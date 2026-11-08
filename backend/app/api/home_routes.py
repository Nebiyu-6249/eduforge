"""The home screen: dashboard, search and notifications.

One request fills the dashboard, so the first screen a teacher sees loads in
one go. Everything here is scoped to the signed-in teacher's own courses, the
same rule as the rest of the API.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_faculty
from app.db import get_db
from app.extraction.schema import ExtractedSyllabus
from app.models import (
    AssessmentForm,
    CourseVersion,
    Faculty,
    Item,
    Job,
    NotificationRead,
    utcnow,
)

router = APIRouter(prefix="/api")

LIVE = ("extracted", "in_review", "locked")
REVIEWABLE = ("suggested", "under_review", "needs_review")


# --------------------------------------------------------------------------- #
# Shapes
# --------------------------------------------------------------------------- #

class Kpi(BaseModel):
    key: str
    label: str
    value: int
    note: str  # one line saying what the number means
    href: str


class DayCount(BaseModel):
    day: str  # Mon … Sun
    date: str
    created: int
    approved: int


class CourseCard(BaseModel):
    id: int
    code: str
    title: str
    term: str
    initials: str
    status: str  # plain words
    tone: str  # ok | attention | neutral
    href: str


class Readiness(BaseModel):
    confirmed: int
    ready: int
    needs_checking: int
    total: int


class NextAssessment(BaseModel):
    course_version_id: int
    course: str
    name: str
    due: str  # "Tue 10 November"
    days_away: int
    href: str


class Dashboard(BaseModel):
    teacher: str
    term: str | None
    kpis: list[Kpi]
    week: list[DayCount]
    courses: list[CourseCard]
    readiness: Readiness
    next_assessment: NextAssessment | None = None


class SearchHit(BaseModel):
    kind: str  # course | question
    title: str
    subtitle: str
    href: str


class Notification(BaseModel):
    key: str
    title: str
    body: str
    href: str
    read: bool = False


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _mine(db: Session, me: Faculty) -> list[CourseVersion]:
    return list(db.scalars(
        select(CourseVersion).where(CourseVersion.faculty_id == me.id, CourseVersion.status.in_(LIVE))
        .order_by(CourseVersion.id.desc())).all())


def _initials(code: str) -> str:
    """Two letters for the avatar. A course code is letters then a number
    ("CSAI 351"), so take the letters: CS, not C3."""
    letters = "".join(ch for ch in (code or "") if ch.isalpha())
    return (letters[:2] or "?").upper()


def _code(cv: CourseVersion) -> str:
    return (cv.record.get("course", {}) or {}).get("code") or "Untitled course"


def _title(cv: CourseVersion) -> str:
    return (cv.record.get("course", {}) or {}).get("title") or ""


def _term(cv: CourseVersion) -> str:
    return cv.term or (cv.record.get("offering", {}) or {}).get("term") or "No term"


def _open_blocking(cv: CourseVersion) -> int:
    return sum(1 for f in cv.flags if f.status == "open" and f.severity != "info")


def _latest_term(versions: list[CourseVersion]) -> str | None:
    """The term the teacher is working in: the one most of their live courses
    sit in, preferring the most recently touched."""
    counts: dict[str, int] = defaultdict(int)
    for cv in versions:
        counts[_term(cv)] += 1
    if not counts:
        return None
    return max(counts, key=lambda t: (counts[t], t))


def _course_card(cv: CourseVersion, waiting: int) -> CourseCard:
    blocking = _open_blocking(cv)
    if cv.status == "locked":
        status = f"{waiting} questions to review" if waiting else "Confirmed"
        tone = "attention" if waiting else "ok"
    elif blocking:
        status = f"{blocking} thing{'s' if blocking != 1 else ''} to check"
        tone = "attention"
    else:
        status = "Ready to confirm"
        tone = "neutral"
    return CourseCard(id=cv.id, code=_code(cv), title=_title(cv), term=_term(cv),
                      initials=_initials(_code(cv)), status=status, tone=tone, href=f"/v/{cv.id}")


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

@router.get("/dashboard", response_model=Dashboard)
def dashboard(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)) -> Dashboard:
    versions = _mine(db, me)
    ids = [cv.id for cv in versions]
    term = _latest_term(versions)
    this_term = [cv for cv in versions if _term(cv) == term] if term else versions

    items = list(db.scalars(select(Item).where(Item.course_version_id.in_(ids))).all()) if ids else []
    waiting_by_cv: dict[int, int] = defaultdict(int)
    for it in items:
        if it.status in REVIEWABLE:
            waiting_by_cv[it.course_version_id] += 1

    to_check = sum(_open_blocking(cv) for cv in versions if cv.status != "locked")
    waiting = sum(waiting_by_cv.values())
    approved = sum(1 for it in items if it.status == "approved")

    kpis = [
        Kpi(key="courses", label="Courses this term", value=len(this_term),
            note=f"Syllabuses you are working on for {term}" if term else "Upload a syllabus to start",
            href="/courses"),
        Kpi(key="to_check", label="Things to check", value=to_check,
            note="Found in syllabuses you have not confirmed yet", href="/courses?filter=to_check"),
        Kpi(key="waiting", label="Questions waiting for review", value=waiting,
            note="Drafts that need your approval before you can use them", href="/questions?filter=waiting"),
        Kpi(key="approved", label="Approved questions", value=approved,
            note="Ready to put in a quiz or exam", href="/questions?filter=approved"),
    ]

    # Seven days ending today, Monday first.
    today = date.today()
    start = today - timedelta(days=6)
    buckets = {start + timedelta(days=i): [0, 0] for i in range(7)}
    for it in items:
        made = it.created_at.date() if isinstance(it.created_at, datetime) else None
        if made in buckets:
            buckets[made][0] += 1
        ok = it.approved_at.date() if it.approved_at else None
        if ok in buckets:
            buckets[ok][1] += 1
    week = [DayCount(day=d.strftime("%a"), date=d.isoformat(), created=c, approved=a)
            for d, (c, a) in sorted(buckets.items())]

    cards = [_course_card(cv, waiting_by_cv.get(cv.id, 0)) for cv in this_term[:8]]
    readiness = Readiness(
        confirmed=sum(1 for cv in this_term if cv.status == "locked"),
        ready=sum(1 for cv in this_term if cv.status != "locked" and _open_blocking(cv) == 0),
        needs_checking=sum(1 for cv in this_term if cv.status != "locked" and _open_blocking(cv) > 0),
        total=len(this_term),
    )
    return Dashboard(teacher=me.name, term=term, kpis=kpis, week=week, courses=cards, readiness=readiness,
                     next_assessment=_next_assessment(versions))


def _next_assessment(versions: list[CourseVersion]) -> NextAssessment | None:
    """The soonest upcoming assessment across confirmed syllabuses."""
    today = date.today()
    best: tuple[date, CourseVersion, str] | None = None
    for cv in versions:
        if cv.status != "locked":
            continue
        try:
            rec = ExtractedSyllabus.model_validate(cv.record)
        except ValidationError:  # a half-read record must not break the home screen
            continue
        for _wi, _ai, a in rec.scheduled_assessments():
            if a.due_date and a.due_date >= today and (best is None or a.due_date < best[0]):
                best = (a.due_date, cv, a.name)
    if best is None:
        return None
    due, cv, name = best
    return NextAssessment(
        course_version_id=cv.id, course=_code(cv), name=name,
        due=f"{due:%a} {due.day} {due:%B}", days_away=(due - today).days,
        href=f"/v/{cv.id}/quiz/new?step=2&for={quote(name)}",
    )


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

def _question_text(it: Item) -> str:
    b = it.body_json or {}
    for key in ("stem", "question", "statement", "title", "prompt", "scenario"):
        if b.get(key):
            return str(b[key])
    return ""


@router.get("/search", response_model=list[SearchHit])
def search(q: str = "", limit: int = 12, db: Session = Depends(get_db),
           me: Faculty = Depends(current_faculty)) -> list[SearchHit]:
    """Courses and approved questions of this teacher only."""
    needle = q.strip().lower()
    if len(needle) < 2:
        return []
    hits: list[SearchHit] = []
    versions = _mine(db, me)
    for cv in versions:
        if needle in f"{_code(cv)} {_title(cv)} {_term(cv)}".lower():
            hits.append(SearchHit(kind="course", title=f"{_code(cv)} {_title(cv)}".strip(),
                                  subtitle=_term(cv), href=f"/v/{cv.id}"))
    ids = [cv.id for cv in versions]
    if ids:
        for it in db.scalars(select(Item).where(Item.course_version_id.in_(ids),
                                                Item.status == "approved").order_by(Item.id.desc())).all():
            text = _question_text(it)
            if needle in text.lower():
                hits.append(SearchHit(kind="question", title=text[:120],
                                      subtitle=f"Approved question in {_code(it.course_version)}",
                                      href=f"/v/{it.course_version_id}/questions?item={it.id}"))
    return hits[:limit]


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

class ReadIn(BaseModel):
    keys: list[str] = Field(default_factory=list)


def _notifications(db: Session, me: Faculty) -> list[Notification]:
    out: list[Notification] = []
    for cv in _mine(db, me):
        code = _code(cv)
        blocking = _open_blocking(cv)
        if cv.status != "locked" and blocking:
            out.append(Notification(
                key=f"check:{cv.id}:{blocking}",
                title=f"{code}: {blocking} thing{'s' if blocking != 1 else ''} to check",
                body="Settle these before you confirm the syllabus for the term.",
                href=f"/v/{cv.id}"))
        elif cv.status != "locked":
            out.append(Notification(
                key=f"ready:{cv.id}",
                title=f"{code} is ready to confirm",
                body="Nothing left to check. Confirm it to start writing questions.",
                href=f"/v/{cv.id}"))
        waiting = db.scalar(select(Item.id).where(Item.course_version_id == cv.id,
                                                  Item.status.in_(REVIEWABLE)).limit(1))
        if waiting:
            n = len(list(db.scalars(select(Item.id).where(Item.course_version_id == cv.id,
                                                          Item.status.in_(REVIEWABLE))).all()))
            out.append(Notification(
                key=f"drafts:{cv.id}:{n}",
                title=f"{code}: {n} question{'s' if n != 1 else ''} waiting for review",
                body="Approve, edit or replace each one before you use it.",
                href=f"/v/{cv.id}/questions"))
        draft_forms = list(db.scalars(select(AssessmentForm).where(
            AssessmentForm.course_version_id == cv.id, AssessmentForm.status == "draft")).all())
        for f in draft_forms:
            out.append(Notification(
                key=f"form:{f.id}",
                title=f"{code}: {f.assessment_name} is not approved yet",
                body="Approve the paper to download it or send it to Blackboard.",
                href=f"/v/{cv.id}/quiz/{f.id}"))
    # Work that finished in the last day (round 3): a teacher who walked away
    # learns here that the quiz or the slides are ready, and clicks through.
    day_ago = utcnow() - timedelta(hours=24)
    for job in db.scalars(select(Job).where(Job.faculty_id == me.id, Job.status.in_(("done", "failed")),
                                            Job.finished_at >= day_ago, Job.title.is_not(None))
                          .order_by(Job.finished_at.desc()).limit(10)):
        ok = job.status == "done"
        out.append(Notification(
            key=f"job:{job.id}",
            title=f"{job.title} is ready" if ok else f"{job.title} could not be finished",
            body="Open it to see the result." if ok else (job.error or "Something went wrong. Try again."),
            href=job.link or "/"))
    seen = {k for (k,) in db.execute(select(NotificationRead.key)
                                     .where(NotificationRead.faculty_id == me.id)).all()}
    for note in out:
        note.read = note.key in seen
    return out


@router.get("/notifications", response_model=list[Notification])
def notifications(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)) -> list[Notification]:
    return _notifications(db, me)


@router.post("/notifications/read", status_code=204)
def mark_read(body: ReadIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)) -> None:
    keys = body.keys or [n.key for n in _notifications(db, me)]
    have = {k for (k,) in db.execute(select(NotificationRead.key)
                                     .where(NotificationRead.faculty_id == me.id)).all()}
    for k in keys:
        if k not in have:
            db.add(NotificationRead(faculty_id=me.id, key=k[:200], at=utcnow()))
    db.commit()


# The validator flags are the one place an unresolved count appears in two
# screens; keep the names in one module so they cannot drift.
__all__ = ["router"]
