from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs, storage
from app.audit import record
from app.auth import current_faculty
from app.config import get_settings
from app.db import get_db
from app.extraction.pipeline import UnsupportedFile
from app.models import CourseVersion, Faculty, Job, SourceFile
from app.services import course_versions as svc
from app.validation.rules import RULE_TITLES

from .schemas import (
    EditOut,
    EditRequest,
    FacultyOut,
    FlagOut,
    JobOut,
    PreviousVersion,
    ResolveRequest,
    RolloverRequest,
    VersionDetail,
    VersionSummary,
    job_out,
)

router = APIRouter(prefix="/api")


def _get_cv(db: Session, me: Faculty, cv_id: int) -> CourseVersion:
    cv = db.get(CourseVersion, cv_id)
    if cv is None or cv.faculty_id != me.id:  # faculty see only their own courses
        raise HTTPException(404, "Course version not found.")
    return cv


def _summary(cv: CourseVersion) -> dict:
    course = cv.record.get("course", {})
    return dict(
        id=cv.id, status=cv.status, origin=cv.origin,
        course_code=course.get("code"), course_title=course.get("title"),
        term=cv.term or cv.record.get("offering", {}).get("term"),
        version_no=cv.version_no,
        source_filename=cv.source_file.filename if cv.source_file else None,
        open_blocking=len(svc.blocking_flags(cv)),
        created_at=cv.created_at, updated_at=cv.updated_at, locked_at=cv.locked_at,
        parent_version_id=cv.parent_version_id,
    )


def _flag(f) -> FlagOut:
    return FlagOut(id=f.id, rule_id=f.rule_id, rule_title=RULE_TITLES.get(f.rule_id, f.rule_id),
                   severity=f.severity, message=f.message, evidence_refs=f.evidence_refs or [],
                   choices=[{"label": c["label"]} for c in (f.choices or [])],
                   status=f.status, resolution=f.resolution, resolution_note=f.resolution_note,
                   resolved_by=f.resolved_by.name if f.resolved_by else None, resolved_at=f.resolved_at)


def _detail(cv: CourseVersion) -> VersionDetail:
    order = {"open": 0, "resolved": 1, "cleared": 2}
    sev = {"error": 0, "warning": 1, "info": 2}
    flags = sorted(cv.flags, key=lambda f: (order.get(f.status, 9), sev.get(f.severity, 9), f.id))
    prev = svc.previous_version(cv) if cv.status in svc.EDITABLE else None
    return VersionDetail(
        **_summary(cv), record=cv.record, flags=[_flag(f) for f in flags], edit_count=len(cv.edits),
        can_lock=cv.status in svc.EDITABLE and not svc.blocking_flags(cv),
        previous=PreviousVersion(id=prev.id, term=prev.term, version_no=prev.version_no,
                                 matching_settled_flags=len(svc.carry_over_matches(cv, prev))) if prev else None,
    )


def _run(db: Session, fn, *args):
    try:
        out = fn(db, *args)
        db.commit()
        return out
    except svc.WorkflowError as e:
        db.rollback()
        raise HTTPException(e.status, {"message": str(e), "items": e.detail} if e.detail else str(e)) from e


# --------------------------------------------------------------------------- #

@router.get("/health")
def health():
    return {"ok": True}


@router.get("/me", response_model=FacultyOut)
def me(me: Faculty = Depends(current_faculty)):
    team = {e.lower() for e in get_settings().team_emails}
    return FacultyOut(id=me.id, email=me.email, name=me.name, is_team=me.email.lower() in team)


@router.get("/rules")
def rules():
    return RULE_TITLES


@router.post("/syllabi", response_model=JobOut, status_code=202)
async def upload_syllabus(file: UploadFile = File(...), db: Session = Depends(get_db),
                          me: Faculty = Depends(current_faculty)):
    """Store the file now; extraction + validation run as a job (plan 1.9).
    Poll GET /api/jobs/{id}; its result holds the new course_version_id."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB.")
    if not data:
        raise HTTPException(422, "Empty file.")
    try:
        sf = svc.store_file(db, me, file.filename or "syllabus", data)
    except UnsupportedFile as e:
        db.rollback()
        raise HTTPException(415, str(e)) from e
    record(db, me, "syllabus_upload", {"source_file_id": sf.id, "filename": sf.filename, "sha256": sf.sha256})
    db.commit()
    job = jobs.enqueue(db, "extract", me, {"source_file_id": sf.id, "filename": sf.filename})
    return job_out(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    job = db.get(Job, job_id)
    if job is None or job.faculty_id != me.id:
        raise HTTPException(404, "Job not found.")
    return job_out(job)


@router.get("/course-versions", response_model=list[VersionSummary])
def list_versions(term: str | None = None, include_superseded: bool = False, db: Session = Depends(get_db),
                  me: Faculty = Depends(current_faculty)):
    q = select(CourseVersion).where(CourseVersion.faculty_id == me.id).order_by(CourseVersion.updated_at.desc())
    rows = db.scalars(q).all()
    out = [VersionSummary(**_summary(cv)) for cv in rows if include_superseded or cv.status != "superseded"]
    if term:
        out = [v for v in out if (v.term or "").lower() == term.lower()]
    return out


@router.get("/course-versions/{cv_id}", response_model=VersionDetail)
def get_version(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return _detail(_get_cv(db, me, cv_id))


@router.patch("/course-versions/{cv_id}/record", response_model=VersionDetail)
def edit_record(cv_id: int, body: EditRequest, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    _run(db, svc.apply_edits, cv, me, [o.model_dump() for o in body.ops], body.note)
    db.refresh(cv)
    return _detail(cv)


@router.post("/course-versions/{cv_id}/flags/{flag_id}/resolve", response_model=VersionDetail)
def resolve(cv_id: int, flag_id: int, body: ResolveRequest, db: Session = Depends(get_db),
            me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    _run(db, svc.resolve_flag, cv, me, flag_id, body.action, body.note)
    db.refresh(cv)
    return _detail(cv)


@router.post("/course-versions/{cv_id}/revalidate", response_model=VersionDetail)
def revalidate(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    if cv.status not in svc.EDITABLE:
        raise HTTPException(409, f"This version is {cv.status}.")
    _run(db, svc.revalidate, cv, me, True)
    db.refresh(cv)
    return _detail(cv)


@router.post("/course-versions/{cv_id}/lock", response_model=VersionDetail)
def lock(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    record(db, me, "lock", {"course_version_id": cv.id})
    _run(db, svc.lock, cv, me)
    db.refresh(cv)
    return _detail(cv)


@router.post("/course-versions/{cv_id}/revise", response_model=VersionDetail, status_code=201)
def revise(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    new = _run(db, svc.revise, _get_cv(db, me, cv_id), me)
    db.refresh(new)
    return _detail(new)


@router.post("/course-versions/{cv_id}/rollover", response_model=VersionDetail, status_code=201)
def rollover(cv_id: int, body: RolloverRequest, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    new = _run(db, svc.rollover, _get_cv(db, me, cv_id), me, body.term)
    db.refresh(new)
    return _detail(new)


@router.delete("/course-versions/{cv_id}", status_code=204)
def discard(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    if cv.status not in svc.EDITABLE:
        raise HTTPException(409, "Locked and superseded versions are kept for the audit trail.")
    if db.scalar(select(CourseVersion.id).where(CourseVersion.parent_version_id == cv.id)):
        raise HTTPException(409, "Another version was created from this one.")
    db.delete(cv)
    db.commit()


@router.get("/course-versions/{cv_id}/edits", response_model=list[EditOut])
def edits(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    return [EditOut(id=e.id, op=e.op, field_path=e.field_path, old_value=e.old_value, new_value=e.new_value,
                    note=e.note, edited_by=e.edited_by.name, at=e.at) for e in cv.edits]


@router.get("/course-versions/{cv_id}/coverage")
def coverage(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return svc.coverage(_get_cv(db, me, cv_id))


def _safe_name(name: str) -> str:
    """A file name safe inside a Content-Disposition header."""
    import re

    return re.sub(r"[^\w.\- ]+", "_", name)[:150] or "file"


@router.get("/course-versions/{cv_id}/source")
def source_file(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    sf: SourceFile | None = cv.source_file
    if sf is None:
        raise HTTPException(404, "No source file.")
    data = storage.get(db, sf.storage_key)
    if data is None:
        raise HTTPException(410, "The stored file is missing.")
    record(db, me, "source_download", {"course_version_id": cv.id, "source_file_id": sf.id})
    db.commit()
    return Response(data, media_type=sf.mime,
                    headers={"Content-Disposition": f'attachment; filename="{_safe_name(sf.filename)}"'})


@router.get("/course-versions/{cv_id}/source/pages/{page}")
def source_page(cv_id: int, page: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """PNG of one page of the uploaded PDF, for the review screen's source panel
    (plan 1.11). Rendered once, then cached next to the stored file."""
    cv = _get_cv(db, me, cv_id)
    sf: SourceFile | None = cv.source_file
    if sf is None or not sf.mime.endswith("pdf"):
        raise HTTPException(404, "Page images exist only for PDF syllabi.")
    cache = storage.cache_dir() / "pages" / sf.sha256 / f"{page}.png"
    if not cache.exists():
        import io

        import pdfplumber

        src = storage.get(db, sf.storage_key)
        if src is None:
            raise HTTPException(410, "The stored file is missing.")
        with pdfplumber.open(io.BytesIO(src)) as pdf:
            if not 1 <= page <= len(pdf.pages):
                raise HTTPException(404, f"The file has {len(pdf.pages)} pages.")
            cache.parent.mkdir(parents=True, exist_ok=True)
            pdf.pages[page - 1].to_image(resolution=110).original.save(cache, format="PNG")
    return FileResponse(cache, media_type="image/png")


class ChooseRequest(BaseModel):
    choice: int


@router.post("/course-versions/{cv_id}/flags/{flag_id}/choose", response_model=VersionDetail)
def choose(cv_id: int, flag_id: int, body: ChooseRequest, db: Session = Depends(get_db),
           me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    _run(db, svc.choose_value, cv, me, flag_id, body.choice)
    db.refresh(cv)
    return _detail(cv)


@router.get("/course-versions/{cv_id}/edits.csv")
def edits_csv(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Edit log export (plan 1.12): every change against the uploaded file."""
    import csv
    import io
    import json

    cv = _get_cv(db, me, cv_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["when_utc", "who", "op", "field", "old_value", "new_value", "note"])
    for e in cv.edits:
        w.writerow([e.at.isoformat(), e.edited_by.name, e.op, e.field_path,
                    json.dumps(e.old_value, ensure_ascii=False), json.dumps(e.new_value, ensure_ascii=False),
                    e.note or ""])
    code = (cv.record.get("course", {}).get("code") or "course").replace(" ", "")
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{code}_v{cv.id}_edit_log.csv"'})


class CarryOverRequest(BaseModel):
    from_version_id: int


@router.post("/course-versions/{cv_id}/carry-over", response_model=VersionDetail)
def carry_over(cv_id: int, body: CarryOverRequest, db: Session = Depends(get_db),
               me: Faculty = Depends(current_faculty)):
    cv = _get_cv(db, me, cv_id)
    _run(db, svc.carry_over, cv, me, body.from_version_id)
    db.refresh(cv)
    return _detail(cv)


@router.get("/team/metrics")
def team_metrics(db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Plan 2.11: approval rate, edit size, rejection reasons, time to review —
    per type, course and prompt version. Team only (TEAM_EMAILS)."""
    from app import metrics

    if me.email.lower() not in {e.lower() for e in get_settings().team_emails}:
        raise HTTPException(403, "The metrics dashboard is for the project team (TEAM_EMAILS).")
    return metrics.compute(db)


@router.get("/audit")
def my_audit(limit: int = 200, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Your own security-relevant actions (sign-ins, uploads, locks, exports, downloads)."""
    from app.models import AuditEvent

    rows = db.scalars(select(AuditEvent).where(AuditEvent.faculty_id == me.id)
                      .order_by(AuditEvent.id.desc()).limit(min(limit, 1000))).all()
    return [{"action": a.action, "detail": a.detail, "at": a.at} for a in rows]
