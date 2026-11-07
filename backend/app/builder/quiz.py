"""Make a whole quiz in one request.

A teacher says "for Quiz 2, give me 3 multiple-choice and 2 short-answer
questions" and presses one button. This runs the existing generation service
once per question type, keeps the quality checks, and assembles the new
questions into an assessment paper in the order the teacher asked for, so
there is nothing to stitch together afterwards.

The faculty-in-the-loop rules are unchanged (plan 14.10): questions come only
from a confirmed syllabus, every new question starts as a draft the teacher
must approve, and the paper starts as a draft that cannot be exported until it
is approved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.drafts import service as drafts
from app.drafts.schemas import ITEM_TYPES, TYPE_LABELS
from app.models import AssessmentForm, CourseVersion, Faculty, FormItem, Item
from app.services.course_versions import WorkflowError

from . import assemble

MAX_QUESTIONS = 20
DEFAULT_POINTS = {"mcq": 2.0, "short_answer": 5.0, "problem": 10.0, "code_exercise": 10.0,
                  "practice_set": 10.0, "case_study": 15.0}


@dataclass
class MixPart:
    type: str
    count: int
    points: float | None = None


def parse_mix(mix: list[dict]) -> list[MixPart]:
    out: list[MixPart] = []
    for part in mix:
        t = str(part.get("type", ""))
        n = int(part.get("count", 0) or 0)
        if n <= 0:
            continue
        if t not in ITEM_TYPES:
            raise WorkflowError(f"'{t}' is not a kind of question this tool writes.", 422)
        pts = part.get("points")
        out.append(MixPart(type=t, count=n, points=float(pts) if pts is not None else None))
    if not out:
        raise WorkflowError("Choose at least one question.", 422)
    total = sum(p.count for p in out)
    if total > MAX_QUESTIONS:
        raise WorkflowError(f"Ask for up to {MAX_QUESTIONS} questions at a time; you asked for {total}.", 422)
    return out


def check_request(cv: CourseVersion, me: Faculty, mix: list[MixPart], clo_numbers: list[int],
                  weeks: list[int], difficulty: str | None) -> None:
    """Refuse a request that cannot work, before any model is called, so the
    teacher gets one clear message instead of a half-built paper."""
    if cv.faculty_id != me.id:
        raise WorkflowError("Not your course.", 404)
    if cv.status != "locked":
        raise WorkflowError("Confirm the syllabus for this term before writing questions.", 409)
    for part in mix:
        drafts.check_request(cv, me, part.type, clo_numbers, weeks, part.count, difficulty, None)


def create(db: Session, cv: CourseVersion, me: Faculty, *, assessment_name: str | None, mix: list[MixPart],
           clo_numbers: list[int], weeks: list[int], difficulty: str | None, notes: str | None,
           progress: Callable[[int, str], None] | None = None) -> AssessmentForm:
    """Generate every part of the mix and assemble the paper. One job."""
    step = progress or (lambda pct, msg: None)
    check_request(cv, me, mix, clo_numbers, weeks, difficulty)

    from sqlalchemy import select

    total = sum(p.count for p in mix)
    made: list[tuple[MixPart, list[Item]]] = []
    done = 0
    for part in mix:
        label = TYPE_LABELS[part.type].lower()
        base, span = 5 + 80 * done / total, 80 * part.count / total

        def inner(pct: int, msg: str, _base: float = base, _span: float = span) -> None:
            step(int(_base + _span * pct / 100), msg)

        step(int(base), f"Writing {part.count} {label}{'s' if part.count != 1 else ''}")
        req = drafts.request_drafts(db, cv, me, part.type, clo_numbers, weeks, part.count, difficulty, None,
                                    notes, progress=inner)
        items = list(db.scalars(select(Item).where(Item.request_id == req.id).order_by(Item.id)).all())
        made.append((part, items))
        done += part.count

    step(90, "Putting the paper together")
    name = assessment_name or "Practice questions"
    form = AssessmentForm(course_version_id=cv.id, assessment_name=name, version_label="A", status="draft",
                          blueprint={"assessment": name, "weeks": sorted(weeks), "clo_numbers": sorted(clo_numbers),
                                     "difficulty": difficulty or "medium",
                                     "types": {p.type: p.count for p in mix},
                                     "total_points": _total_points(made),
                                     "made_in_one_step": True},
                          gaps=_gaps(made), created_by_id=me.id)
    db.add(form)
    db.flush()
    pos = 0
    for part, items in made:
        points = part.points if part.points is not None else DEFAULT_POINTS.get(part.type, 5.0)
        for it in items:
            pos += 1
            form.items.append(FormItem(item_id=it.id, position=pos, points=points,
                                       option_order=assemble.shuffle_options(it, form.id)))
    db.flush()
    step(100, "Ready for your review")
    return form


def _total_points(made: list[tuple[MixPart, list[Item]]]) -> float:
    return sum((p.points if p.points is not None else DEFAULT_POINTS.get(p.type, 5.0)) * len(items)
               for p, items in made)


def _gaps(made: list[tuple[MixPart, list[Item]]]) -> list[dict]:
    """Said in plain words: what the teacher asked for and did not get."""
    out = []
    for part, items in made:
        if len(items) < part.count:
            short = part.count - len(items)
            label = TYPE_LABELS[part.type].lower()
            out.append({"warning": f"You asked for {part.count} {label}{'s' if part.count != 1 else ''} and "
                                   f"got {len(items)}. {short} could not be written; try again, or add a "
                                   f"question yourself."})
    return out


__all__ = ["DEFAULT_POINTS", "MAX_QUESTIONS", "MixPart", "check_request", "create", "parse_mix"]
