"""Built-in metrics for the team (plan 2.11; gate 2 in 14.3).

Per item type, course and prompt version:

* approval rate      = approved / (approved + rejected)
* edit size          = 1 - difflib ratio between the model's draft text and
                       the approved text (0 = untouched, 1 = rewritten)
* light-edit rate    = approved items with edit size <= LIGHT_EDIT (gate 2:
                       ≥70% of pilot drafts approved with light edits)
* rejection reasons  = notes on reject / regenerate events
* time to review     = median hours from draft to its first approve/reject

The dashboard is for the team, not faculty (TEAM_EMAILS).
"""

from __future__ import annotations

import difflib
import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .drafts.quality import Draft, item_text
from .models import Course, CourseVersion, Item

LIGHT_EDIT = 0.2  # the team must fix this before the pilot starts (plan 14.3 gate 2)


def _text(body: dict | None, key: dict | None, item_type: str) -> str:
    return item_text(Draft(item_type, {}, body or {}, key, None)) + "\n" + str(key or "")


def edit_size(item: Item) -> float | None:
    """How much faculty changed the model's draft before approval (0..1)."""
    revs = item.revisions
    if not revs:
        return None
    original = next((r for r in revs if r.source == "model"), revs[0])
    a = _text(original.body_json, original.answer_key_json, item.type)
    b = _text(item.body_json, item.answer_key_json, item.type)
    return round(1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


def compute(db: Session) -> dict:
    rows = db.execute(select(Item, CourseVersion, Course).join(CourseVersion, Item.course_version_id == CourseVersion.id)
                      .join(Course, CourseVersion.course_id == Course.id)).all()
    groups: dict[tuple[str, str, str], list[Item]] = defaultdict(list)
    for item, _cv, course in rows:
        groups[(item.type, course.code, item.prompt_version)].append(item)

    def summarise(items: list[Item]) -> dict:
        approved = [i for i in items if i.status == "approved"]
        rejected = [i for i in items if i.status == "rejected"]
        decided = len(approved) + len(rejected)
        sizes = [s for i in approved if (s := edit_size(i)) is not None]
        reasons = [e.notes for i in items for e in i.events if e.action in {"reject", "regenerate"} and e.notes]
        hours = []
        for i in items:
            first = next((e for e in i.events if e.action in {"approve", "reject", "regenerate"}), None)
            if first:
                hours.append((first.at - i.created_at).total_seconds() / 3600)
        return {
            "drafts": len(items),
            "approved": len(approved),
            "rejected": len(rejected),
            "pending": len(items) - decided,
            "approval_rate": round(len(approved) / decided, 3) if decided else None,
            "median_edit_size": round(statistics.median(sizes), 3) if sizes else None,
            "light_edit_rate": round(sum(1 for s in sizes if s <= LIGHT_EDIT) / len(approved), 3) if approved else None,
            "median_hours_to_review": round(statistics.median(hours), 2) if hours else None,
            "rejection_reasons": reasons[-20:],
        }

    by_group = [{"type": t, "course": c, "prompt_version": pv, **summarise(items)}
                for (t, c, pv), items in sorted(groups.items())]
    every = [i for items in groups.values() for i in items]
    by_type = {t: summarise([i for i in every if i.type == t]) for t in sorted({i.type for i in every})}
    overall = summarise(every)
    return {
        "light_edit_threshold": LIGHT_EDIT,
        "overall": overall,
        "gate2_light_edit_rate": overall["light_edit_rate"],
        "by_type": by_type,
        "by_group": by_group,
    }
