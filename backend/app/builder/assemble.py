"""Exam builder and parallel versions (plan 3.2, 3.3, 3.5).

Greedy selection with a repair pass. Each slot (one item of a type) takes the
candidate that best closes the remaining CLO and difficulty deficits. Near-
duplicates of already chosen items (embedding similarity) and items used in
the last N terms are skipped, and the time budget is respected. A swap pass
then tries to close any CLO still short. Whatever can't be met is reported as
a gap, with the request that would fill it.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from app.drafts.quality import Draft, item_text
from app.llm.embeddings import LocalHashEmbedder, cosine
from app.models import Item

from .blueprint import MINUTES_PER_ITEM, POINT_WEIGHT

DUP_THRESHOLD = 0.85


@dataclass
class Built:
    item_ids: list[int]
    points: dict[int, float]
    gaps: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _text(it: Item) -> str:
    return item_text(Draft(it.type, {}, it.body_json, None, None))


def assemble(bp: dict, pool: list[Item], exclude: set[int], recently_used: set[int],
             allow_reuse: bool = False) -> Built:
    weeks = set(bp.get("weeks") or [])
    shares = {int(k): float(v) for k, v in (bp.get("clo_shares") or {}).items()}
    types: dict[str, int] = {t: int(n) for t, n in (bp.get("types") or {}).items() if int(n) > 0}
    total = sum(types.values())
    clo_target = {c: s * total for c, s in shares.items()}
    diff_target = {d: s * total for d, s in (bp.get("difficulty_mix") or {}).items()}
    minutes_cap = float(bp.get("minutes") or 0)

    warnings: list[str] = []

    def eligible(it: Item) -> bool:
        if it.id in exclude or it.status != "approved":
            return False
        if shares and not set(it.clo_ids) & set(shares):
            return False
        return not (weeks and it.week_no is not None and it.week_no not in weeks)

    cands = [it for it in pool if eligible(it)]
    if not allow_reuse:
        reused = [it for it in cands if it.id in recently_used]
        if reused:
            warnings.append(f"Skipped {len(reused)} item(s) used in the last "
                            f"{bp.get('avoid_used_in_last_terms', 2)} term(s).")
        cands = [it for it in cands if it.id not in recently_used]

    emb = LocalHashEmbedder()
    vec = dict(zip([c.id for c in cands], emb.embed([_text(c) for c in cands]))) if cands else {}
    chosen: list[Item] = []
    clo_have: Counter = Counter()
    diff_have: Counter = Counter()
    minutes = 0.0

    def score(it: Item) -> float:
        s = sum(max(0.0, clo_target.get(c, 0) - clo_have[c]) for c in it.clo_ids if c in clo_target)
        s += 0.5 * max(0.0, diff_target.get(it.difficulty or "medium", 0) - diff_have[it.difficulty or "medium"])
        return s

    def is_dup(it: Item) -> bool:
        return any(cosine(vec[it.id], vec[c.id]) >= DUP_THRESHOLD for c in chosen)

    shortfall: dict[str, int] = {}
    for t, n in sorted(types.items(), key=lambda kv: -MINUTES_PER_ITEM.get(kv[0], 1)):
        for _ in range(n):
            opts = [c for c in cands if c.type == t and c not in chosen and not is_dup(c)]
            if minutes_cap:
                opts = [c for c in opts if minutes + MINUTES_PER_ITEM.get(t, 2) <= minutes_cap]
            if not opts:
                shortfall[t] = shortfall.get(t, 0) + 1
                continue
            best = max(opts, key=lambda c: (score(c), -c.id))
            chosen.append(best)
            clo_have.update(c for c in best.clo_ids if c in clo_target)
            diff_have[best.difficulty or "medium"] += 1
            minutes += MINUTES_PER_ITEM.get(t, 2)

    # Repair: swap a chosen item for an unused one of the same type if that
    # reduces the largest CLO deficit without creating a new one.
    for _ in range(len(chosen)):
        deficit = {c: clo_target[c] - clo_have[c] for c in clo_target}
        short = max(deficit, key=lambda c: deficit[c], default=None)
        if short is None or deficit[short] < 1:
            break
        swapped = False
        for i, cur in enumerate(chosen):
            if short in cur.clo_ids:
                continue
            for alt in cands:
                if alt.type != cur.type or alt in chosen or short not in alt.clo_ids:
                    continue
                if any(clo_have[c] - 1 < clo_target.get(c, 0) - 0.5 for c in cur.clo_ids if c in clo_target):
                    continue
                if any(cosine(vec[alt.id], vec[o.id]) >= DUP_THRESHOLD for o in chosen if o is not cur):
                    continue
                clo_have.subtract(c for c in cur.clo_ids if c in clo_target)
                clo_have.update(c for c in alt.clo_ids if c in clo_target)
                chosen[i] = alt
                swapped = True
                break
            if swapped:
                break
        if not swapped:
            break

    gaps = [{"type": t, "count": n, "clo_numbers": sorted(shares), "weeks": sorted(weeks),
             "reason": "not enough approved, unused, non-duplicate items"} for t, n in shortfall.items()]
    for c, target in clo_target.items():
        missing = round(target - clo_have[c])
        if missing >= 1:
            gaps.append({"type": None, "count": missing, "clo_numbers": [c], "weeks": sorted(weeks),
                         "reason": f"CLO {c} is under-covered ({clo_have[c]} of ~{round(target)} items)"})

    return Built([it.id for it in chosen], allocate_points(chosen, float(bp.get("total_points") or 100)), gaps,
                 warnings)


def allocate_points(items: list[Item], total: float) -> dict[int, float]:
    """Points by item type weight, in half-point steps, summing exactly to total
    (largest-remainder rounding)."""
    if not items:
        return {}
    weights = {it.id: POINT_WEIGHT.get(it.type, 2) for it in items}
    tot_w = sum(weights.values())
    halves = round(total * 2)
    raw = {i: halves * w / tot_w for i, w in weights.items()}
    alloc = {i: int(v) for i, v in raw.items()}
    for i in sorted(raw, key=lambda k: raw[k] - alloc[k], reverse=True)[: halves - sum(alloc.values())]:
        alloc[i] += 1
    return {i: a / 2 for i, a in alloc.items()}


def shuffle_options(item: Item, salt: int) -> list[str] | None:
    """A per-version MCQ option order (labels as stored), deterministic per form."""
    if item.type != "mcq":
        return None
    labels = [o["label"] for o in item.body_json.get("options", [])]
    rng = random.Random(f"{salt}:{item.id}")
    rng.shuffle(labels)
    return labels
