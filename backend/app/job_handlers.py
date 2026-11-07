"""Job handlers: the slow work behind upload and generation (plan 1.9, 2.7)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .drafts import service as drafts
from .jobs import JobContext, JobFailed, handler
from .models import CourseVersion, Item, Job, SourceFile
from .services import course_versions as registry
from .services.course_versions import WorkflowError


def _fail(e: WorkflowError) -> JobFailed:
    err = JobFailed(str(e), e.status)
    err.detail = e.detail  # type: ignore[attr-defined]
    return err


@handler("extract")
def extract_job(db: Session, job: Job, ctx: JobContext) -> dict:
    sf = db.get(SourceFile, job.payload["source_file_id"])
    if sf is None:
        raise JobFailed("The uploaded file is gone.", 410)
    ctx.progress(5, "Reading the file")
    try:
        cv = registry.build_version(db, ctx.faculty, sf, registry.read_source(sf), progress=ctx.progress)
    except WorkflowError as e:
        raise _fail(e) from e
    except ValueError as e:  # UnsupportedFile
        raise JobFailed(str(e), 415) from e
    db.commit()
    return {"course_version_id": cv.id}


@handler("generate")
def generate_job(db: Session, job: Job, ctx: JobContext) -> dict:
    p = job.payload
    cv = db.get(CourseVersion, p["course_version_id"])
    if cv is None:
        raise JobFailed("The course version is gone.", 410)
    try:
        req = drafts.request_drafts(db, cv, ctx.faculty, p["item_type"], p.get("clo_numbers", []),
                                    p.get("weeks", []), p.get("count", 3), p.get("difficulty"),
                                    p.get("bloom_level"), p.get("notes"), progress=ctx.progress)
    except WorkflowError as e:
        db.commit()  # keep the failed GenerationRequest and the LLM call log for the audit trail
        raise _fail(e) from e
    db.commit()
    ids = list(db.scalars(select(Item.id).where(Item.request_id == req.id).order_by(Item.id)))
    return {"request_id": req.id, "item_ids": ids}


@handler("regenerate")
def regenerate_job(db: Session, job: Job, ctx: JobContext) -> dict:
    item = db.get(Item, job.payload["item_id"])
    if item is None:
        raise JobFailed("The item is gone.", 410)
    try:
        req = drafts.regenerate(db, item, ctx.faculty, job.payload.get("notes"), progress=ctx.progress)
    except WorkflowError as e:
        db.rollback()
        raise _fail(e) from e
    db.commit()
    ids = list(db.scalars(select(Item.id).where(Item.request_id == req.id).order_by(Item.id)))
    return {"item_id": item.id, "item_ids": ids}


@handler("index_material")
def index_material_job(db: Session, job: Job, ctx: JobContext) -> dict:
    from .materials.service import index_material
    from .models import Material

    m = db.get(Material, job.payload["material_id"])
    if m is None:
        raise JobFailed("The material is gone.", 410)
    index_material(db, m, progress=ctx.progress)
    db.commit()
    return {"material_id": m.id, "status": m.status, "chunks": m.chunk_count, "error": m.error}


@handler("bank_import")
def bank_import_job(db: Session, job: Job, ctx: JobContext) -> dict:
    """Plan 3.7: questions -> suggested items, tagged locally, checked, de-duplicated."""
    from .builder import bank_import as bi
    from .drafts import quality
    from .drafts.service import as_draft, course_context
    from .extraction.schema import ExtractedSyllabus
    from .models import BankImport, ItemRevision

    cv = db.get(CourseVersion, job.payload["course_version_id"])
    sf = db.get(SourceFile, job.payload["source_file_id"])
    if cv is None or sf is None:
        raise JobFailed("The course version or file is gone.", 410)
    ctx.progress(10, "Reading questions")
    try:
        questions = bi.parse(sf.filename, registry.read_source(sf))
    except Exception as e:
        raise JobFailed(f"Couldn't read questions from the file: {e}", 422) from e
    if not questions:
        raise JobFailed("No numbered questions found (expected '1. …' with optional 'A. …' options and "
                        "'Answer: B' lines, or a QTI package).", 422)
    rec = ExtractedSyllabus.model_validate(cv.record)
    tags = bi.tag(questions, rec)
    existing = db.scalars(select(Item).where(Item.course_version_id == cv.id, Item.status != "rejected")).all()
    others = [(i.id, as_draft(i)) for i in existing]
    cctx = course_context(cv)
    created, dups = [], 0
    for n, (q, t) in enumerate(zip(questions, tags), 1):
        ctx.progress(20 + int(75 * n / len(questions)), f"Checking question {n} of {len(questions)}")
        typ, body, key, fb = bi.to_item_parts(q)
        it = Item(course_version_id=cv.id, type=typ, status="suggested", clo_ids=t["clo_numbers"],
                  week_no=t["week_no"], bloom_level=t["bloom_level"], difficulty=t["difficulty"], body_json=body,
                  answer_key_json=key, feedback_prompts_json=fb, grounded=False, source_chunk_ids=[],
                  model="import", prompt_version=f"import:{sf.filename}")
        db.add(it)
        db.flush()
        it.revisions.append(ItemRevision(body_json=body, answer_key_json=key, feedback_prompts_json=fb,
                                         tags_json={k: t[k] for k in ("clo_numbers", "week_no", "bloom_level",
                                                                       "difficulty")}, source="model"))
        checks = quality.run_all(as_draft(it), cctx, others, llm=None)  # no model reads imported exam items
        for c in checks:
            it.scores.append(quality_score(c))
        if any(c.check == "duplicate" and c.outcome == "warn" for c in checks):
            dups += 1
        others.append((it.id, as_draft(it)))
        created.append(it.id)
    db.add(BankImport(course_version_id=cv.id, file_id=sf.id, items_created=len(created), duplicates=dups,
                      by_id=ctx.faculty.id))
    db.commit()
    return {"item_ids": created, "duplicates": dups}


def quality_score(c):
    from .models import QualityScore

    return QualityScore(check=c.check, outcome=c.outcome, score=c.score, detail=c.detail)


@handler("solvability")
def solvability_job(db: Session, job: Job, ctx: JobContext) -> dict:
    from .builder import solvability as sv
    from .llm.factory import get_gateway
    from .models import SolvabilityCheck

    it = db.get(Item, job.payload["item_id"])
    if it is None:
        raise JobFailed("The item is gone.", 410)
    ctx.progress(20, "Asking the model to solve it unaided")
    llm = get_gateway(db, faculty_id=ctx.faculty.id, course_version_id=it.course_version_id)
    res = sv.check(it, llm)
    row = SolvabilityCheck(item_id=it.id, model=f"{llm.provider.name}:{llm.provider.model}", verdict=res["verdict"],
                           detail=res["detail"], suggestions=sv.SUGGESTIONS if res["verdict"] in {"trivial", "partly"}
                           else [])
    db.add(row)
    db.commit()
    return {"verdict": row.verdict, "detail": row.detail}


@handler("grade")
def grade_job(db: Session, job: Job, ctx: JobContext) -> dict:
    """Phase 4 suggestions for one form and section (plan 4.5-4.9)."""
    from .grading import service as grading
    from .llm.factory import get_gateway
    from .models import AssessmentForm, Section

    try:
        grading.require_enabled()
    except WorkflowError as e:
        raise _fail(e) from e
    form = db.get(AssessmentForm, job.payload["form_id"])
    section = db.get(Section, job.payload["section_id"])
    if form is None or section is None:
        raise JobFailed("The form or section is gone.", 410)
    llm = get_gateway(db, faculty_id=ctx.faculty.id, course_version_id=form.course_version_id)
    out = grading.score(db, form, section, llm, progress=ctx.progress, rescore=bool(job.payload.get("rescore")))
    from .audit import record

    # Gate 4 audit trail: how many anonymised answers went to which model, and how many the guard stopped.
    record(db, ctx.faculty, "grading_run", {"form_id": form.id, "section_id": section.id,
                                            "model": f"{llm.provider.name}:{getattr(llm.provider, 'model', '')}", **out})
    db.commit()
    return out


@handler("create_quiz")
def create_quiz_job(db: Session, job: Job, ctx: JobContext) -> dict:
    """One button: write every kind of question the teacher asked for and put
    them in a paper, ready for review (round 2, section 4)."""
    from .builder import quiz

    p = job.payload
    cv = db.get(CourseVersion, p["course_version_id"])
    if cv is None:
        raise JobFailed("The course is gone.", 410)
    try:
        mix = quiz.parse_mix(p.get("mix", []))
        form = quiz.create(db, cv, ctx.faculty, assessment_name=p.get("assessment_name"), mix=mix,
                           clo_numbers=p.get("clo_numbers", []), weeks=p.get("weeks", []),
                           difficulty=p.get("difficulty"), notes=p.get("notes"), progress=ctx.progress)
    except WorkflowError as e:
        db.commit()  # keep the questions already written, and the call log
        raise _fail(e) from e
    db.commit()
    return {"form_id": form.id, "item_ids": [fi.item_id for fi in form.items]}
