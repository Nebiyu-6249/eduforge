"""Calibration harness (plan 4.13): suggested vs faculty marks.

Per item type and overall: exact level agreement, within-one-level agreement,
quadratic weighted kappa (QWK), mean absolute error in points, mean signed
difference (leniency), and a bias check: the correlation between answer length
and (suggested − faculty). Gate 4 (proposed): within-one ≥ 90% and QWK ≥ 0.8
for open answers; 100% for key-scored items.

Levels: points ÷ the item's level step (rubric level gap, or the full points
for right/wrong items), rounded.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CalibrationScore, CalibrationSet, Item, ResponseScore, Submission


@dataclass
class Pair:
    item_type: str
    method: str
    suggested: float | None
    faculty: float
    max_points: float
    step: float
    answer_len: int


def _level(points: float, step: float) -> int:
    return round(points / step) if step > 0 else 0


def qwk(a: list[int], b: list[int]) -> float | None:
    if not a:
        return None
    lo, hi = min(a + b), max(a + b)
    k = hi - lo + 1
    if k == 1:
        return 1.0
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        obs[x - lo][y - lo] += 1
    ha = [sum(r) for r in obs]
    hb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    n = len(a)
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * obs[i][j]
            den += w * ha[i] * hb[j] / n
    return 1.0 if den == 0 else 1 - num / den


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / (sx * sy)


def summarise(pairs: list[Pair]) -> dict:
    with_s = [p for p in pairs if p.suggested is not None]
    la = [_level(p.suggested or 0, p.step) for p in with_s]
    lb = [_level(p.faculty, p.step) for p in with_s]
    n = len(with_s)
    diffs = [(p.suggested or 0) - p.faculty for p in with_s]
    k = qwk(la, lb)
    r = _pearson([float(p.answer_len) for p in with_s], diffs)
    return {
        "n": len(pairs), "suggested": n,
        "exact": round(sum(1 for x, y in zip(la, lb, strict=True) if x == y) / n, 3) if n else None,
        "within_one": round(sum(1 for x, y in zip(la, lb, strict=True) if abs(x - y) <= 1) / n, 3) if n else None,
        "qwk": round(k, 3) if k is not None else None,
        "mae": round(sum(abs(d) for d in diffs) / n, 2) if n else None,
        "mean_diff": round(sum(diffs) / n, 2) if n else None,
        "length_bias_r": round(r, 2) if r is not None else None,
    }


def pairs_for(db: Session, cal: CalibrationSet) -> list[Pair]:
    out = []
    rows = db.execute(select(CalibrationScore, ResponseScore, Item, Submission)
                      .join(ResponseScore, (ResponseScore.submission_id == CalibrationScore.submission_id)
                            & (ResponseScore.item_id == CalibrationScore.item_id))
                      .join(Item, Item.id == CalibrationScore.item_id)
                      .join(Submission, Submission.id == CalibrationScore.submission_id)
                      .where(CalibrationScore.calibration_id == cal.id)).all()
    for cs, rs, it, sub in rows:
        ans = next((a["text"] for a in sub.answers if a["item_id"] == it.id), "")
        out.append(Pair(it.type, rs.method, rs.suggested_points, cs.faculty_points, rs.max_points,
                        rs.level_step or rs.max_points, len(ans)))
    return out


def report(pairs: list[Pair]) -> dict:
    groups: dict[str, list[Pair]] = defaultdict(list)
    for p in pairs:
        groups[p.item_type].append(p)
        groups["key-scored" if p.method == "key" else "open (rubric/code)"].append(p)
    rows = {k: summarise(v) for k, v in sorted(groups.items())}
    rows["all"] = summarise(pairs)
    return rows


def gate(rows: dict) -> list[str]:
    """Which groups miss the proposed Gate 4 thresholds."""
    out = []
    key = rows.get("key-scored")
    if key and key["suggested"] and key["exact"] is not None and key["exact"] < 1:
        out.append(f"key-scored exact agreement {key['exact']:.0%} < 100%")
    op = rows.get("open (rubric/code)")
    if op and op["suggested"]:
        if (op["within_one"] or 0) < 0.9:
            out.append(f"open answers within-one {op['within_one']:.0%} < 90%")
        if op["qwk"] is not None and op["qwk"] < 0.8:
            out.append(f"open answers QWK {op['qwk']:.2f} < 0.80")
    return out


def table(rows: dict) -> str:
    cols = ["n", "suggested", "exact", "within_one", "qwk", "mae", "mean_diff", "length_bias_r"]
    w = max(len(k) for k in rows) + 2
    lines = ["group".ljust(w) + "".join(c.rjust(14) for c in cols)]
    for k, r in rows.items():
        lines.append(k.ljust(w) + "".join(("—" if r[c] is None else str(r[c])).rjust(14) for c in cols))
    return "\n".join(lines)
