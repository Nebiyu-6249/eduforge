"""Term-to-term syllabus comparison (plan 3.8).

When a new version is locked, diff it against the previous locked version of
the same course: CLOs (added / removed / reworded), weights, assessments and
weekly topics. The faculty member's approved items tied to a changed or
removed CLO go to `needs_review`: they can't be exported or built into exams
until re-approved.
"""

from __future__ import annotations

import difflib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extraction.normalize import canonical_name
from app.extraction.schema import ExtractedSyllabus
from app.models import CourseVersion, Faculty, Item, ReviewEvent, VersionDiff


def diff(old: ExtractedSyllabus, new: ExtractedSyllabus) -> dict:
    o = {c.number: c.text for c in old.clos}
    n = {c.number: c.text for c in new.clos}
    changed = {k: {"from": o[k], "to": n[k]} for k in o.keys() & n.keys()
               if difflib.SequenceMatcher(None, o[k].lower(), n[k].lower()).ratio() < 0.9}
    ow = {canonical_name(w.name): w.weight_pct for w in old.weights}
    nw = {canonical_name(w.name): w.weight_pct for w in new.weights}
    otop = {w.week_no: "; ".join(w.topics) for w in old.weekly}
    ntop = {w.week_no: "; ".join(w.topics) for w in new.weekly}
    return {
        "clos_added": sorted(n.keys() - o.keys()),
        "clos_removed": sorted(o.keys() - n.keys()),
        "clos_changed": {str(k): v for k, v in sorted(changed.items())},
        "weights_changed": {k: {"from": ow[k], "to": nw[k]} for k in ow.keys() & nw.keys() if ow[k] != nw[k]},
        "assessments_added": sorted(nw.keys() - ow.keys()),
        "assessments_removed": sorted(ow.keys() - nw.keys()),
        "weeks_changed": sorted(k for k in otop.keys() & ntop.keys() if otop[k] != ntop[k]),
    }


def on_lock(db: Session, cv: CourseVersion, me: Faculty) -> VersionDiff | None:
    prev = db.scalar(select(CourseVersion).where(
        CourseVersion.course_id == cv.course_id, CourseVersion.faculty_id == me.id, CourseVersion.id != cv.id,
        CourseVersion.status.in_(("locked", "superseded"))).order_by(CourseVersion.locked_at.desc()).limit(1))
    if prev is None:
        return None
    d = diff(ExtractedSyllabus.model_validate(prev.record), ExtractedSyllabus.model_validate(cv.record))
    touched = set(d["clos_removed"]) | {int(k) for k in d["clos_changed"]}
    affected: list[int] = []
    if touched:
        items = db.scalars(select(Item).join(CourseVersion, Item.course_version_id == CourseVersion.id).where(
            CourseVersion.course_id == cv.course_id, CourseVersion.faculty_id == me.id,
            Item.status == "approved")).all()
        label = f"{cv.term or ''} v{cv.version_no or ''}".strip()
        for it in items:
            hit = sorted(set(it.clo_ids) & touched)
            if hit:
                it.status = "needs_review"
                it.events.append(ReviewEvent(action="needs_review", by_id=me.id,
                                             notes=f"Outcome {', '.join(map(str, hit))} changed or was removed in {label}."))
                affected.append(it.id)
    vd = VersionDiff(from_version_id=prev.id, to_version_id=cv.id, diff=d, affected_item_ids=affected)
    db.add(vd)
    db.flush()
    return vd
