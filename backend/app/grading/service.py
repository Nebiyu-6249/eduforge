"""Grading & Feedback Assist workflow (plan 4.1–4.12).

Invariants (enforced here, tested in tests/test_grading.py):

* grading routes refuse unless GRADING_ENABLED (13.D approval);
* only the form's faculty member sees its sections, students and marks;
* identities are re-identified only on an explicit, audit-logged request or at release;
* a mark counts only once the faculty member confirms it; release is refused
  while any cell is unconfirmed or the grading scale isn't confirmed;
* feedback goes out only if approved;
* after release, a confirmed mark changes only through an appeal, with history.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.config import get_settings
from app.extraction.schema import ExtractedSyllabus, GradeBand
from app.llm.embeddings import LocalHashEmbedder, cosine
from app.llm.gateway import LLMGateway
from app.models import (
    Appeal,
    AssessmentForm,
    CalibrationScore,
    CalibrationSet,
    CourseVersion,
    Faculty,
    FeedbackDraft,
    FormItem,
    GradeRelease,
    GradingScale,
    Item,
    ResponseScore,
    Section,
    Student,
    StudentIdentity,
    Submission,
)
from app.services.course_versions import WorkflowError

from . import identity, intake, scale, scoring
from .identity import Person


def now() -> datetime:
    return datetime.now(UTC)


def require_enabled() -> None:
    if not get_settings().grading_enabled:
        raise WorkflowError("Grading Assist is off until the university's data-protection approval (13.D) is in "
                            "place. An administrator turns it on with GRADING_ENABLED.", 403)


# ---- ownership --------------------------------------------------------------
def own_form(db: Session, me: Faculty, form_id: int) -> AssessmentForm:
    f = db.get(AssessmentForm, form_id)
    if f is None or f.created_by_id != me.id:
        raise WorkflowError("Form not found.", 404)
    return f


def own_section(db: Session, me: Faculty, section_id: int, form: AssessmentForm | None = None) -> Section:
    s = db.get(Section, section_id)
    if s is None or s.faculty_id != me.id or (form is not None and s.course_version_id != form.course_version_id):
        raise WorkflowError("Section not found.", 404)
    return s


def own_cv(db: Session, me: Faculty, cv_id: int) -> CourseVersion:
    cv = db.get(CourseVersion, cv_id)
    if cv is None or cv.faculty_id != me.id:
        raise WorkflowError("Course version not found.", 404)
    if cv.status != "locked":
        raise WorkflowError("Marking works on the syllabus you have confirmed for the term. This one has been replaced by a newer version: open that one instead.", 409)
    return cv


def _items(form: AssessmentForm) -> list[FormItem]:
    return sorted(form.items, key=lambda f: f.position)


# ---- sections and rosters (4.1) ---------------------------------------------
def create_section(db: Session, me: Faculty, cv: CourseVersion, label: str) -> Section:
    label = label.strip()[:40]
    if not label:
        raise WorkflowError("Give the section a label, e.g. 'S1'.", 422)
    if db.scalar(select(Section).where(Section.course_version_id == cv.id, Section.label == label)):
        raise WorkflowError(f"Section '{label}' already exists.", 409)
    s = Section(course_version_id=cv.id, label=label, faculty_id=me.id)
    db.add(s)
    db.flush()
    return s


def _find(db: Session, section: Section, external_id: str) -> Student | None:
    m = identity.mac("id", identity.norm_id(external_id))
    return db.scalar(select(Student).join(StudentIdentity, StudentIdentity.student_id == Student.id)
                     .where(Student.section_id == section.id, StudentIdentity.lookup_mac == m))


def upsert_student(db: Session, section: Section, p: Person) -> tuple[Student, bool]:
    st = _find(db, section, p.external_id)
    created = st is None
    if st is None:
        while True:
            pseudo = identity.new_pseudonym()
            if not db.scalar(select(Student).where(Student.pseudonym == pseudo)):
                break
        st = Student(pseudonym=pseudo, section_id=section.id)
        db.add(st)
        db.flush()
        db.add(StudentIdentity(student_id=st.id, lookup_mac=identity.mac("id", identity.norm_id(p.external_id)),
                               external_id_enc=identity.encrypt(p.external_id.strip()) or "",
                               name_enc=identity.encrypt(p.name), email_enc=identity.encrypt(p.email),
                               token_macs=identity.token_macs(p)))
        # Flush the identity too: _find looks students up through it, so on a
        # session without autoflush the next upload would not see the student
        # just added and would create them a second time.
        db.flush()
    else:
        ident = db.get(StudentIdentity, st.id)
        assert ident is not None
        old = _person(ident)
        merged = Person(p.external_id.strip(), p.name or old.name, p.email or old.email)
        ident.name_enc, ident.email_enc = identity.encrypt(merged.name), identity.encrypt(merged.email)
        ident.token_macs = identity.token_macs(merged)
    return st, created


def _person(ident: StudentIdentity) -> Person:
    return Person(identity.decrypt(ident.external_id_enc) or "", identity.decrypt(ident.name_enc),
                  identity.decrypt(ident.email_enc))


def add_roster(db: Session, me: Faculty, section: Section, people: list[Person]) -> dict:
    added = sum(1 for p in people if upsert_student(db, section, p)[1])
    record(db, me, "roster_upload", {"section_id": section.id, "students": len(people)})
    return {"students": len(people), "added": added, "updated": len(people) - added}


def students(db: Session, section: Section) -> list[Student]:
    return list(db.scalars(select(Student).where(Student.section_id == section.id).order_by(Student.pseudonym)))


def reveal(db: Session, me: Faculty, section: Section, why: str) -> dict[int, Person]:
    """Re-identify a section (the course's faculty member only; audit-logged)."""
    rows = db.execute(select(Student, StudentIdentity).join(StudentIdentity, StudentIdentity.student_id == Student.id)
                      .where(Student.section_id == section.id)).all()
    record(db, me, "reidentify", {"section_id": section.id, "students": len(rows), "why": why})
    return {st.id: _person(ident) for st, ident in rows}


def _roster_people(db: Session, section: Section) -> list[Person]:
    """Identities in memory, only to anonymise incoming text; never returned or logged."""
    rows = db.scalars(select(StudentIdentity).join(Student, Student.id == StudentIdentity.student_id)
                      .where(Student.section_id == section.id)).all()
    return [_person(i) for i in rows]


def section_macs(db: Session, section: Section) -> set[str]:
    rows = db.scalars(select(StudentIdentity.token_macs).join(Student, Student.id == StudentIdentity.student_id)
                      .where(Student.section_id == section.id)).all()
    return {m for r in rows for m in (r or [])}


# ---- intake (4.2, 4.3) ------------------------------------------------------
def _store(db: Session, form: AssessmentForm, st: Student, answers: dict[int, str], roster: list[Person],
           source: str) -> Submission:
    fis = _items(form)
    sub = db.scalar(select(Submission).where(Submission.form_id == form.id, Submission.student_id == st.id))
    if sub is not None and any(sc.confirmed_points is not None for sc in sub.scores):
        raise WorkflowError(f"{st.pseudonym} already has confirmed marks for this form; record an appeal to change "
                            "them instead of re-uploading.", 409)
    clean, redactions = [], 0
    for fi in fis:
        text, n = identity.scrub(answers.get(fi.position, ""), roster)
        redactions += n
        clean.append({"item_id": fi.item_id, "position": fi.position, "text": text})
    if sub is None:
        sub = Submission(form_id=form.id, student_id=st.id)
        db.add(sub)
    sub.answers, sub.source, sub.redactions, sub.status, sub.received_at = clean, source, redactions, "received", now()
    sub.scores.clear()
    db.flush()
    for fb in db.scalars(select(FeedbackDraft).where(FeedbackDraft.submission_id == sub.id)):
        db.delete(fb)
    return sub


def _check_form(form: AssessmentForm) -> None:
    if form.status != "approved":
        raise WorkflowError("Approve the form before taking submissions for it.", 409)


def intake_csv(db: Session, me: Faculty, form: AssessmentForm, section: Section, data: bytes,
               calibration: CalibrationSet | None = None) -> dict:
    _check_form(form)
    rows = intake.parse_answers_csv(data, len(form.items), with_marks=calibration is not None)
    for r in rows:
        upsert_student(db, section, r.person)
    roster = _roster_people(db, section)
    by_pos = {fi.position: fi for fi in _items(form)}
    n_red = 0
    for r in rows:
        st = _find(db, section, r.person.external_id)
        assert st is not None
        sub = _store(db, form, st, r.answers, roster, "csv")
        n_red += sub.redactions
        if calibration is not None:
            for pos, pts in r.marks.items():
                fi = by_pos.get(pos)
                if fi is None or not 0 <= pts <= fi.points:
                    raise WorkflowError(f"Mark {pts:g} for question {pos} is outside 0–{fi.points if fi else '?'}.", 422)
                db.add(CalibrationScore(calibration_id=calibration.id, submission_id=sub.id, item_id=fi.item_id,
                                        faculty_points=pts))
    record(db, me, "submissions_upload", {"form_id": form.id, "section_id": section.id, "count": len(rows),
                                          "source": "csv", "calibration": calibration is not None})
    return {"submissions": len(rows), "redactions": n_red}


def intake_files(db: Session, me: Faculty, form: AssessmentForm, section: Section, files: list[tuple[str, bytes]]) -> dict:
    _check_form(form)
    roster = _roster_people(db, section)
    done, unmatched, n_red, unsplit = 0, [], 0, []
    for name, data in files:
        st = next((s for t in intake.id_tokens(name) if (s := _find(db, section, t))), None)
        if st is None:
            unmatched.append(name)
            continue
        answers = intake.split_answers(intake.file_text(name, data), len(form.items))
        if not answers:
            unsplit.append(st.pseudonym)
        sub = _store(db, form, st, answers, roster, "file")
        n_red += sub.redactions
        done += 1
    record(db, me, "submissions_upload", {"form_id": form.id, "section_id": section.id, "count": done, "source": "file"})
    return {"submissions": done, "redactions": n_red,
            "unmatched_files": unmatched,  # file names only: no student ID on the roster matched
            "not_split": unsplit}


# ---- scoring (job) -----------------------------------------------------------
def _put_feedback(db: Session, sub: Submission, item_id: int | None, text: str | None, source: str) -> None:
    for fb in db.scalars(select(FeedbackDraft).where(FeedbackDraft.submission_id == sub.id,
                                                     FeedbackDraft.item_id == item_id)):
        if fb.status == "suggested":
            db.delete(fb)
        elif item_id is not None:
            return  # approved/rejected per-item feedback stays as decided
    if text:
        db.add(FeedbackDraft(submission_id=sub.id, item_id=item_id, text=text, source=source))


def score(db: Session, form: AssessmentForm, section: Section, llm: LLMGateway | None,
          progress: Callable[[int, str], None] | None = None, rescore: bool = False) -> dict:
    fis = _items(form)
    subs = db.scalars(select(Submission).join(Student, Student.id == Submission.student_id)
                      .where(Submission.form_id == form.id, Student.section_id == section.id)).all()
    macs = section_macs(db, section)
    todo = [s for s in subs if rescore or s.status != "scored"]
    counts: dict[str, int] = defaultdict(int)
    for n, sub in enumerate(todo):
        if progress:
            progress(5 + int(90 * n / max(1, len(todo))), f"Scoring {sub.student.pseudonym} ({n + 1} of {len(todo)})")
        answers = {a["item_id"]: a["text"] for a in sub.answers}
        cells = {sc.item_id: sc for sc in sub.scores}
        for fi in fis:
            sc = cells.get(fi.item_id)
            if sc is not None and sc.confirmed_points is not None:
                continue  # never overwrite a confirmed mark
            sg = scoring.suggest(fi.item, fi, answers.get(fi.item_id, ""), llm, macs)
            if sc is None:
                sc = ResponseScore(submission_id=sub.id, item_id=fi.item_id, method=sg.method, max_points=fi.points,
                                   level_step=sg.level_step)
                sub.scores.append(sc)
            sc.method, sc.max_points, sc.level_step = sg.method, fi.points, sg.level_step
            sc.suggested_points, sc.confidence, sc.criteria = sg.points, sg.confidence, sg.criteria
            sc.evidence, sc.needs_faculty, sc.note = sg.evidence, sg.needs_faculty, sg.note
            _put_feedback(db, sub, fi.item_id, sg.feedback, sg.feedback_source or "key")
            counts[sg.method] += 1
            counts["needs_faculty"] += int(sg.needs_faculty)
            counts["sent_to_model"] += int(sg.method == "llm")
            counts["blocked_by_identity_guard"] += int((sg.note or "").startswith("Not sent to the model"))
        sub.status = "scored"
        db.flush()
    return {"submissions": len(todo), **counts}


# ---- grid, confirmation (4.10) -------------------------------------------------
def released(db: Session, form: AssessmentForm, section: Section) -> GradeRelease | None:
    return db.scalar(select(GradeRelease).where(GradeRelease.form_id == form.id, GradeRelease.section_id == section.id)
                     .order_by(GradeRelease.at.desc()))


def section_submissions(db: Session, form: AssessmentForm, section: Section) -> list[Submission]:
    return list(db.scalars(select(Submission).join(Student, Student.id == Submission.student_id)
                           .where(Submission.form_id == form.id, Student.section_id == section.id)
                           .order_by(Student.pseudonym)))


def _history(sc: ResponseScore, me: Faculty, kind: str, reason: str | None) -> None:
    sc.history = [*(sc.history or []), {"points": sc.confirmed_points, "by": me.name, "at": now().isoformat(),
                                        "kind": kind, "reason": reason}]


def needs_reason(sc: ResponseScore, points: float) -> bool:
    """4.10: changing a high-confidence suggestion by more than one level needs a reason."""
    return (sc.suggested_points is not None and sc.confidence is not None and sc.confidence >= scoring.HIGH_CONFIDENCE
            and abs(points - sc.suggested_points) > sc.level_step + 1e-6)


def confirm(db: Session, me: Faculty, sc: ResponseScore, points: float, reason: str | None,
            via_appeal: bool = False) -> ResponseScore:
    if not 0 <= points <= sc.max_points + 1e-9:
        raise WorkflowError(f"Marks must be between 0 and {sc.max_points:g}.", 422)
    sub = db.get(Submission, sc.submission_id)
    assert sub is not None
    form = db.get(AssessmentForm, sub.form_id)
    section = db.get(Section, sub.student.section_id)
    assert form is not None and section is not None
    if not via_appeal and sc.confirmed_points is not None and released(db, form, section):
        raise WorkflowError("Marks for this section were released. Record an appeal to change a released mark.", 409)
    reason = (reason or "").strip() or None
    if needs_reason(sc, points) and not reason:
        raise WorkflowError("This changes a high-confidence suggestion by more than one level: give a short reason.", 422)
    sc.confirmed_points, sc.confirmed_by_id, sc.confirmed_at = round(points, 2), me.id, now()
    sc.override_reason = reason if sc.suggested_points is None or abs(points - sc.suggested_points) > 1e-6 else None
    _history(sc, me, "appeal" if via_appeal else "confirm", reason)
    db.flush()
    refresh_summary(db, form, sub)
    return sc


def bulk_confirm_key(db: Session, me: Faculty, form: AssessmentForm, section: Section, item_id: int | None) -> int:
    """Bulk confirm is only for key-scored cells that aren't flagged (4.10)."""
    n = 0
    for sub in section_submissions(db, form, section):
        for sc in sub.scores:
            if (sc.method == "key" and not sc.needs_faculty and sc.confirmed_points is None
                    and sc.suggested_points is not None and (item_id is None or sc.item_id == item_id)):
                sc.confirmed_points, sc.confirmed_by_id, sc.confirmed_at = sc.suggested_points, me.id, now()
                _history(sc, me, "bulk confirm", None)
                n += 1
        db.flush()
        refresh_summary(db, form, sub)
    return n


def refresh_summary(db: Session, form: AssessmentForm, sub: Submission) -> None:
    """Overall feedback, rebuilt from the confirmed marks once every cell is confirmed."""
    if len(sub.scores) < len(form.items) or any(sc.confirmed_points is None for sc in sub.scores):
        return
    total = sum(sc.confirmed_points or 0 for sc in sub.scores)
    mx = sum(sc.max_points for sc in sub.scores)
    pos = {fi.item_id: fi.position for fi in form.items}
    lost: dict[int, list[int]] = defaultdict(list)
    for sc in sub.scores:
        if (sc.confirmed_points or 0) < sc.max_points - 1e-6:
            it = db.get(Item, sc.item_id)
            for c in (it.clo_ids if it else []) or [0]:
                lost[c].append(pos[sc.item_id])
    text = f"You scored {total:g} out of {mx:g} ({100 * total / mx:.0f}%)." if mx else ""
    if lost:
        text += " To review: " + "; ".join(
            (f"outcome {c}" if c else "other") + f" (question{'s' if len(q) > 1 else ''} {', '.join(map(str, sorted(q)))})"
            for c, q in sorted(lost.items())) + "."
    else:
        text += " Full marks."
    cur = db.scalar(select(FeedbackDraft).where(FeedbackDraft.submission_id == sub.id, FeedbackDraft.item_id.is_(None)))
    if cur is None:
        db.add(FeedbackDraft(submission_id=sub.id, item_id=None, text=text, source="summary"))
    elif cur.text != text and cur.source == "summary":
        cur.text, cur.status, cur.approved_by_id, cur.approved_at = text, "suggested", None, None
    db.flush()


def feedback_action(db: Session, me: Faculty, fb: FeedbackDraft, action: str, text: str | None) -> FeedbackDraft:
    if action == "approve":
        fb.status = "approved"
    elif action == "reject":
        fb.status = "rejected"
    elif action == "edit":
        if not (text or "").strip():
            raise WorkflowError("Feedback text can't be empty; reject it instead.", 422)
        fb.text, fb.status, fb.source = text.strip(), "approved", "faculty"  # type: ignore[union-attr]
    else:
        raise WorkflowError(f"Unknown action '{action}'.", 422)
    fb.approved_by_id, fb.approved_at = (me.id, now()) if fb.status == "approved" else (None, None)
    return fb


def add_feedback(db: Session, me: Faculty, sub: Submission, item_id: int | None, text: str) -> FeedbackDraft:
    if not text.strip():
        raise WorkflowError("Feedback text can't be empty.", 422)
    fb = FeedbackDraft(submission_id=sub.id, item_id=item_id, text=text.strip(), source="faculty", status="approved",
                       approved_by_id=me.id, approved_at=now())
    db.add(fb)
    return fb


# ---- consistency (4.8) ---------------------------------------------------------
def outliers(db: Session, form: AssessmentForm, section: Section) -> list[dict]:
    """Same (or near-identical) answer, different mark: listed per item."""
    out: list[dict] = []
    emb = LocalHashEmbedder()
    subs = section_submissions(db, form, section)
    for fi in _items(form):
        cells = []
        for sub in subs:
            sc = next((s for s in sub.scores if s.item_id == fi.item_id), None)
            ans = next((a["text"] for a in sub.answers if a["item_id"] == fi.item_id), "")
            pts = sc.confirmed_points if sc and sc.confirmed_points is not None else (sc.suggested_points if sc else None)
            if sc is None or pts is None or not ans.strip():
                continue
            cells.append((sub.student.pseudonym, scoring._norm(ans), pts, sc.level_step))
        if len(cells) < 2:
            continue
        vecs = emb.embed([c[1] for c in cells])
        seen: set[tuple[str, str]] = set()
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                a, b = cells[i], cells[j]
                same = a[1] == b[1]
                if not same and cosine(vecs[i], vecs[j]) < 0.95:
                    continue
                if abs(a[2] - b[2]) > (1e-6 if same else max(a[3], 1e-6)):
                    key = (a[0], b[0])
                    if key not in seen:
                        seen.add(key)
                        out.append({"position": fi.position, "item_id": fi.item_id, "students": [a[0], b[0]],
                                    "points": [a[2], b[2]], "identical": same})
    return out


# ---- release (4.11) -------------------------------------------------------------
def confirmed_scale(db: Session, cv_id: int) -> list[GradingScale]:
    return list(db.scalars(select(GradingScale).where(GradingScale.course_version_id == cv_id)
                           .order_by(GradingScale.min_pct.desc())))


def blockers(db: Session, form: AssessmentForm, section: Section) -> list[str]:
    out = []
    if section.calibration:
        out.append("This is a calibration set: it is never released.")
    if form.status != "approved":
        out.append("The form isn't approved.")
    if not confirmed_scale(db, form.course_version_id):
        out.append("Confirm the grading scale for this course first.")
    subs = section_submissions(db, form, section)
    if not subs:
        out.append("Nobody has answers in yet.")
    unscored = sum(1 for s in subs if len(s.scores) < len(form.items))
    if unscored:
        out.append(f"{unscored} student{'s have' if unscored != 1 else ' has'} answers that are not marked yet.")
    unconfirmed = sum(1 for s in subs for sc in s.scores if sc.confirmed_points is None)
    if unconfirmed:
        out.append(f"{unconfirmed} mark{'s are' if unconfirmed != 1 else ' is'} still waiting for you to confirm.")
    return out


def pending_feedback(db: Session, subs: list[Submission]) -> int:
    ids = [s.id for s in subs]
    return len(db.scalars(select(FeedbackDraft.id).where(FeedbackDraft.submission_id.in_(ids),
                                                         FeedbackDraft.status == "suggested")).all()) if ids else 0


# ---- appeals (4.12) ---------------------------------------------------------------
def open_appeal(db: Session, me: Faculty, sub: Submission, item_id: int | None, reason: str) -> Appeal:
    if not reason.strip():
        raise WorkflowError("Record the student's reason for the appeal.", 422)
    if item_id is not None and item_id not in {a["item_id"] for a in sub.answers}:
        raise WorkflowError("That question isn't on this form.", 422)
    ap = Appeal(submission_id=sub.id, item_id=item_id, reason=reason.strip())
    db.add(ap)
    db.flush()
    return ap


def decide_appeal(db: Session, me: Faculty, ap: Appeal, outcome: str, new_points: dict[int, float]) -> Appeal:
    if ap.status != "open":
        raise WorkflowError("This appeal was already decided.", 409)
    if not outcome.strip():
        raise WorkflowError("Record the outcome.", 422)
    sub = db.get(Submission, ap.submission_id)
    assert sub is not None
    changed = False
    for item_id, pts in new_points.items():
        sc = next((s for s in sub.scores if s.item_id == int(item_id)), None)
        if sc is None:
            raise WorkflowError("That question has no mark to change.", 422)
        if sc.confirmed_points is None or abs(sc.confirmed_points - pts) > 1e-6:
            confirm(db, me, sc, pts, f"Appeal #{ap.id}: {outcome.strip()}", via_appeal=True)
            changed = True
    ap.status, ap.outcome, ap.decided_by_id, ap.decided_at = ("changed" if changed else "upheld"), outcome.strip(), me.id, now()
    return ap


# ---- grading scale (4.4, V13) -----------------------------------------------------
def scale_view(db: Session, cv: CourseVersion) -> dict:
    rec = ExtractedSyllabus.model_validate(cv.record)
    confirmed = confirmed_scale(db, cv.id)
    current = ([GradeBand(letter=g.letter, min_pct=g.min_pct, max_pct=g.max_pct, points=g.points) for g in confirmed]
               or rec.grading_scale)
    return {"extracted": [b.model_dump() for b in rec.grading_scale],
            "confirmed": [{"letter": g.letter, "min_pct": g.min_pct, "max_pct": g.max_pct, "points": g.points}
                          for g in confirmed],
            "confirmed_at": confirmed[0].confirmed_at if confirmed else None,
            "note": confirmed[0].note if confirmed else None,
            "problems": scale.problems(current),
            "others": _other_scales(db, cv, current)}


def _other_scales(db: Session, cv: CourseVersion, bands: list[GradeBand]) -> list[dict]:
    """V13's comparison: other locked syllabi of the same term whose scale differs."""
    if not cv.term:
        return []
    out = []
    mine = scale.signature(bands)
    for other in db.scalars(select(CourseVersion).where(CourseVersion.term == cv.term, CourseVersion.status == "locked",
                                                         CourseVersion.id != cv.id)):
        rec = ExtractedSyllabus.model_validate(other.record)
        theirs = rec.grading_scale
        if theirs and scale.signature(theirs) != mine:
            out.append({"course": rec.course.code or f"version {other.id}", "scale": scale.describe(theirs)})
    return out


def confirm_scale(db: Session, me: Faculty, cv: CourseVersion, bands: list[GradeBand], acknowledge: bool,
                  note: str | None) -> dict:
    probs = scale.problems(bands)
    if probs:
        raise WorkflowError("Fix the scale first: " + " ".join(probs), 422, {"problems": probs})
    others = _other_scales(db, cv, bands)
    if others and not acknowledge:
        raise WorkflowError("This scale differs from other syllabi this term; confirm that it is the one that applies.",
                            409, {"others": others})
    for g in confirmed_scale(db, cv.id):
        db.delete(g)
    db.flush()
    text = (note or "").strip() or (f"Differs from: {', '.join(o['course'] for o in others)}" if others else None)
    for b in bands:
        db.add(GradingScale(course_version_id=cv.id, letter=b.letter.strip().upper(), min_pct=b.min_pct,
                            max_pct=b.max_pct, points=b.points, confirmed_by_id=me.id, note=text))
    record(db, me, "grading_scale_confirmed", {"course_version_id": cv.id, "scale": scale.describe(bands)})
    db.flush()
    return scale_view(db, cv)


# ---- calibration (4.13) -----------------------------------------------------------
def create_calibration(db: Session, me: Faculty, form: AssessmentForm, data: bytes, description: str) -> CalibrationSet:
    n = len(db.scalars(select(CalibrationSet.id).where(CalibrationSet.form_id == form.id)).all()) + 1
    label = f"Calibration {form.version_label}{n}"
    sec = Section(course_version_id=form.course_version_id, label=label, faculty_id=me.id, calibration=True)
    db.add(sec)
    db.flush()
    cal = CalibrationSet(form_id=form.id, section_id=sec.id, description=description.strip(), created_by_id=me.id)
    db.add(cal)
    db.flush()
    intake_csv(db, me, form, sec, data, calibration=cal)
    return cal
