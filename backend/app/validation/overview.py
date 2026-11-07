"""One reconciliation row per assessment (plan 1.13, faculty usability).

An assessment appears in up to three places in the record: the weight table
(``/weights``), the CLO x assessment matrix (``/clo_matrix``) and the weekly
schedule (``/weekly/{i}/assessments/{k}``, with the CLOs for that week in
``/weekly/{i}/clo_numbers``). Rules V2-V6 and V9 all flag disagreements
between those places, and faculty used to have to hunt across three tabs to
settle one of them.

This module reuses :func:`app.validation.matching.match_all` to put the three
sides of one assessment on a single row, together with the open flags whose
evidence points at any part of that row. The UI renders one table from it and
edits a row in one dialog, so a fix is one save and one coherent set of log
entries.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.extraction.normalize import canonical_name, category_of
from app.extraction.schema import ExtractedSyllabus

from .matching import match_all

_DAY_NAMES = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
_WEEKDAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Rules this view is meant to help settle; only these can be listed as
# "not pinned to a row" so the UI never claims to cover something it doesn't.
ASSESSMENT_RULES = {"V1", "V2", "V3", "V4", "V5", "V6", "V8", "V9"}

# An evidence ref shallower than this many tokens is about a whole table
# ('/weights', '/clos'), not about one assessment, so it is not pinned to a row.
_MIN_REF_DEPTH = 2


class FlagLike(Protocol):
    """The parts of a stored validator flag this module reads."""

    id: int
    rule_id: str
    severity: str
    message: str
    status: str
    evidence_refs: Any


class WeightCell(BaseModel):
    index: int
    name: str
    weight_pct: float | None = None


class MatrixCell(BaseModel):
    index: int
    assessment: str
    clo_numbers: list[int] = Field(default_factory=list)


class ScheduleCell(BaseModel):
    week_index: int
    item_index: int
    week_no: int
    name: str
    weight_pct: float | None = None
    due_date: date | None = None
    due_week: int | None = None
    due_text_raw: str | None = None
    clo_numbers: list[int] = Field(default_factory=list)  # CLOs the schedule lists for this week row
    shared_week: bool = False  # the week row lists more than one assessment
    due_on_meeting_day: bool | None = None  # None when there is no date or no meeting days


class RowFlag(BaseModel):
    id: int
    rule_id: str
    severity: str
    message: str


class AssessmentRow(BaseModel):
    key: str  # canonical name; stable across edits of the display name
    name: str
    weight: WeightCell | None = None
    matrix: MatrixCell | None = None
    schedule: list[ScheduleCell] = Field(default_factory=list)
    schedule_clo_numbers: list[int] = Field(default_factory=list)  # union over the scheduled weeks
    schedule_weight_total: float | None = None
    by_category: bool = False
    pointers: list[str] = Field(default_factory=list)
    flags: list[RowFlag] = Field(default_factory=list)
    status: Literal["ok", "warning", "error"] = "ok"


class WeekOption(BaseModel):
    index: int
    week_no: int
    topics: list[str] = Field(default_factory=list)


class AssessmentOverview(BaseModel):
    rows: list[AssessmentRow]
    clo_numbers: list[int]
    weeks: list[WeekOption]
    meeting_days: list[str]
    meeting_days_label: str
    weight_total: float | None = None
    unrowed_flags: list[RowFlag] = Field(default_factory=list)


def _sched_ptr(wi: int, ai: int) -> str:
    return f"/weekly/{wi}/assessments/{ai}"


def _touches(ref: str, ptr: str) -> bool:
    if ref == ptr or ref.startswith(ptr + "/"):
        return True
    if ptr.startswith(ref + "/"):
        return len([t for t in ref.split("/") if t]) >= _MIN_REF_DEPTH
    return False


def _cell(rec: ExtractedSyllabus, wi: int, ai: int, meeting_days: set[str]) -> ScheduleCell:
    w = rec.weekly[wi]
    a = w.assessments[ai]
    on_day: bool | None = None
    if a.due_date and meeting_days:
        on_day = _WEEKDAY[a.due_date.weekday()] in meeting_days
    return ScheduleCell(
        week_index=wi, item_index=ai, week_no=w.week_no, name=a.name, weight_pct=a.weight_pct,
        due_date=a.due_date, due_week=a.due_week, due_text_raw=a.due_text_raw,
        clo_numbers=sorted(w.clo_numbers), shared_week=len(w.assessments) > 1, due_on_meeting_day=on_day,
    )


def _finish(row: AssessmentRow, flags: list[FlagLike]) -> AssessmentRow:
    ptrs: list[str] = []
    if row.weight is not None:
        ptrs.append(f"/weights/{row.weight.index}")
    if row.matrix is not None:
        ptrs.append(f"/clo_matrix/{row.matrix.index}")
    for c in row.schedule:
        ptrs.append(_sched_ptr(c.week_index, c.item_index))
        ptrs.append(f"/weekly/{c.week_index}/clo_numbers")
    row.pointers = list(dict.fromkeys(ptrs))

    clos: set[int] = set()
    for c in row.schedule:
        clos.update(c.clo_numbers)
    row.schedule_clo_numbers = sorted(clos)
    if row.schedule and any(c.weight_pct is not None for c in row.schedule):
        row.schedule_weight_total = sum(c.weight_pct or 0 for c in row.schedule)

    hits = [f for f in flags
            if any(_touches(r, p) for r in (f.evidence_refs or []) for p in row.pointers)]
    row.flags = [RowFlag(id=f.id, rule_id=f.rule_id, severity=f.severity, message=f.message) for f in hits]
    if any(f.severity == "error" for f in row.flags):
        row.status = "error"
    elif row.flags:
        row.status = "warning"
    return row


def overview(rec: ExtractedSyllabus, flags: list[FlagLike]) -> AssessmentOverview:
    """Build the reconciliation rows. ``flags`` may include settled flags; only
    open ones are pinned to a row."""
    open_flags = [f for f in flags if f.status == "open"]
    m = match_all(rec)
    days = rec.meeting_days()
    rows: list[AssessmentRow] = []
    used_sched: set[tuple[int, int]] = set()
    used_matrix: set[int] = set()

    # 1. One row per weight-table entry, in table order.
    for i, w in enumerate(rec.weights):
        match = m.weight_to_sched[i]
        j = m.weight_to_matrix.get(i)
        row = AssessmentRow(key=canonical_name(w.name), name=w.name, by_category=match.by_category,
                            weight=WeightCell(index=i, name=w.name, weight_pct=w.weight_pct))
        if j is not None:
            col = rec.clo_matrix[j]
            row.matrix = MatrixCell(index=j, assessment=col.assessment, clo_numbers=sorted(col.clo_numbers))
            used_matrix.add(j)
        row.schedule = [_cell(rec, wi, ai, days) for wi, ai in sorted(match.sched)]
        used_sched.update(match.sched)
        rows.append(_finish(row, open_flags))

    # 2. Matrix columns with no weight-table entry (V3 warning).
    for j, col in enumerate(rec.clo_matrix):
        if j in used_matrix:
            continue
        refs = [r for r in m.matrix_to_sched[j].sched if r not in used_sched]
        row = AssessmentRow(key=canonical_name(col.assessment), name=col.assessment,
                            by_category=m.matrix_to_sched[j].by_category,
                            matrix=MatrixCell(index=j, assessment=col.assessment,
                                              clo_numbers=sorted(col.clo_numbers)))
        row.schedule = [_cell(rec, wi, ai, days) for wi, ai in sorted(refs)]
        used_sched.update(refs)
        rows.append(_finish(row, open_flags))

    # 3. Scheduled items with no weight-table entry, grouped the way V3 groups
    #    them (by category, so HW1..HW4 is one row).
    groups: dict[str, list[tuple[int, int]]] = {}
    for ref in m.unmatched_sched:
        if ref in used_sched:
            continue
        a = rec.weekly[ref[0]].assessments[ref[1]]
        groups.setdefault(category_of(a.name) or canonical_name(a.name), []).append(ref)
    for key, refs in groups.items():
        first = rec.weekly[refs[0][0]].assessments[refs[0][1]]
        name = first.name if len(refs) == 1 else f"{key.title()} ({len(refs)} in the schedule)"
        row = AssessmentRow(key=key, name=name)
        row.schedule = [_cell(rec, wi, ai, days) for wi, ai in sorted(refs)]
        rows.append(_finish(row, open_flags))

    pinned = {f.id for r in rows for f in r.flags}
    unrowed = [RowFlag(id=f.id, rule_id=f.rule_id, severity=f.severity, message=f.message)
               for f in open_flags if f.id not in pinned and f.rule_id in ASSESSMENT_RULES]
    total = sum(w.weight_pct or 0 for w in rec.weights) if rec.weights else None
    return AssessmentOverview(
        rows=rows,
        clo_numbers=[c.number for c in rec.clos],
        weeks=[WeekOption(index=i, week_no=w.week_no, topics=w.topics) for i, w in enumerate(rec.weekly)],
        meeting_days=[d for d in _WEEKDAY if d in days],
        meeting_days_label="/".join(_DAY_NAMES[d] for d in _WEEKDAY if d in days),
        weight_total=total,
        unrowed_flags=unrowed,
    )


__all__ = ["ASSESSMENT_RULES", "AssessmentOverview", "AssessmentRow", "overview"]
