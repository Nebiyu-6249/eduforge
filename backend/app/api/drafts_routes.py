from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.api.schemas import JobOut, job_out
from app.audit import record
from app.auth import current_faculty
from app.db import get_db
from app.drafts import export as exporter
from app.drafts import quality
from app.drafts import service as svc
from app.drafts.bloom import LEVELS, clo_level, is_skills_clo
from app.drafts.schemas import ITEM_MODELS, ITEM_TYPES, QUESTION_TYPES, TYPE_LABELS, ItemType
from app.extraction.schema import ExtractedSyllabus
from app.models import CourseVersion, Export, Faculty, Item
from app.services.course_versions import WorkflowError

router = APIRouter(prefix="/api")


class GenerateIn(BaseModel):
    item_type: ItemType
    clo_numbers: list[int] = Field(default_factory=list)
    weeks: list[int] = Field(default_factory=list)
    count: int = 3
    difficulty: Literal["easy", "medium", "hard"] | None = None
    bloom_level: str | None = None
    notes: str | None = None


class EditIn(BaseModel):
    tags: dict[str, Any] | None = None
    body: dict[str, Any] | None = None
    answer_key: dict[str, Any] | None = None
    feedback: dict[str, Any] | None = None
    notes: str | None = None


class ActionIn(BaseModel):
    action: Literal["approve", "reject", "reopen", "regenerate"]
    notes: str | None = None


class ExportIn(BaseModel):
    format: Literal["docx", "pdf"] = "docx"
    item_ids: list[int] | None = None  # default: every approved item
    # The question paper and the answer key are separate files: the paper never
    # carries answers or CLO/week/Bloom tags.
    part: Literal["paper", "key"] = "paper"


class ScoreOut(BaseModel):
    check: str
    label: str
    outcome: str
    score: float | None
    detail: str
    hard: bool


class UsedIn(BaseModel):
    """A quiz or exam this question is on, so the bank can say which is which."""

    form_id: int
    assessment_name: str
    version_label: str
    status: str


class ItemOut(BaseModel):
    id: int
    course_version_id: int
    type: str
    type_label: str
    status: str
    clo_numbers: list[int]
    week_no: int | None
    bloom_level: str | None
    difficulty: str | None
    body: dict
    answer_key: dict | None
    feedback: dict | None
    grounded: bool
    model: str
    prompt_version: str
    parent_item_id: int | None
    created_at: datetime
    updated_at: datetime
    approved_by: str | None
    approved_at: datetime | None
    scores: list[ScoreOut]
    can_approve: bool
    revision_count: int
    events: list[dict]
    shared: bool = False  # in the course's shared bank (plan 3.10)
    used_in: list[UsedIn] = []  # the quizzes and exams it is on; empty = "Not in a quiz yet"


def _cv(db: Session, me: Faculty, cv_id: int) -> CourseVersion:
    cv = db.get(CourseVersion, cv_id)
    if cv is None or cv.faculty_id != me.id:
        raise HTTPException(404, "Course version not found.")
    return cv


def _item(db: Session, me: Faculty, item_id: int) -> Item:
    it = db.get(Item, item_id)
    if it is None or it.course_version.faculty_id != me.id:
        raise HTTPException(404, "Item not found.")
    return it


def _out(it: Item) -> ItemOut:
    hard_fail = any(s.check in quality.HARD_CHECKS and s.outcome == "fail" for s in it.scores)
    return ItemOut(
        id=it.id, course_version_id=it.course_version_id, type=it.type, type_label=TYPE_LABELS[it.type],
        status=it.status, clo_numbers=it.clo_ids, week_no=it.week_no, bloom_level=it.bloom_level,
        difficulty=it.difficulty, body=it.body_json, answer_key=it.answer_key_json, feedback=it.feedback_prompts_json,
        grounded=it.grounded, model=it.model, prompt_version=it.prompt_version, parent_item_id=it.parent_item_id,
        created_at=it.created_at, updated_at=it.updated_at,
        approved_by=it.approved_by.name if it.approved_by else None, approved_at=it.approved_at,
        scores=[ScoreOut(check=s.check, label=quality.CHECK_LABELS.get(s.check, s.check), outcome=s.outcome,
                         score=s.score, detail=s.detail, hard=s.check in quality.HARD_CHECKS) for s in it.scores],
        can_approve=it.status in svc.REVIEWABLE and not hard_fail,
        revision_count=len(it.revisions),
        shared=_is_shared(it),
        used_in=_used_in(it),
        events=[{"action": e.action, "notes": e.notes, "by": e.by.name, "at": e.at} for e in it.events],
    )


def _used_in(it: Item) -> list[UsedIn]:
    from sqlalchemy.orm import object_session

    from app.models import AssessmentForm, FormItem

    db = object_session(it)
    if db is None:
        return []
    rows = db.execute(select(AssessmentForm).join(FormItem, FormItem.form_id == AssessmentForm.id)
                      .where(FormItem.item_id == it.id).order_by(AssessmentForm.id)).scalars().all()
    return [UsedIn(form_id=f.id, assessment_name=f.assessment_name, version_label=f.version_label, status=f.status)
            for f in rows]


def _is_shared(it: Item) -> bool:
    from sqlalchemy.orm import object_session

    from app.models import SharedBankItem

    db = object_session(it)
    return bool(db and db.scalar(select(SharedBankItem.id).where(SharedBankItem.item_id == it.id)))


def _run(db: Session, fn, *args, keep_on_error: bool = False):
    try:
        out = fn(db, *args)
        db.commit()
        return out
    except WorkflowError as e:
        if keep_on_error:
            db.commit()  # keep the failed request and the LLM call log for the audit trail
        else:
            db.rollback()
        raise HTTPException(e.status, {"message": str(e), "items": e.detail} if e.detail else str(e)) from e


# --------------------------------------------------------------------------- #

@router.get("/draft-types")
def draft_types():
    return [{"type": t, "label": TYPE_LABELS[t], "question": t in QUESTION_TYPES,
             "has_answer_key": "answer_key" in ITEM_MODELS[t].model_fields,
             # The highest Bloom level this type can evidence (None = uncapped).
             "max_bloom": svc.MAX_BLOOM.get(t)} for t in ITEM_TYPES]


@router.get("/course-versions/{cv_id}/draft-context")
def draft_context(cv_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """CLOs (with Bloom level and skills flag) and weeks, for the request form."""
    cv = _cv(db, me, cv_id)
    rec = ExtractedSyllabus.model_validate(cv.record)
    return {
        "status": cv.status,
        "can_generate": cv.status == "locked",
        "clos": [{"number": c.number, "text": c.text, "bloom_level": clo_level(c.text), "skills": is_skills_clo(c.text)}
                 for c in rec.clos],
        "weeks": [{"week_no": w.week_no, "topics": w.topics} for w in rec.weekly],
        "bloom_levels": LEVELS,
    }


@router.post("/course-versions/{cv_id}/drafts", response_model=JobOut, status_code=202)
def generate(cv_id: int, body: GenerateIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Validate now (bad requests fail at once), then draft + check as a job
    (plan 2.7). The job result lists the new item_ids."""
    cv = _cv(db, me, cv_id)
    try:
        svc.check_request(cv, me, body.item_type, body.clo_numbers, body.weeks, body.count, body.difficulty,
                          body.bloom_level)
    except WorkflowError as e:
        raise HTTPException(e.status, str(e)) from e
    label = TYPE_LABELS.get(body.item_type, body.item_type).lower()
    job = jobs.enqueue(db, "generate", me, {"course_version_id": cv.id, **body.model_dump()},
                       title=f"{body.count} {label}{'' if body.count == 1 else 's'}",
                       course_version_id=cv.id, link=f"/v/{cv.id}/questions", size=body.count)
    return job_out(job)


@router.get("/course-versions/{cv_id}/drafts", response_model=list[ItemOut])
def list_items(cv_id: int, status: str | None = None, item_type: str | None = None, db: Session = Depends(get_db),
               me: Faculty = Depends(current_faculty)):
    _cv(db, me, cv_id)
    q = select(Item).where(Item.course_version_id == cv_id).order_by(Item.id.desc())
    if status:
        q = q.where(Item.status == status)
    if item_type:
        q = q.where(Item.type == item_type)
    return [_out(i) for i in db.scalars(q).all()]


@router.get("/drafts/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    return _out(_item(db, me, item_id))


@router.patch("/drafts/{item_id}", response_model=ItemOut)
def edit_item(item_id: int, body: EditIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    it = _item(db, me, item_id)
    _run(db, svc.edit, it, me, body.tags, body.body, body.answer_key, body.feedback, body.notes)
    db.refresh(it)
    return _out(it)


@router.post("/drafts/{item_id}/action")
def item_action(item_id: int, body: ActionIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    it = _item(db, me, item_id)
    if body.action == "regenerate":
        try:
            svc.check_regenerate(it, me, body.notes)
        except WorkflowError as e:
            raise HTTPException(e.status, str(e)) from e
        job = jobs.enqueue(db, "regenerate", me, {"item_id": it.id, "notes": body.notes},
                           title=f"Rewriting question #{it.id}",
                           course_version_id=it.course_version_id,
                           link=f"/v/{it.course_version_id}/questions", size=1)
        db.refresh(it)
        return {"item": _out(it), "replacements": [], "job": job_out(job)}
    fn = {"approve": svc.approve, "reject": svc.reject, "reopen": svc.reopen}[body.action]
    _run(db, fn, it, me, body.notes)
    db.refresh(it)
    return {"item": _out(it), "replacements": [], "job": None}


@router.post("/drafts/{item_id}/recheck", response_model=ItemOut)
def recheck(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    it = _item(db, me, item_id)
    _run(db, svc.recheck, it, me)
    db.refresh(it)
    return _out(it)


class SourceOut(BaseModel):
    chunk_id: int
    material_id: int
    material_title: str
    kind: str
    week_no: int | None
    location: str
    excerpt: str


class GroundingOut(BaseModel):
    grounded: bool
    note: str
    sources: list[SourceOut]


@router.get("/drafts/{item_id}/grounding", response_model=GroundingOut)
def item_grounding(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """Which pieces of the faculty member's own material a draft was built from,
    with the matching excerpt — or, when it is ungrounded, why (plan 2.7)."""
    from app.models import Chunk, Material

    it = _item(db, me, item_id)
    rows = []
    if it.source_chunk_ids:
        q = (select(Chunk, Material).join(Material, Chunk.material_id == Material.id)
             .where(Chunk.id.in_(it.source_chunk_ids)))
        order = {cid: i for i, cid in enumerate(it.source_chunk_ids)}
        for c, mat in sorted(db.execute(q).all(), key=lambda r: order.get(r[0].id, 99)):
            rows.append(SourceOut(chunk_id=c.id, material_id=mat.id, material_title=mat.title, kind=mat.kind,
                                  week_no=c.week_no, location=c.location, excerpt=c.text[:1200]))
    note = (it.request.grounding_note if it.request and it.request.grounding_note else None)
    if not note:
        note = ("Grounded in the course material listed below." if rows else
                "No course material was retrieved for this request, so the draft came from the syllabus alone.")
    return GroundingOut(grounded=it.grounded, note=note, sources=rows)


@router.get("/drafts/{item_id}/revisions")
def revisions(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    it = _item(db, me, item_id)
    return [{"id": r.id, "source": r.source, "by": r.edited_by.name if r.edited_by else it.model, "at": r.at,
             "tags": r.tags_json, "body": r.body_json, "answer_key": r.answer_key_json,
             "feedback": r.feedback_prompts_json} for r in it.revisions]


@router.post("/course-versions/{cv_id}/export")
def export(cv_id: int, body: ExportIn, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    cv = _cv(db, me, cv_id)
    q = select(Item).where(Item.course_version_id == cv_id)
    if body.item_ids:
        q = q.where(Item.id.in_(body.item_ids))
    else:
        q = q.where(Item.status == "approved")
    items = db.scalars(q.order_by(Item.id)).all()
    if body.item_ids and len(items) != len(set(body.item_ids)):
        raise HTTPException(404, "Some of the chosen questions are not in this course.")
    not_ok = [i.id for i in items if i.status != "approved"]
    if not_ok:
        raise HTTPException(409, "Only approved questions can be downloaded. Approve these first: "
                                 f"{', '.join(f'#{n}' for n in not_ok)}.")
    if not items:
        raise HTTPException(409, "There are no approved questions to download yet.")
    data, filename, mime = exporter.render(ExtractedSyllabus.model_validate(cv.record), list(items), body.format,
                                           body.part)
    is_key = body.part == exporter.PART_KEY
    db.add(Export(course_version_id=cv.id, format=body.format, item_ids=[i.id for i in items],
                  include_answer_key=is_key, by_id=me.id))
    record(db, me, "export", {"course_version_id": cv.id, "format": body.format, "items": len(items),
                              "part": body.part})
    db.commit()
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/drafts/{item_id}/figure.png")
def item_figure(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    """The item's figure: a chart drawn from its generated dataset, or its rendered diagram (plan 2.18/2.20)."""
    from app.drafts.rich import DatasetError, figure_png

    it = _item(db, me, item_id)
    try:
        png = figure_png(it.body_json.get("figure"))
    except DatasetError as e:
        raise HTTPException(422, str(e)) from e
    if png is None:
        raise HTTPException(404, "No renderable figure (a diagram renderer may not be installed on the server).")
    return Response(content=png, media_type="image/png")


@router.get("/drafts/{item_id}/dataset.csv")
def item_dataset(item_id: int, db: Session = Depends(get_db), me: Faculty = Depends(current_faculty)):
    from app.drafts.rich import DatasetError, dataset_csv

    it = _item(db, me, item_id)
    try:
        csv = dataset_csv(it.body_json.get("figure"))
    except DatasetError as e:
        raise HTTPException(422, str(e)) from e
    if csv is None:
        raise HTTPException(404, "This item has no dataset.")
    return Response(content=csv, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="item{it.id}_dataset.csv"'})
