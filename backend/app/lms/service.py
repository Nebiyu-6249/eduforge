"""Blackboard workflow (plan 5.1–5.6).

Invariants (tests/test_lms.py):
* only approved forms are pushed;
* course links need the course code and term to match (wrong-course protection);
* grades are written only when every mark of the section is faculty-confirmed;
  a dry-run diff comes first; a grade changed in Blackboard since this tool last
  wrote it is never overwritten unless the faculty member says so;
* every request is logged (LmsSync.request_log); re-runs are idempotent.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.config import get_settings
from app.extraction.schema import ExtractedSyllabus
from app.grading import identity, intake
from app.grading import service as grading
from app.grading.identity import Person
from app.models import (
    AssessmentForm,
    CourseVersion,
    Faculty,
    FeedbackDraft,
    GradeRelease,
    LmsColumnLink,
    LmsLink,
    LmsSync,
    LmsToken,
    Section,
)
from app.services.course_versions import WorkflowError

from . import fake_blackboard
from .adapter import CallLog, LmsAdapter, LmsCourse, LmsError, Token
from .blackboard import BlackboardAdapter

_override: Callable[[CallLog, Callable[[Token], None] | None], LmsAdapter] | None = None


def set_adapter_override(factory: Callable[[CallLog, Callable[[Token], None] | None], LmsAdapter] | None) -> None:
    global _override
    _override = factory


def require_on() -> None:
    if get_settings().lms_mode not in {"mock", "blackboard"}:
        raise WorkflowError("Blackboard integration is off until IT registers the Blackboard REST application "
                            "(13.C). Until then use the QTI export and the Grade Center CSV.", 403)


def make_adapter(log: CallLog, on_refresh: Callable[[Token], None] | None = None) -> LmsAdapter:
    if _override is not None:
        return _override(log, on_refresh)
    s = get_settings()
    if s.lms_mode == "mock":
        fb = fake_blackboard.shared()
        return BlackboardAdapter(fake_blackboard.BASE, "mock-key", "mock-secret", s.blackboard_redirect_uri,
                                 client=fb.client(), log=log, min_interval=0, sleep=lambda _s: None, on_refresh=on_refresh)
    if not (s.blackboard_url and s.blackboard_app_key and s.blackboard_app_secret):
        raise WorkflowError("Blackboard isn't configured (BLACKBOARD_URL, BLACKBOARD_APP_KEY, BLACKBOARD_APP_SECRET).", 500)
    return BlackboardAdapter(s.blackboard_url, s.blackboard_app_key, s.blackboard_app_secret, s.blackboard_redirect_uri,
                             log=log, on_refresh=on_refresh)


def _wrap(e: LmsError) -> WorkflowError:
    return WorkflowError(str(e), e.status if e.status in {401, 403, 404, 409} else 502)


# ---- connection (5.1) ---------------------------------------------------------
def save_token(db: Session, me: Faculty, tok: Token) -> None:
    row = db.get(LmsToken, me.id) or LmsToken(faculty_id=me.id)
    row.provider, row.lms_user_id = "blackboard", tok.user_id
    row.access_enc = identity.encrypt(tok.access_token) or ""
    row.refresh_enc, row.expires_at = identity.encrypt(tok.refresh_token), tok.expires_at
    db.add(row)
    db.flush()


def _token(db: Session, me: Faculty) -> Token:
    row = db.get(LmsToken, me.id)
    if row is None:
        raise WorkflowError("Connect your Blackboard account first.", 409)
    return Token(identity.decrypt(row.access_enc) or "", identity.decrypt(row.refresh_enc), row.expires_at, row.lms_user_id)


def session(db: Session, me: Faculty) -> tuple[LmsAdapter, Token, CallLog]:
    log = CallLog()
    return make_adapter(log, lambda t: save_token(db, me, t)), _token(db, me), log


def _state_signer() -> URLSafeTimedSerializer:
    secret = get_settings().session_secret or get_settings().identity_key
    if not secret:
        raise WorkflowError("SESSION_SECRET is not set.", 500)
    return URLSafeTimedSerializer(secret, salt="lms-oauth")


def connect(db: Session, me: Faculty) -> str | None:
    """Mock: connects at once (returns None). Blackboard: the URL to send the browser to."""
    if get_settings().lms_mode == "mock" and _override is None:
        fb = fake_blackboard.shared()
        uid = seed_mock(db, me, fb)
        log = CallLog()
        save_token(db, me, make_adapter(log).exchange_code(fb.authorize(uid)))
        record(db, me, "lms_connect", {"mode": "mock"})
        return None
    return make_adapter(CallLog()).authorize_url(_state_signer().dumps({"fid": me.id}))


def callback(db: Session, code: str, state: str) -> Faculty:
    try:
        fid = _state_signer().loads(state, max_age=600)["fid"]
    except (BadSignature, KeyError, TypeError) as e:
        raise WorkflowError("The Blackboard sign-in took too long or didn't come from this tool; try again.", 400) from e
    me = db.get(Faculty, fid)
    if me is None:
        raise WorkflowError("Unknown account.", 400)
    try:
        save_token(db, me, make_adapter(CallLog()).exchange_code(code))
    except LmsError as e:
        raise _wrap(e) from e
    record(db, me, "lms_connect", {"mode": "blackboard"})
    return me


def disconnect(db: Session, me: Faculty) -> None:
    row = db.get(LmsToken, me.id)
    if row is not None:
        db.delete(row)
    record(db, me, "lms_disconnect", {})


def seed_mock(db: Session, me: Faculty, fb: fake_blackboard.FakeBlackboard) -> str:
    """Mock mode: a sandbox course per locked course version, a decoy course, three
    made-up students, and canned attempts that appear on every new column."""
    found = next((u for u, d in fb.users.items() if (d["contact"] or {}).get("email") == me.email), None)
    if found:
        return found
    inst = fb.add_user(me.email.split("@")[0], me.name, email=me.email)
    studs = [fb.add_user(f"demo{i}", n, f"2027{i:04d}", f"demo{i}@students.example.edu")
             for i, n in enumerate(["Layla Haddad", "Yousef Nasser", "Sara Mansour"], 1)]
    terms: dict[str, str] = {}
    for cv in db.scalars(select(CourseVersion).where(CourseVersion.faculty_id == me.id, CourseVersion.status == "locked")):
        rec = ExtractedSyllabus.model_validate(cv.record)
        code, term = rec.course.code or "COURSE", cv.term or rec.offering.term or ""
        if term and term not in terms:
            terms[term] = fb.add_term(term)
        fb.add_course(f"{_norm(code)}-{_term_tag(term)}-01", f"{code} {rec.course.title or ''}".strip(),
                      terms.get(term), inst, studs)
    fb.add_course("MATH101-F26-01", "MATH 101 Calculus I", fb.add_term("Fall 2026"), inst, studs)
    fb.auto_attempts = [(s, f"Q1: A\nQ2: B\nQ3: The mean uses every value, so extremes pull it. ({i})")
                        for i, s in enumerate(studs, 1)]
    return inst


# ---- courses and links (5.2) -----------------------------------------------------
def _norm(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def _term_tag(term: str) -> str:
    m = re.search(r"(spring|summer|fall|autumn|winter)\D*(\d{4})", term, re.I)
    return f"{m.group(1)[0].upper()}{m.group(2)[2:]}" if m else "XX"


def mismatch(code: str | None, term: str | None, c: LmsCourse) -> list[str]:
    """Plan 5.2: the Blackboard course must carry the same course code and term."""
    out = []
    if not code or _norm(code) not in _norm(c.course_id + " " + c.name):
        out.append(f"Course code {code} isn't in the Blackboard course '{c.course_id}' ({c.name}).")
    m = re.search(r"(spring|summer|fall|autumn|winter)\D*(\d{4})", term or "", re.I)
    if not m:
        out.append("This course version has no readable term.")
    else:
        season, year = m.group(1).lower(), m.group(2)
        hay = (c.term or "").lower()
        tag = _term_tag(term or "")
        ok = (season in hay and year in hay) or bool(re.search(rf"(?<![A-Z0-9]){tag}(?![0-9])|{season[:2].upper()}{year[2:]}",
                                                              c.course_id.upper()))
        if not ok:
            out.append(f"The Blackboard course's term ({c.term or 'none'}) isn't {term}.")
    return out


def courses(db: Session, me: Faculty) -> list[LmsCourse]:
    ad, tok, _log = session(db, me)
    try:
        return ad.courses(tok)
    except LmsError as e:
        raise _wrap(e) from e


def link(db: Session, me: Faculty, cv: CourseVersion, section_id: int | None, lms_course_id: str) -> LmsLink:
    if cv.faculty_id != me.id or cv.status != "locked":
        raise WorkflowError("Link a locked course version of yours.", 409)
    if section_id is not None:
        grading.own_section(db, me, section_id)
    c = next((x for x in courses(db, me) if x.id == lms_course_id), None)
    if c is None:
        raise WorkflowError("That Blackboard course isn't one you teach.", 404)
    rec = ExtractedSyllabus.model_validate(cv.record)
    probs = mismatch(rec.course.code, cv.term or rec.offering.term, c)
    if probs:
        raise WorkflowError("Wrong course? " + " ".join(probs), 409, {"problems": probs})
    existing = db.scalar(select(LmsLink).where(LmsLink.course_version_id == cv.id, LmsLink.section_id == section_id,
                                               LmsLink.lms_course_id == c.id))
    if existing:
        return existing
    ln = LmsLink(course_version_id=cv.id, section_id=section_id, lms_course_id=c.id, lms_course_code=c.course_id,
                 lms_course_name=c.name, lms_term=c.term, linked_by_id=me.id)
    db.add(ln)
    db.flush()
    record(db, me, "lms_link", {"course_version_id": cv.id, "lms_course": c.course_id})
    return ln


def own_link(db: Session, me: Faculty, link_id: int) -> LmsLink:
    ln = db.get(LmsLink, link_id)
    cv = db.get(CourseVersion, ln.course_version_id) if ln else None
    if ln is None or cv is None or cv.faculty_id != me.id:
        raise WorkflowError("Link not found.", 404)
    return ln


def _form(db: Session, me: Faculty, ln: LmsLink, form_id: int) -> AssessmentForm:
    form = grading.own_form(db, me, form_id)
    if form.course_version_id != ln.course_version_id:
        raise WorkflowError("That form belongs to another course version.", 409)
    return form


def _sync(db: Session, me: Faculty, ln: LmsLink, form: AssessmentForm | None, kind: str, status: str, summary: dict,
          log: CallLog) -> LmsSync:
    s = LmsSync(link_id=ln.id, form_id=form.id if form else None, kind=kind, status=status, summary=summary,
                request_log=log.entries, by_id=me.id)
    db.add(s)
    db.flush()
    return s


# ---- push (5.3) ---------------------------------------------------------------------------
def push(db: Session, me: Faculty, ln: LmsLink, form_id: int) -> LmsSync:
    form = _form(db, me, ln, form_id)
    if form.status != "approved":
        raise WorkflowError("Only approved forms go to Blackboard. Approve it in the Assessment Builder first.", 409)
    ad, tok, log = session(db, me)
    col = db.scalar(select(LmsColumnLink).where(LmsColumnLink.link_id == ln.id, LmsColumnLink.form_id == form.id))
    try:
        if col is None:
            pts = sum(fi.points for fi in form.items)
            c = ad.create_column(tok, ln.lms_course_id, f"{form.assessment_name} {form.version_label}", pts,
                                 "Created by EduForge from an approved form.")
            col = LmsColumnLink(link_id=ln.id, form_id=form.id, column_id=c.id, column_name=c.name, last_written={})
            db.add(col)
    except LmsError as e:
        _sync(db, me, ln, form, "pool_push", "failed", {"error": str(e)}, log)
        db.commit()
        raise _wrap(e) from e
    record(db, me, "lms_push", {"form_id": form.id, "lms_course": ln.lms_course_code})
    return _sync(db, me, ln, form, "pool_push", "ok",
                 {"column_id": col.column_id, "column": col.column_name, "items": len(form.items),
                  "qti": "Import the form's QTI export into this course's question pools or as a test; the REST API "
                         "has no pool import."}, log)


def attach_column(db: Session, me: Faculty, ln: LmsLink, form_id: int, column_id: str) -> LmsColumnLink:
    form = _form(db, me, ln, form_id)
    ad, tok, _log = session(db, me)
    try:
        c = next((x for x in ad.columns(tok, ln.lms_course_id) if x.id == column_id), None)
    except LmsError as e:
        raise _wrap(e) from e
    if c is None:
        raise WorkflowError("No such Grade Center column in that course.", 404)
    col = db.scalar(select(LmsColumnLink).where(LmsColumnLink.link_id == ln.id, LmsColumnLink.form_id == form.id))
    if col is None:
        col = LmsColumnLink(link_id=ln.id, form_id=form.id, column_id=c.id, column_name=c.name, last_written={})
        db.add(col)
    else:
        col.column_id, col.column_name, col.last_written = c.id, c.name, {}
    db.flush()
    return col


def _column(db: Session, ln: LmsLink, form: AssessmentForm) -> LmsColumnLink:
    col = db.scalar(select(LmsColumnLink).where(LmsColumnLink.link_id == ln.id, LmsColumnLink.form_id == form.id))
    if col is None:
        raise WorkflowError("Push the form (or pick its Grade Center column) first.", 409)
    return col


def _section(db: Session, me: Faculty, ln: LmsLink, section_id: int | None, form: AssessmentForm) -> Section:
    sid = section_id or ln.section_id
    if sid is None:
        raise WorkflowError("Pick the section these students belong to.", 422)
    return grading.own_section(db, me, sid, form)


# ---- pull submissions (5.4) ------------------------------------------------------------------
def pull(db: Session, me: Faculty, ln: LmsLink, form_id: int, section_id: int | None) -> LmsSync:
    grading.require_enabled()
    form = _form(db, me, ln, form_id)
    if form.status != "approved":
        raise WorkflowError("Approve the form first.", 409)
    section = _section(db, me, ln, section_id, form)
    col = _column(db, ln, form)
    ad, tok, log = session(db, me)
    try:
        attempts = ad.attempts(tok, ln.lms_course_id, col.column_id)
        latest = {a.user_id: a for a in attempts}  # last attempt per student
        people = {uid: ad.user(tok, uid) for uid in latest}
    except LmsError as e:
        _sync(db, me, ln, form, "submission_pull", "failed", {"error": str(e)}, log)
        db.commit()
        raise _wrap(e) from e
    for u in people.values():
        grading.upsert_student(db, section, Person(u.student_id or u.user_name, u.name, u.email))
    roster = grading._roster_people(db, section)
    stored = redactions = 0
    for uid, a in latest.items():
        u = people[uid]
        st = grading._find(db, section, u.student_id or u.user_name)
        assert st is not None
        sub = grading._store(db, form, st, intake.split_answers(a.text, len(form.items)), roster, "blackboard")
        stored += 1
        redactions += sub.redactions
    summary = {"blackboard_attempts": len(attempts), "blackboard_students": len(latest), "stored": stored,
               "redactions": redactions, "section": section.label}
    record(db, me, "lms_pull", {"form_id": form.id, "count": stored})
    return _sync(db, me, ln, form, "submission_pull", "ok" if stored == len(latest) else "partial", summary, log)


# ---- grade passback (5.5) -----------------------------------------------------------------------
def passback(db: Session, me: Faculty, ln: LmsLink, form_id: int, section_id: int | None, dry_run: bool,
             overwrite: list[str]) -> LmsSync:
    grading.require_enabled()
    form = _form(db, me, ln, form_id)
    section = _section(db, me, ln, section_id, form)
    blockers = grading.blockers(db, form, section)
    if blockers:
        raise WorkflowError("Nothing is written to Blackboard until every mark is confirmed: " + " ".join(blockers),
                            409, {"blockers": blockers})
    col = _column(db, ln, form)
    ad, tok, log = session(db, me)
    try:
        current = {g.user_id: g.score for g in ad.grades(tok, ln.lms_course_id, col.column_id)}
        lms_users = ad.roster(tok, ln.lms_course_id)
    except LmsError as e:
        raise _wrap(e) from e
    index: dict[str, str] = {}
    for u in lms_users:
        for k in (u.student_id, u.user_name, u.email, (u.email or "").split("@")[0] or None):
            if k:
                index[identity.norm_id(k)] = u.id
    people = grading.reveal(db, me, section, why="grade passback")
    rows: list[dict[str, Any]] = []
    for sub in grading.section_submissions(db, form, section):
        p = people[sub.student_id]
        total = round(sum(sc.confirmed_points or 0 for sc in sub.scores), 2)
        fb = db.scalar(select(FeedbackDraft).where(FeedbackDraft.submission_id == sub.id, FeedbackDraft.item_id.is_(None),
                                                   FeedbackDraft.status == "approved"))
        uid = next((index[k] for k in (identity.norm_id(p.external_id), identity.norm_id(p.email or ""),
                                        identity.norm_id((p.email or "").split("@")[0])) if k and k in index), None)
        row: dict[str, Any] = {"pseudonym": sub.student.pseudonym, "student_id": p.external_id, "new": total,
               "current": current.get(uid) if uid else None, "feedback": bool(fb)}
        last = col.last_written.get(uid) if uid else None
        if uid is None:
            row["action"] = "not in the Blackboard course"
        elif row["current"] is not None and abs(row["current"] - total) < 1e-6:
            row["action"] = "same"
        elif row["current"] is not None and (last is None or abs(row["current"] - last) > 1e-6):
            row["action"] = "write (overwrite)" if sub.student.pseudonym in overwrite else "changed in Blackboard: skipped"
        else:
            row["action"] = "write"
        row["_uid"], row["_fb"] = uid, fb.text if fb else None
        rows.append(row)
    errors = 0
    if not dry_run:
        for r in rows:
            if not r["action"].startswith("write"):
                continue
            try:
                ad.put_grade(tok, ln.lms_course_id, col.column_id, r["_uid"], r["new"], r["_fb"])
                col.last_written = {**col.last_written, r["_uid"]: r["new"]}
                r["result"] = "written"
            except LmsError as e:
                r["result"] = f"failed: {e}"
                errors += 1
        written = sum(1 for r in rows if r.get("result") == "written")
        if written:
            db.add(GradeRelease(form_id=form.id, section_id=section.id, channel="blackboard", n_students=written,
                                marks={r["pseudonym"]: r["new"] for r in rows if r.get("result") == "written"},
                                by_id=me.id))
        record(db, me, "lms_grade_push", {"form_id": form.id, "written": written, "failed": errors})
    for r in rows:
        r.pop("_uid")
        r.pop("_fb")
    status = "partial" if errors else "ok"
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("result") or r["action"]] = counts.get(r.get("result") or r["action"], 0) + 1
    return _sync(db, me, ln, form, "grade_dry_run" if dry_run else "grade_push", status,
                 {"rows": rows, "counts": counts, "column": col.column_name}, log)
