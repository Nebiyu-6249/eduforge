"""Blackboard integration API (plan 14.8). Everything except /status and the OAuth
callback answers 403 until LMS_MODE is mock or blackboard (13.C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.api.schemas import job_out
from app.auth import current_faculty
from app.config import get_settings
from app.db import get_db
from app.lms import service as svc
from app.models import CourseVersion, Faculty, LmsColumnLink, LmsLink, LmsSync, LmsToken
from app.services.course_versions import WorkflowError


def _on() -> None:
    try:
        svc.require_on()
    except WorkflowError as e:
        raise HTTPException(e.status, str(e)) from e


open_router = APIRouter(prefix="/api/lms")
router = APIRouter(prefix="/api/lms", dependencies=[Depends(_on)])


def _run(db: Session, fn, *args, **kw):
    try:
        out = fn(db, *args, **kw)
        db.commit()
        return out
    except WorkflowError as e:
        db.rollback()
        raise HTTPException(e.status, {"message": str(e), **e.detail} if isinstance(e.detail, dict) else str(e)) from e


def _sync_out(s: LmsSync) -> dict:
    return {"id": s.id, "kind": s.kind, "status": s.status, "summary": s.summary, "at": s.at,
            "requests": len(s.request_log or []), "form_id": s.form_id}


@open_router.get("/status")
def status(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    mode = get_settings().lms_mode
    return {"mode": mode, "connected": db.get(LmsToken, me.id) is not None if mode != "off" else False}


@open_router.get("/callback")
def callback(code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    if error:
        raise HTTPException(401, f"Blackboard returned an error: {error}")
    _on()
    _run(db, svc.callback, code, state)
    return RedirectResponse(get_settings().frontend_url.rstrip("/") + "/?lms=connected", status_code=302)


@router.post("/connect")
def connect(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    url = _run(db, svc.connect, me)
    return {"connected": url is None, "authorize_url": url}


@router.post("/disconnect", status_code=204)
def disconnect(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    _run(db, svc.disconnect, me)


@router.get("/courses")
def courses(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return [c.__dict__ for c in _run(db, svc.courses, me)]


class LinkIn(BaseModel):
    course_version_id: int
    lms_course_id: str
    section_id: int | None = None


def _link_out(db: Session, ln: LmsLink) -> dict:
    cols = db.scalars(select(LmsColumnLink).where(LmsColumnLink.link_id == ln.id)).all()
    return {"id": ln.id, "course_version_id": ln.course_version_id, "section_id": ln.section_id,
            "lms_course_id": ln.lms_course_id, "lms_course_code": ln.lms_course_code, "lms_course_name": ln.lms_course_name,
            "lms_term": ln.lms_term, "linked_at": ln.linked_at,
            "columns": [{"form_id": c.form_id, "column_id": c.column_id, "column_name": c.column_name} for c in cols]}


@router.post("/links", status_code=201)
def make_link(body: LinkIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = db.get(CourseVersion, body.course_version_id)
    if cv is None or cv.faculty_id != me.id:
        raise HTTPException(404, "Course version not found.")
    ln = _run(db, svc.link, me, cv, body.section_id, body.lms_course_id)
    return _link_out(db, ln)


@router.get("/course-versions/{cv_id}/links")
def links(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = db.get(CourseVersion, cv_id)
    if cv is None or cv.faculty_id != me.id:
        raise HTTPException(404, "Course version not found.")
    return [_link_out(db, ln) for ln in db.scalars(select(LmsLink).where(LmsLink.course_version_id == cv.id))]


@router.delete("/links/{link_id}", status_code=204)
def unlink(link_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    def go(d: Session):
        d.delete(svc.own_link(d, me, link_id))
    _run(db, go)


class FormIn(BaseModel):
    form_id: int


@router.post("/links/{link_id}/push")
def push(link_id: int, body: FormIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return _sync_out(_run(db, lambda d: svc.push(d, me, svc.own_link(d, me, link_id), body.form_id)))


@router.get("/links/{link_id}/columns")
def columns(link_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    def go(d: Session):
        ln = svc.own_link(d, me, link_id)
        ad, tok, _log = svc.session(d, me)
        try:
            return [c.__dict__ for c in ad.columns(tok, ln.lms_course_id)]
        except svc.LmsError as e:
            raise svc._wrap(e) from e
    return _run(db, go)


class AttachIn(BaseModel):
    form_id: int
    column_id: str


@router.post("/links/{link_id}/attach")
def attach(link_id: int, body: AttachIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    _run(db, lambda d: svc.attach_column(d, me, svc.own_link(d, me, link_id), body.form_id, body.column_id))
    return _link_out(db, svc.own_link(db, me, link_id))


class PullIn(BaseModel):
    form_id: int
    section_id: int | None = None


@router.post("/links/{link_id}/pull")
def pull(link_id: int, body: PullIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    s = _run(db, lambda d: svc.pull(d, me, svc.own_link(d, me, link_id), body.form_id, body.section_id))
    section_id = body.section_id or svc.own_link(db, me, link_id).section_id
    job = jobs.enqueue(db, "grade", me, {"form_id": body.form_id, "section_id": section_id})
    return {**_sync_out(s), "job": job_out(job)}


class PassbackIn(BaseModel):
    form_id: int
    section_id: int | None = None
    dry_run: bool = True
    overwrite: list[str] = []  # pseudonyms whose grade changed in Blackboard and may be overwritten


@router.post("/links/{link_id}/passback")
def passback(link_id: int, body: PassbackIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return _sync_out(_run(db, lambda d: svc.passback(d, me, svc.own_link(d, me, link_id), body.form_id, body.section_id,
                                                     body.dry_run, body.overwrite)))


@router.get("/links/{link_id}/syncs")
def syncs(link_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    ln = _run(db, lambda d: svc.own_link(d, me, link_id))
    rows = db.scalars(select(LmsSync).where(LmsSync.link_id == ln.id).order_by(LmsSync.at.desc())).all()
    return [_sync_out(s) for s in rows]
