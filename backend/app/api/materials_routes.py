"""Course materials library API (plan 2.1–2.4)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.api.schemas import JobOut, job_out
from app.audit import record
from app.auth import current_faculty
from app.config import get_settings
from app.db import get_db
from app.materials import service as svc
from app.models import CourseVersion, Faculty, Material
from app.services.course_versions import WorkflowError

router = APIRouter(prefix="/api")


class MaterialOut(BaseModel):
    id: int
    title: str
    filename: str
    kind: str
    week_no: int | None
    licensed: bool
    status: str
    error: str | None
    chunk_count: int
    embed_model: str | None
    created_at: datetime
    indexed_at: datetime | None


def _out(m: Material) -> MaterialOut:
    return MaterialOut(id=m.id, title=m.title, filename=m.file.filename, kind=m.kind, week_no=m.week_no,
                       licensed=m.licensed, status=m.status, error=m.error, chunk_count=m.chunk_count,
                       embed_model=m.embed_model, created_at=m.created_at, indexed_at=m.indexed_at)


def _cv(db: Session, me: Faculty, cv_id: int) -> CourseVersion:
    cv = db.get(CourseVersion, cv_id)
    if cv is None or cv.faculty_id != me.id:
        raise HTTPException(404, "Course version not found.")
    return cv


def _material(db: Session, me: Faculty, mid: int) -> Material:
    m = db.get(Material, mid)
    if m is None or m.faculty_id != me.id:
        raise HTTPException(404, "Material not found.")
    return m


@router.get("/course-versions/{cv_id}/materials", response_model=list[MaterialOut])
def list_materials(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _cv(db, me, cv_id)
    if cv.course_id is None:
        return []
    rows = db.scalars(select(Material).where(Material.course_id == cv.course_id, Material.faculty_id == me.id)
                      .order_by(Material.week_no.is_(None), Material.week_no, Material.id)).all()
    return [_out(m) for m in rows]


@router.post("/course-versions/{cv_id}/materials", response_model=JobOut, status_code=202)
async def upload_material(cv_id: int, file: UploadFile = File(...), kind: str = Form("notes"),
                          week_no: int | None = Form(None), title: str | None = Form(None),
                          licensed: bool = Form(False), db: Session = Depends(get_db),
                          me: Faculty = Depends(current_faculty)):
    """Store the file, then index it as a job (extract, chunk, embed)."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB.")
    if not data:
        raise HTTPException(422, "Empty file.")
    cv = _cv(db, me, cv_id)
    try:
        m = svc.add_material(db, me, cv, file.filename or "material", data, kind, week_no, title, licensed)
    except WorkflowError as e:
        db.rollback()
        raise HTTPException(e.status, str(e)) from e
    record(db, me, "material_upload", {"material_id": m.id, "kind": kind, "licensed": licensed})
    db.commit()
    return job_out(jobs.enqueue(db, "index_material", me, {"material_id": m.id}))


@router.post("/materials/{mid}/reindex", response_model=JobOut, status_code=202)
def reindex(mid: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    m = _material(db, me, mid)
    return job_out(jobs.enqueue(db, "index_material", me, {"material_id": m.id}))


class MaterialPatch(BaseModel):
    week_no: int | None = None
    kind: str | None = None
    licensed: bool | None = None
    title: str | None = None


@router.patch("/materials/{mid}", response_model=JobOut, status_code=202)
def update_material(mid: int, body: MaterialPatch, db: Session = Depends(get_db),
                    me: Faculty = Depends(current_faculty)):
    """Change tags (week, kind, licence) and re-index so chunks carry them."""
    m = _material(db, me, mid)
    data = body.model_dump(exclude_unset=True)
    if "kind" in data and data["kind"] not in svc.MATERIAL_KINDS:
        raise HTTPException(422, f"Kind must be one of {', '.join(svc.MATERIAL_KINDS)}.")
    for k, v in data.items():
        setattr(m, k, v)
    db.commit()
    return job_out(jobs.enqueue(db, "index_material", me, {"material_id": m.id}))


@router.delete("/materials/{mid}", status_code=204)
def delete_material(mid: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    m = _material(db, me, mid)
    record(db, me, "material_delete", {"material_id": m.id, "title": m.title})
    db.delete(m)
    db.commit()
