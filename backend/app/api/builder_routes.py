"""Assessment Builder, bank import, term diff, solvability, shared bank, program coverage, QA viewer (plan 3.x)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.api.schemas import JobOut, job_out, time_left_words
from app.audit import record
from app.auth import current_faculty, current_viewer
from app.builder import program
from app.builder import service as svc
from app.config import get_settings
from app.db import get_db
from app.models import (
    AssessmentForm,
    CourseVersion,
    Faculty,
    Item,
    Job,
    SolvabilityCheck,
    VersionDiff,
)
from app.services.course_versions import WorkflowError

router = APIRouter(prefix="/api")


def _cv(db: Session, me: Faculty, cv_id: int) -> CourseVersion:
    cv = db.get(CourseVersion, cv_id)
    if cv is None or cv.faculty_id != me.id:
        raise HTTPException(404, "Course version not found.")
    return cv


def _form(db: Session, me: Faculty, form_id: int) -> AssessmentForm:
    f = db.get(AssessmentForm, form_id)
    if f is None or f.created_by_id != me.id:
        raise HTTPException(404, "Form not found.")
    return f


def _run(db: Session, fn, *args, **kw):
    try:
        out = fn(db, *args, **kw)
        db.commit()
        return out
    except WorkflowError as e:
        db.rollback()
        raise HTTPException(e.status, str(e)) from e


def _form_out(f: AssessmentForm, db: Session | None = None) -> dict:
    approved = sum(1 for fi in f.items if fi.item.status == "approved")
    asked = (f.blueprint or {}).get("asked_for") or len(f.items)
    job = db.get(Job, f.job_id) if (db is not None and f.job_id) else None
    return {
        "id": f.id, "assessment_name": f.assessment_name, "version_label": f.version_label, "section": f.section,
        "status": f.status, "blueprint": f.blueprint, "gaps": f.gaps, "created_at": f.created_at,
        "job_id": f.job_id, "error": f.error,
        # What the "Quizzes and exams" list needs without opening every quiz.
        "question_count": len(f.items), "asked_for": asked, "approved_count": approved,
        "points": sum(fi.points for fi in f.items),
        "last_change": f.approved_at or f.created_at,
        "job": {"progress": job.progress or 0, "time_left": time_left_words(job), "status": job.status}
               if job is not None else None,
        "approved_by": f.approved_by.name if f.approved_by else None, "approved_at": f.approved_at,
        "items": [{"item_id": fi.item_id, "position": fi.position, "points": fi.points, "type": fi.item.type,
                   "status": fi.item.status, "clo_numbers": fi.item.clo_ids, "week_no": fi.item.week_no,
                   "difficulty": fi.item.difficulty, "option_order": fi.option_order,
                   "summary": str(fi.item.body_json.get("stem") or fi.item.body_json.get("question")
                                  or fi.item.body_json.get("statement") or fi.item.body_json.get("prompt")
                                  or fi.item.body_json.get("title") or "")[:160]}
                  for fi in sorted(f.items, key=lambda x: x.position)],
        "coverage": svc.coverage_report(f),
    }


# ---- blueprint + build (3.1–3.3) --------------------------------------------

@router.get("/course-versions/{cv_id}/assessments")
def assessments(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return svc.rows(_cv(db, me, cv_id))


@router.get("/course-versions/{cv_id}/blueprint")
def get_blueprint(cv_id: int, name: str, week: int | None = None, db: Session = Depends(get_db),
                  me: Faculty = Depends(current_faculty)):
    try:
        return svc.default_blueprint(_cv(db, me, cv_id), me, name, week)
    except WorkflowError as e:
        raise HTTPException(e.status, str(e)) from e


class MixIn(BaseModel):
    type: str
    count: int
    points: float | None = None


class QuizIn(BaseModel):
    """What a teacher chooses in "Create a quiz or exam"."""

    assessment_name: str | None = None  # the row of the syllabus, or None for practice questions
    weeks: list[int] = []
    clo_numbers: list[int] = []
    difficulty: Literal["easy", "medium", "hard"] | None = None
    mix: list[MixIn] = []
    notes: str | None = None


@router.get("/course-versions/{cv_id}/quiz-options")
def quiz_options(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Everything the four steps of "Create a quiz or exam" need, in one call
    and in plain words: what you can make, the weeks and outcomes it covers,
    which slides will be used and which question types fit."""
    from app.builder import quiz
    from app.drafts.bloom import is_skills_clo
    from app.drafts.schemas import QUESTION_TYPES, TYPE_LABELS
    from app.extraction.schema import ExtractedSyllabus
    from app.materials.service import sensitive_ok  # noqa: F401  (kept for parity with retrieval rules)
    from app.models import Material

    cv = _cv(db, me, cv_id)
    rec = ExtractedSyllabus.model_validate(cv.record)
    rows = svc.rows(cv)
    choices = []
    for r in rows:
        bits = [f"{r['weight_pct']:g}% of the grade" if r.get("weight_pct") is not None else None,
                f"week {r['week']}" if r.get("week") else None]
        choices.append({
            "name": r["name"],
            "week": r.get("week"),
            "weight_pct": r.get("weight_pct"),
            "subtitle": " · ".join(b for b in bits if b),
            "weeks": _weeks_up_to(rec, r.get("week")),
            "clo_numbers": sorted(r.get("clos") or []),
        })
    mats = []
    if cv.course_id is not None:
        mats = [m for m in db.scalars(select(Material).where(Material.course_id == cv.course_id,
                                                             Material.status == "indexed")).all()]
    return {
        "can_create": cv.status == "locked",
        "course": f"{rec.course.code or ''} {rec.course.title or ''}".strip(),
        "term": rec.offering.term,
        "choices": choices,
        "weeks": [{"week_no": w.week_no, "topics": w.topics} for w in rec.weekly],
        "outcomes": [{"number": c.number, "text": c.text, "skills": is_skills_clo(c.text)} for c in rec.clos],
        "slides": [{"title": m.title, "week_no": m.week_no} for m in mats],
        "types": [{"type": t, "label": TYPE_LABELS[t], "points": quiz.DEFAULT_POINTS.get(t, 5.0),
                   "minutes": _MINUTES.get(t, 3)}
                  for t in ("mcq", "short_answer", "problem", "code_exercise", "case_study")
                  if t in QUESTION_TYPES or t in ("code_exercise", "case_study")],
        "max_questions": quiz.MAX_QUESTIONS,
    }


_MINUTES = {"mcq": 2, "short_answer": 5, "problem": 10, "code_exercise": 20, "case_study": 20}


def _weeks_up_to(rec, week: int | None) -> list[int]:
    weeks = [w.week_no for w in rec.weekly]
    return [w for w in weeks if w <= week] if week else weeks


@router.post("/course-versions/{cv_id}/quizzes", response_model=JobOut, status_code=202)
def create_quiz(cv_id: int, body: QuizIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """One request writes every kind of question asked for and assembles the
    paper. Refused up front if the request cannot work."""
    from app.builder import quiz

    cv = _cv(db, me, cv_id)
    try:
        mix = quiz.parse_mix([m.model_dump() for m in body.mix])
        form = quiz.start(db, cv, me, assessment_name=body.assessment_name, mix=mix,
                          clo_numbers=body.clo_numbers, weeks=body.weeks, difficulty=body.difficulty)
    except WorkflowError as e:
        db.rollback()
        raise HTTPException(e.status, str(e)) from e
    asked = sum(p.count for p in mix)
    db.commit()
    job = jobs.enqueue(db, "create_quiz", me,
                       {"course_version_id": cv.id, "form_id": form.id, **body.model_dump()},
                       title=f"{form.assessment_name} · {asked} question{'' if asked == 1 else 's'}",
                       course_version_id=cv.id, link=f"/v/{cv.id}/quiz/{form.id}", size=asked)
    form.job_id = job.id
    db.commit()
    return job_out(job)


class BuildIn(BaseModel):
    blueprint: dict[str, Any]
    versions: int = 1
    sections: list[str] | None = None
    allow_reuse: bool = False
    allow_overlap: bool = False


@router.post("/course-versions/{cv_id}/forms", status_code=201)
def build_forms(cv_id: int, body: BuildIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _cv(db, me, cv_id)
    forms = _run(db, svc.build, cv, me, body.blueprint, body.versions, body.sections, body.allow_reuse,
                 body.allow_overlap)
    return [_form_out(f, db) for f in forms]


@router.get("/course-versions/{cv_id}/forms")
def list_forms(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _cv(db, me, cv_id)
    rows = db.scalars(select(AssessmentForm).where(AssessmentForm.course_version_id == cv.id)
                      .order_by(AssessmentForm.id.desc())).all()
    return [_form_out(f, db) for f in rows]


@router.get("/forms/{form_id}")
def get_form(form_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return _form_out(_form(db, me, form_id), db)


class FormEdit(BaseModel):
    action: Literal["reorder", "points", "swap", "approve"]
    item_ids: list[int] | None = None
    item_id: int | None = None
    points: float | None = None
    replace_with: int | None = None


@router.post("/forms/{form_id}/edit")
def edit_form(form_id: int, body: FormEdit, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    f = _form(db, me, form_id)
    cv = db.get(CourseVersion, f.course_version_id)
    if body.action == "reorder":
        _run(db, svc.reorder, f, me, body.item_ids or [])
    elif body.action == "points":
        _run(db, svc.set_points, f, me, body.item_id or 0, body.points if body.points is not None else -1)
    elif body.action == "swap":
        _run(db, svc.swap, cv, f, me, body.item_id or 0, body.replace_with or 0)
    else:
        _run(db, svc.approve, f, me)
    db.refresh(f)
    return _form_out(f, db)


@router.delete("/forms/{form_id}", status_code=204)
def delete_form(form_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    f = _form(db, me, form_id)
    if f.status == "approved":
        raise HTTPException(409, "Approved forms are kept (they may have been used); edit it to return it to draft.")
    db.delete(f)
    db.commit()


class FormExport(BaseModel):
    format: Literal["docx", "pdf", "qti"] = "docx"
    # Same split as the Draft Studio export: the sat paper and the answer key
    # are separate files. Ignored for QTI, which carries its own answers.
    part: Literal["paper", "key"] = "paper"


@router.post("/forms/{form_id}/export")
def export_form(form_id: int, body: FormExport, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    f = _form(db, me, form_id)
    cv = db.get(CourseVersion, f.course_version_id)
    data, name, mime = _run(db, svc.export_form, cv, f, me, body.format, body.part)
    record(db, me, "form_export", {"form_id": f.id, "format": body.format, "part": body.part})
    db.commit()
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/course-versions/{cv_id}/qti")
def export_items_qti(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """All approved items of this course version as a QTI 2.1 package (3.6)."""
    from app.builder import qti

    cv = _cv(db, me, cv_id)
    items = db.scalars(select(Item).where(Item.course_version_id == cv.id, Item.status == "approved",
                                          Item.type.in_(("mcq", "short_answer", "problem", "case_study")))).all()
    if not items:
        raise HTTPException(409, "No approved questions to export.")
    record(db, me, "export", {"course_version_id": cv.id, "format": "qti", "items": len(items)})
    db.commit()
    data = qti.package(f"{cv.record['course']['code']} bank", [(i, 1.0, None) for i in items], as_test=False)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{cv.record["course"]["code"]}_bank_qti.zip"'})


# ---- bank import (3.7) ------------------------------------------------------

@router.post("/course-versions/{cv_id}/bank-import", response_model=JobOut, status_code=202)
async def bank_import(cv_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                      me: Faculty = Depends(current_faculty)):
    cv = _cv(db, me, cv_id)
    if cv.status != "locked":
        raise HTTPException(409, "Import into the locked working version.")
    data = await file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    if not data or len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "Empty or too large.")
    from app.materials.service import _store_any

    try:
        sf = _store_any(db, me, file.filename or "bank", data)
    except WorkflowError as e:
        raise HTTPException(e.status, str(e)) from e
    record(db, me, "bank_import", {"course_version_id": cv.id, "file": sf.filename})
    db.commit()
    return job_out(jobs.enqueue(db, "bank_import", me, {"course_version_id": cv.id, "source_file_id": sf.id}))


# ---- term diff (3.8) --------------------------------------------------------

@router.get("/course-versions/{cv_id}/diff")
def term_diff(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _cv(db, me, cv_id)
    vd = db.scalar(select(VersionDiff).where(VersionDiff.to_version_id == cv.id).order_by(VersionDiff.id.desc()))
    if vd is None:
        return None
    prev = db.get(CourseVersion, vd.from_version_id)
    return {"from_version_id": vd.from_version_id, "from_term": prev.term if prev else None,
            "diff": vd.diff, "affected_item_ids": vd.affected_item_ids}


# ---- solvability (3.9) ------------------------------------------------------

@router.post("/drafts/{item_id}/solvability", response_model=JobOut, status_code=202)
def solvability(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    from app.materials.service import sensitive_ok

    it = db.get(Item, item_id)
    if it is None or it.course_version.faculty_id != me.id:
        raise HTTPException(404, "Item not found.")
    if not sensitive_ok():
        raise HTTPException(409, "The configured model may not see exam items (plan 14.10). Use a local model or a "
                                 "no-retention provider (LLM_NO_RETENTION) for this check.")
    return job_out(jobs.enqueue(db, "solvability", me, {"item_id": it.id}))


@router.get("/drafts/{item_id}/solvability")
def solvability_results(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    it = db.get(Item, item_id)
    if it is None or it.course_version.faculty_id != me.id:
        raise HTTPException(404, "Item not found.")
    rows = db.scalars(select(SolvabilityCheck).where(SolvabilityCheck.item_id == it.id)
                      .order_by(SolvabilityCheck.id.desc())).all()
    return [{"model": r.model, "verdict": r.verdict, "detail": r.detail, "suggestions": r.suggestions, "at": r.at}
            for r in rows]


# ---- shared bank (3.10) -----------------------------------------------------

class ShareIn(BaseModel):
    shared: bool


@router.post("/drafts/{item_id}/share", status_code=204)
def share(item_id: int, body: ShareIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(404, "Item not found.")
    _run(db, svc.share, it, me, body.shared)


@router.get("/course-versions/{cv_id}/shared-bank")
def shared_bank(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _cv(db, me, cv_id)
    try:
        rows = svc.shared_bank(db, cv, me)
    except WorkflowError as e:
        raise HTTPException(e.status, str(e)) from e
    return [{"item_id": it.id, "type": it.type, "clo_numbers": it.clo_ids, "week_no": it.week_no,
             "shared_by": s.shared_by_id, "mine": it.course_version.faculty_id == me.id,
             "summary": str(it.body_json.get("stem") or it.body_json.get("question") or "")[:160]}
            for it, s in rows]


# ---- program-wide coverage (3.11) + QA viewer (3.12) ------------------------

@router.get("/programs")
def list_programs(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return program.programs(db)


@router.get("/programs/{program_id}/coverage")
def program_coverage(program_id: int, term: str | None = None, db: Session = Depends(get_db),
                     me: Faculty = Depends(current_faculty)):
    try:
        return program.coverage(db, program_id, term)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/qa/programs")
def qa_programs(db: Session = Depends(get_db), viewer: Faculty = Depends(current_viewer)):
    return program.programs(db)


@router.get("/qa/programs/{program_id}/coverage")
def qa_coverage(program_id: int, term: str | None = None, db: Session = Depends(get_db),
                viewer: Faculty = Depends(current_viewer)):
    try:
        return program.coverage(db, program_id, term)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/qa/syllabi")
def qa_syllabi(term: str | None = None, db: Session = Depends(get_db), viewer: Faculty = Depends(current_viewer)):
    """Locked course versions (the official course records): never items or exams."""
    q = select(CourseVersion).where(CourseVersion.status == "locked")
    if term:
        q = q.where(CourseVersion.term == term)
    return [{"id": cv.id, "code": cv.record["course"]["code"], "title": cv.record["course"]["title"],
             "term": cv.term, "version_no": cv.version_no} for cv in db.scalars(q).all()]


@router.get("/qa/syllabi/{cv_id}")
def qa_syllabus(cv_id: int, db: Session = Depends(get_db), viewer: Faculty = Depends(current_viewer)):
    cv = db.get(CourseVersion, cv_id)
    if cv is None or cv.status not in {"locked", "superseded"}:
        raise HTTPException(404, "Not found.")
    rec = dict(cv.record)
    rec.pop("raw_sections", None)
    rec.pop("sources", None)
    return {"id": cv.id, "term": cv.term, "version_no": cv.version_no, "record": rec}


@router.get("/course-versions/{cv_id}/pool")
def bank_pool(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Approved items usable in forms: own items of this course plus colleagues' shared ones."""
    cv = _cv(db, me, cv_id)
    return [{"item_id": it.id, "type": it.type, "clo_numbers": it.clo_ids, "week_no": it.week_no,
             "difficulty": it.difficulty, "mine": it.course_version.faculty_id == me.id,
             "summary": str(it.body_json.get("stem") or it.body_json.get("question") or it.body_json.get("statement")
                            or it.body_json.get("prompt") or it.body_json.get("title") or "")[:160]}
            for it in svc.pool(db, cv, me)]
