"""Grading & Feedback Assist API (plan 14.7). Every route except /status answers
403 until GRADING_ENABLED is set (data-protection approval, 13.D)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.api.schemas import job_out
from app.auth import current_faculty
from app.config import get_settings
from app.db import get_db
from app.drafts.sandbox import backend as sandbox_backend
from app.extraction.schema import GradeBand
from app.grading import calibration as cal_mod
from app.grading import intake
from app.grading import release as release_mod
from app.grading import service as svc
from app.models import (
    Appeal,
    AssessmentForm,
    CalibrationSet,
    Faculty,
    FeedbackDraft,
    GradeRelease,
    Item,
    ResponseScore,
    Section,
    Student,
    Submission,
)
from app.services.course_versions import WorkflowError


def _enabled() -> None:
    try:
        svc.require_enabled()
    except WorkflowError as e:
        raise HTTPException(e.status, str(e)) from e


status_router = APIRouter(prefix="/api/grading")
router = APIRouter(prefix="/api/grading", dependencies=[Depends(_enabled)])


def _err(e: WorkflowError) -> HTTPException:
    if isinstance(e.detail, dict):
        return HTTPException(e.status, {"message": str(e), **e.detail})
    return HTTPException(e.status, str(e))


def _run(db: Session, fn, *args, **kw):
    try:
        out = fn(db, *args, **kw)
        db.commit()
        return out
    except WorkflowError as e:
        db.rollback()
        raise _err(e) from e


async def _read(file: UploadFile) -> bytes:
    cap = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(cap + 1)
    if not data or len(data) > cap:
        raise HTTPException(413, "The file is empty or too large.")
    return data


def _form_section(db: Session, me: Faculty, form_id: int, section_id: int) -> tuple[AssessmentForm, Section]:
    try:
        form = svc.own_form(db, me, form_id)
        return form, svc.own_section(db, me, section_id, form)
    except WorkflowError as e:
        raise _err(e) from e


def _own_sub(db: Session, me: Faculty, sub_id: int) -> Submission:
    sub = db.get(Submission, sub_id)
    form = db.get(AssessmentForm, sub.form_id) if sub else None
    if sub is None or form is None or form.created_by_id != me.id:
        raise HTTPException(404, "Submission not found.")
    return sub


@status_router.get("/status")
def status(me: Faculty = Depends(current_faculty)):
    s = get_settings()
    return {"enabled": s.grading_enabled, "llm_approved": s.grading_llm_approved,
            "sandbox": sandbox_backend() if s.grading_enabled else None, "suggest_off": s.grading_suggest_off}


# ---- grading scale (4.4) ----------------------------------------------------------
class ScaleIn(BaseModel):
    bands: list[GradeBand]
    acknowledge_difference: bool = False
    note: str | None = None


@router.get("/course-versions/{cv_id}/scale")
def get_scale(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return _run(db, lambda d: svc.scale_view(d, svc.own_cv(d, me, cv_id)))


@router.post("/course-versions/{cv_id}/scale")
def set_scale(cv_id: int, body: ScaleIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return _run(db, lambda d: svc.confirm_scale(d, me, svc.own_cv(d, me, cv_id), body.bands,
                                                body.acknowledge_difference, body.note))


# ---- sections and rosters (4.1) -----------------------------------------------------
class SectionIn(BaseModel):
    label: str


def _section_out(db: Session, s: Section) -> dict:
    n = len(db.scalars(select(Student.id).where(Student.section_id == s.id)).all())
    return {"id": s.id, "label": s.label, "calibration": s.calibration, "students": n}


@router.get("/course-versions/{cv_id}/sections")
def sections(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _run(db, lambda d: svc.own_cv(d, me, cv_id))
    rows = db.scalars(select(Section).where(Section.course_version_id == cv.id).order_by(Section.label)).all()
    return [_section_out(db, s) for s in rows]


@router.post("/course-versions/{cv_id}/sections", status_code=201)
def add_section(cv_id: int, body: SectionIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    s = _run(db, lambda d: svc.create_section(d, me, svc.own_cv(d, me, cv_id), body.label))
    return _section_out(db, s)


@router.post("/sections/{section_id}/roster")
async def upload_roster(section_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                        me: Faculty = Depends(current_faculty)):
    data = await _read(file)
    return _run(db, lambda d: svc.add_roster(d, me, svc.own_section(d, me, section_id), intake.parse_roster(data)))


@router.get("/sections/{section_id}/roster")
def roster(section_id: int, reveal: bool = False, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Pseudonyms by default. ``reveal=true`` re-identifies (course faculty only; audit-logged)."""
    def go(d: Session):
        s = svc.own_section(d, me, section_id)
        people = svc.reveal(d, me, s, why="roster view") if reveal else {}
        return [{"pseudonym": st.pseudonym, **({"student_id": people[st.id].external_id, "name": people[st.id].name,
                                                  "email": people[st.id].email} if reveal else {})}
                for st in svc.students(d, s)]
    return _run(db, go)


# ---- forms, intake, scoring (4.2–4.9) ---------------------------------------------------
@router.get("/course-versions/{cv_id}/forms")
def gradable_forms(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _run(db, lambda d: svc.own_cv(d, me, cv_id))
    forms = db.scalars(select(AssessmentForm).where(AssessmentForm.course_version_id == cv.id,
                                                     AssessmentForm.status == "approved",
                                                     AssessmentForm.created_by_id == me.id)
                       .order_by(AssessmentForm.created_at)).all()
    return [{"id": f.id, "assessment_name": f.assessment_name, "version_label": f.version_label, "section": f.section,
             "items": len(f.items), "points": sum(fi.points for fi in f.items)} for f in forms]


@router.post("/forms/{form_id}/sections/{section_id}/submissions", status_code=202)
async def submissions(form_id: int, section_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                      me: Faculty = Depends(current_faculty)):
    form, section = _form_section(db, me, form_id, section_id)
    if section.calibration:
        raise HTTPException(409, "Calibration sets take their submissions when they are created.")
    data = await _read(file)
    name = (file.filename or "upload").strip()
    if name.lower().endswith(".csv"):
        out = _run(db, lambda d: svc.intake_csv(d, me, form, section, data))
    else:
        out = _run(db, lambda d: svc.intake_files(d, me, form, section, intake.files_from_upload(name, data)))
    job = jobs.enqueue(db, "grade", me, {"form_id": form.id, "section_id": section.id})
    return {**out, "job": job_out(job)}


class ScoreIn(BaseModel):
    rescore: bool = False


@router.post("/forms/{form_id}/sections/{section_id}/score", status_code=202)
def rescore(form_id: int, section_id: int, body: ScoreIn, db: Session = Depends(get_db),
            me: Faculty = Depends(current_faculty)):
    form, section = _form_section(db, me, form_id, section_id)
    return job_out(jobs.enqueue(db, "grade", me, {"form_id": form.id, "section_id": section.id, "rescore": body.rescore}))


def _cell(sc: ResponseScore) -> dict:
    return {"id": sc.id, "item_id": sc.item_id, "method": sc.method, "max": sc.max_points,
            "suggested": sc.suggested_points, "confirmed": sc.confirmed_points, "confidence": sc.confidence,
            "needs_faculty": sc.needs_faculty, "note": sc.note, "level_step": sc.level_step}


@router.get("/forms/{form_id}/sections/{section_id}/grid")
def grid(form_id: int, section_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    form, section = _form_section(db, me, form_id, section_id)
    fis = sorted(form.items, key=lambda f: f.position)
    subs = svc.section_submissions(db, form, section)
    open_appeals = {a.submission_id for a in db.scalars(select(Appeal).where(
        Appeal.submission_id.in_([s.id for s in subs] or [0]), Appeal.status == "open"))}
    rel = svc.released(db, form, section)
    return {
        "form": {"id": form.id, "assessment_name": form.assessment_name, "version_label": form.version_label,
                 "status": form.status},
        "section": _section_out(db, section),
        "items": [{"item_id": fi.item_id, "position": fi.position, "type": fi.item.type, "points": fi.points}
                  for fi in fis],
        "rows": [{"submission_id": s.id, "pseudonym": s.student.pseudonym, "status": s.status,
                  "redactions": s.redactions, "appeal_open": s.id in open_appeals,
                  "cells": {str(sc.item_id): _cell(sc) for sc in s.scores},
                  "suggested_total": round(sum(sc.suggested_points or 0 for sc in s.scores), 2),
                  "confirmed_total": round(sum(sc.confirmed_points or 0 for sc in s.scores), 2)
                  if s.scores and all(sc.confirmed_points is not None for sc in s.scores) else None}
                 for s in subs],
        "outliers": svc.outliers(db, form, section),
        "blockers": svc.blockers(db, form, section),
        "pending_feedback": svc.pending_feedback(db, subs),
        "released_at": rel.at if rel else None,
    }


@router.get("/submissions/{sub_id}")
def submission(sub_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    sub = _own_sub(db, me, sub_id)
    form = db.get(AssessmentForm, sub.form_id)
    assert form is not None
    pos = {fi.item_id: fi for fi in form.items}
    cells = {sc.item_id: sc for sc in sub.scores}
    fbs = db.scalars(select(FeedbackDraft).where(FeedbackDraft.submission_id == sub.id).order_by(FeedbackDraft.id)).all()
    appeals = db.scalars(select(Appeal).where(Appeal.submission_id == sub.id).order_by(Appeal.created_at)).all()
    return {
        "id": sub.id, "pseudonym": sub.student.pseudonym, "source": sub.source, "redactions": sub.redactions,
        "answers": [{
            "item_id": a["item_id"], "position": a["position"], "text": a["text"],
            "type": pos[a["item_id"]].item.type if a["item_id"] in pos else None,
            "question": _question(db, a["item_id"]),
            "score": ({**_cell(cells[a["item_id"]]), "criteria": cells[a["item_id"]].criteria,
                       "evidence": cells[a["item_id"]].evidence, "history": cells[a["item_id"]].history,
                       "override_reason": cells[a["item_id"]].override_reason}
                      if a["item_id"] in cells else None),
        } for a in sub.answers],
        "feedback": [{"id": f.id, "item_id": f.item_id, "text": f.text, "source": f.source, "status": f.status}
                     for f in fbs],
        "appeals": [{"id": a.id, "item_id": a.item_id, "reason": a.reason, "status": a.status, "outcome": a.outcome,
                     "created_at": a.created_at, "decided_at": a.decided_at} for a in appeals],
    }


def _question(db: Session, item_id: int) -> str:
    from app.grading.scoring import question_text

    it = db.get(Item, item_id)
    return question_text(it)[:1500] if it else ""


class ConfirmIn(BaseModel):
    points: float
    reason: str | None = None


@router.post("/scores/{score_id}/confirm")
def confirm(score_id: int, body: ConfirmIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    sc = db.get(ResponseScore, score_id)
    if sc is None:
        raise HTTPException(404, "Mark not found.")
    _own_sub(db, me, sc.submission_id)
    return _cell(_run(db, svc.confirm, me, sc, body.points, body.reason))


class BulkIn(BaseModel):
    item_id: int | None = None


@router.post("/forms/{form_id}/sections/{section_id}/confirm-key")
def confirm_key(form_id: int, section_id: int, body: BulkIn, db: Session = Depends(get_db),
                me: Faculty = Depends(current_faculty)):
    form, section = _form_section(db, me, form_id, section_id)
    return {"confirmed": _run(db, svc.bulk_confirm_key, me, form, section, body.item_id)}


class FeedbackIn(BaseModel):
    action: Literal["approve", "reject", "edit"]
    text: str | None = None


@router.post("/feedback/{fb_id}")
def feedback(fb_id: int, body: FeedbackIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    fb = db.get(FeedbackDraft, fb_id)
    if fb is None:
        raise HTTPException(404, "Feedback not found.")
    _own_sub(db, me, fb.submission_id)
    f = _run(db, svc.feedback_action, me, fb, body.action, body.text)
    return {"id": f.id, "item_id": f.item_id, "text": f.text, "source": f.source, "status": f.status}


class NewFeedbackIn(BaseModel):
    item_id: int | None = None
    text: str


@router.post("/submissions/{sub_id}/feedback", status_code=201)
def new_feedback(sub_id: int, body: NewFeedbackIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    sub = _own_sub(db, me, sub_id)
    f = _run(db, svc.add_feedback, me, sub, body.item_id, body.text)
    return {"id": f.id, "item_id": f.item_id, "text": f.text, "source": f.source, "status": f.status}


# ---- release (4.11) ---------------------------------------------------------------------
@router.post("/forms/{form_id}/sections/{section_id}/release")
def release(form_id: int, section_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    form, section = _form_section(db, me, form_id, section_id)
    name, data = _run(db, release_mod.release, me, form, section)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/forms/{form_id}/sections/{section_id}/releases")
def releases(form_id: int, section_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    form, section = _form_section(db, me, form_id, section_id)
    rows = db.scalars(select(GradeRelease).where(GradeRelease.form_id == form.id, GradeRelease.section_id == section.id)
                      .order_by(GradeRelease.at.desc())).all()
    return [{"id": r.id, "at": r.at, "channel": r.channel, "students": r.n_students} for r in rows]


# ---- appeals (4.12) ---------------------------------------------------------------------
class AppealIn(BaseModel):
    item_id: int | None = None
    reason: str


@router.post("/submissions/{sub_id}/appeals", status_code=201)
def appeal(sub_id: int, body: AppealIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    sub = _own_sub(db, me, sub_id)
    a = _run(db, svc.open_appeal, me, sub, body.item_id, body.reason)
    return {"id": a.id, "status": a.status}


class DecideIn(BaseModel):
    outcome: str
    points: dict[int, float] = {}


@router.post("/appeals/{appeal_id}/decide")
def decide(appeal_id: int, body: DecideIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    ap = db.get(Appeal, appeal_id)
    if ap is None:
        raise HTTPException(404, "Appeal not found.")
    _own_sub(db, me, ap.submission_id)
    a = _run(db, svc.decide_appeal, me, ap, body.outcome, body.points)
    return {"id": a.id, "status": a.status, "outcome": a.outcome}


# ---- calibration (4.13) ------------------------------------------------------------------
@router.post("/forms/{form_id}/calibration", status_code=202)
async def calibration(form_id: int, file: UploadFile = File(...), description: str = Form(""),
                      db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    try:
        form = svc.own_form(db, me, form_id)
    except WorkflowError as e:
        raise _err(e) from e
    data = await _read(file)
    cal = _run(db, svc.create_calibration, me, form, data, description)
    job = jobs.enqueue(db, "grade", me, {"form_id": form.id, "section_id": cal.section_id})
    return {"calibration_id": cal.id, "section_id": cal.section_id, "job": job_out(job)}


@router.get("/forms/{form_id}/calibration")
def calibrations(form_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    try:
        form = svc.own_form(db, me, form_id)
    except WorkflowError as e:
        raise _err(e) from e
    out = []
    for c in db.scalars(select(CalibrationSet).where(CalibrationSet.form_id == form.id).order_by(CalibrationSet.id)):
        rows = cal_mod.report(cal_mod.pairs_for(db, c))
        out.append({"id": c.id, "description": c.description, "section_id": c.section_id, "created_at": c.created_at,
                    "report": rows, "gate_misses": cal_mod.gate(rows)})
    return out
