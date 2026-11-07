"""Draft Studio + Faculty Review (HANDOFF §6 gate 2, §10).

Generation is allowed only from a LOCKED course version. Every item starts
as 'suggested'; only a named faculty member's approval makes it usable, and
only approved items export. An edit returns an item to review; reject or
'regenerate with notes' creates a new suggestion.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extraction.schema import ExtractedSyllabus
from app.llm.factory import get_gateway
from app.llm.gateway import LLMError, LLMUnavailable
from app.models import CourseVersion, Faculty, GenerationRequest, Item, ItemRevision, QualityScore, ReviewEvent, utcnow
from app.services.course_versions import WorkflowError

from . import bloom, quality
from .prompts import generation_prompt
from .schemas import ITEM_TYPES, QUESTION_TYPES, TYPE_LABELS, batch_model, validate_parts

MAX_COUNT = 10
REVIEWABLE = {"suggested", "under_review", "needs_review"}  # needs_review: its CLO changed (plan 3.8)

# The highest Bloom level an item type can honestly evidence. Picking the right
# option from a list shows recognition and reasoning about given alternatives,
# never the independent judgement of 'evaluate' or the production of 'create';
# the first export of this tool had eight MCQs all tagged 'create'. Types not
# listed here are uncapped.
MAX_BLOOM = {"mcq": "analyze"}


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #

def _rec(cv: CourseVersion) -> ExtractedSyllabus:
    return ExtractedSyllabus.model_validate(cv.record)


def course_context(cv: CourseVersion) -> quality.CourseContext:
    rec = _rec(cv)
    return quality.CourseContext(clos={c.number: c.text for c in rec.clos}, weeks={w.week_no for w in rec.weekly})


def as_draft(item: Item) -> quality.Draft:
    return quality.Draft(type=item.type, tags=_tags(item), body=item.body_json, answer_key=item.answer_key_json,
                         feedback=item.feedback_prompts_json)


def _tags(item: Item) -> dict:
    return {"clo_numbers": item.clo_ids, "week_no": item.week_no, "bloom_level": item.bloom_level,
            "difficulty": item.difficulty}


def _owner(cv: CourseVersion, me: Faculty) -> None:
    if cv.faculty_id != me.id:
        raise WorkflowError("Not your course version.", 404)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #

def _grounding_block(hits) -> str:
    """Retrieved course material for the prompt, each chunk labelled [C<id>] (plan 2.7)."""
    if not hits:
        return ("GROUNDING: No approved course material matched this request, so draw only on the syllabus "
                "context above. These items will be marked 'ungrounded'.\n")
    parts, budget = [], 7000
    for h in hits:
        text = h.chunk.text[:1800]
        if budget - len(text) < 0:
            break
        budget -= len(text)
        parts.append(f"[C{h.chunk.id}] {h.material.title} ({h.material.kind}, {h.chunk.location}):\n{text}")
    return ("GROUNDING MATERIAL (the instructor's own course material; base the items on it where relevant, "
            "keep its terminology and notation, and do not copy past exam questions verbatim):\n"
            + "\n\n".join(parts) + "\n")


def _prompt_vars(rec: ExtractedSyllabus, item_type: str, clos: list[int], weeks: list[int], count: int,
                 difficulty: str, bloom_level: str, avoid: list[str], notes: str | None,
                 grounding: str = "") -> dict:
    targets = set(clos)
    target_weeks = set(weeks)
    clo_lines = []
    for c in rec.clos:
        lvl = bloom.clo_level(c.text)
        clo_lines.append(f"{'* ' if c.number in targets else '  '}CLO {c.number}: {c.text}"
                         f"{f' [Bloom: {lvl}]' if lvl else ''}")
    week_lines = []
    for w in rec.weekly:
        mark = "* " if w.week_no in target_weeks else "  "
        read = f" (readings: {'; '.join(w.readings)})" if w.readings else ""
        week_lines.append(f"{mark}Week {w.week_no}: {'; '.join(w.topics) or '—'}{read}")
    resources = [*rec.resources.textbooks, *rec.resources.other, *rec.resources.web] or ["(none listed)"]
    return dict(
        code=rec.course.code or "", title=rec.course.title or "", term=rec.offering.term or "",
        description=rec.course.description or "(none)",
        clos="\n".join(clo_lines), weeks="\n".join(week_lines) or "(no schedule)",
        resources="\n".join(f"- {r}" for r in resources),
        grounding=grounding or _grounding_block([]),
        count=count, type_label=TYPE_LABELS[item_type],
        target_clos=", ".join(f"CLO {n}" for n in sorted(targets)),
        target_weeks=", ".join(f"week {n}" for n in sorted(target_weeks)) or "any week the CLO covers",
        difficulty=difficulty, bloom=bloom_level,
        avoid=("- Do not repeat or closely paraphrase these existing items:\n"
               + "\n".join(f"  · {a}" for a in avoid) + "\n") if avoid else "",
        notes=f"- Instructor notes: {notes}\n" if notes else "",
    )


def request_drafts(db: Session, cv: CourseVersion, me: Faculty, item_type: str, clo_numbers: list[int],
                   weeks: list[int], count: int, difficulty: str | None, bloom_level: str | None,
                   notes: str | None, *, regenerate_of: Item | None = None,
                   allow_skills_questions: bool = False,
                   progress: Callable[[int, str], None] | None = None) -> GenerationRequest:
    step = progress or (lambda pct, msg: None)
    clos, bloom_level, difficulty = check_request(cv, me, item_type, clo_numbers, weeks, count, difficulty,
                                                  bloom_level, allow_skills_questions=allow_skills_questions)
    rec = _rec(cv)
    return _generate(db, cv, me, rec, item_type, clos, weeks, count, difficulty, bloom_level, notes,
                     regenerate_of, step)


def check_request(cv: CourseVersion, me: Faculty, item_type: str, clo_numbers: list[int], weeks: list[int],
                  count: int, difficulty: str | None, bloom_level: str | None, *,
                  allow_skills_questions: bool = False) -> tuple[list[int], str, str]:
    """Validate a draft request without calling the model, so the API can
    refuse bad requests at once instead of queueing a job that will fail.
    Returns (clos, bloom_level, difficulty) with defaults filled in."""
    _owner(cv, me)
    if cv.status != "locked":
        raise WorkflowError("Drafts are generated only from a locked working version.", 409)
    if item_type not in ITEM_TYPES:
        raise WorkflowError(f"Unknown item type '{item_type}'.", 422)
    if not 1 <= count <= MAX_COUNT:
        raise WorkflowError(f"Ask for 1–{MAX_COUNT} items at a time.", 422)
    rec = _rec(cv)
    known = {c.number: c.text for c in rec.clos}
    clos = sorted(set(clo_numbers)) or sorted(known)
    bad = [n for n in clos if n not in known]
    if bad:
        raise WorkflowError(f"CLO {', '.join(map(str, bad))} isn't in the locked version.", 422)
    week_set = {w.week_no for w in rec.weekly}
    bad_w = [w for w in weeks if w not in week_set]
    if bad_w:
        raise WorkflowError(f"Week {', '.join(map(str, bad_w))} isn't in the schedule.", 422)
    skills = [n for n in clos if bloom.is_skills_clo(known[n])]
    if item_type in QUESTION_TYPES and len(skills) == len(clos) and not allow_skills_questions:
        raise WorkflowError(
            f"CLO {', '.join(map(str, skills))} is a skills outcome (communication, teamwork, ethics …). "
            "Use a rubric, case study or lesson-plan activity for it instead of a question.", 422)
    if bloom_level is None:
        levels = [lv for n in clos if (lv := bloom.clo_level(known[n]))]
        bloom_level = max(levels, key=bloom.LEVELS.index) if levels else "apply"
        cap = MAX_BLOOM.get(item_type)
        if cap and bloom.LEVELS.index(bloom_level) > bloom.LEVELS.index(cap):
            bloom_level = cap  # a CLO above the cap: aim at the level this type can evidence
    if bloom_level not in bloom.LEVELS:
        raise WorkflowError(f"Bloom level must be one of {', '.join(bloom.LEVELS)}.", 422)
    cap = MAX_BLOOM.get(item_type)
    if cap and bloom.LEVELS.index(bloom_level) > bloom.LEVELS.index(cap):
        raise WorkflowError(
            f"A {TYPE_LABELS[item_type].lower()} cannot evidence '{bloom_level}': choosing between given "
            f"options stops at '{cap}'. Ask for '{cap}' or lower here, and use a rubric, case study, worked "
            "problem or lesson-plan activity for the higher level.", 422)
    difficulty = difficulty or "medium"
    if difficulty not in {"easy", "medium", "hard"}:
        raise WorkflowError("Difficulty must be easy, medium or hard.", 422)
    return clos, bloom_level, difficulty


def _generate(db: Session, cv: CourseVersion, me: Faculty, rec: ExtractedSyllabus, item_type: str, clos: list[int],
              weeks: list[int], count: int, difficulty: str, bloom_level: str, notes: str | None,
              regenerate_of: Item | None, step: Callable[[int, str], None]) -> GenerationRequest:
    existing = db.scalars(select(Item).where(Item.course_version_id == cv.id, Item.type == item_type,
                                             Item.status != "rejected")).all()
    # Retrieval (plan 2.3/2.7): the course's own material for these CLOs and weeks.
    from app.materials.service import Retrieval, retrieve_explained

    found = Retrieval([], "This version is not locked to a course yet, so no material could be retrieved.")
    if cv.course_id is not None:
        known = {c.number: c.text for c in rec.clos}
        topics = [t for w in rec.weekly if w.week_no in set(weeks) for t in w.topics]
        query = " ".join([known.get(n, "") for n in clos] + topics)
        found = retrieve_explained(db, cv.course_id, query, weeks=weeks or None, k=5)
    hits = found.hits
    step(10, f"Found {len(hits)} relevant piece(s) of course material" if hits else "No course material matched")
    avoid = [quality.item_text(as_draft(i)).split("\n")[0][:140] for i in existing][-15:]
    if regenerate_of is not None:
        original = quality.item_text(as_draft(regenerate_of))
        notes = (f"The instructor rejected the draft below and wants a replacement. Their notes: "
                 f"{notes or '(none)'}\nRejected draft:\n{original[:1500]}")

    prompt = generation_prompt(item_type)
    req = GenerationRequest(course_version_id=cv.id, item_type=item_type, clo_numbers=clos, weeks=sorted(weeks),
                            count=count, difficulty=difficulty, bloom_level=bloom_level, notes=notes,
                            regenerate_of_item_id=regenerate_of.id if regenerate_of else None,
                            requested_by_id=me.id, prompt_version=f"{prompt.id}@{prompt.version}",
                            grounding_note=found.reason)
    db.add(req)
    db.flush()

    llm = get_gateway(db, faculty_id=me.id, course_version_id=cv.id)
    req.model = f"{llm.provider.name}:{llm.provider.model}"
    step(15, f"Drafting {count} {TYPE_LABELS[item_type].lower()}(s) with the model")
    try:
        batch = llm.json(prompt, batch_model(item_type),
                         **_prompt_vars(rec, item_type, clos, weeks, count, difficulty, bloom_level, avoid, notes,
                                        grounding=_grounding_block(hits)))
    except LLMUnavailable as e:
        req.status, req.error = "failed", str(e)
        db.flush()
        raise WorkflowError("No LLM is configured. Set LLM_PROVIDER (see README) to generate drafts.", 503) from e
    except LLMError as e:
        req.status, req.error = "failed", str(e)[:2000]
        db.flush()
        raise WorkflowError(f"The model call failed: {e}", 502) from e

    ctx = course_context(cv)
    others = [(i.id, as_draft(i)) for i in existing]
    outs = batch.items[:count]  # type: ignore[attr-defined]  # dynamic batch model
    for n, out in enumerate(outs, 1):
        step(40 + int(55 * (n - 1) / max(1, len(outs))), f"Checking draft {n} of {len(outs)}")
        d = out.model_dump(mode="json")
        tags = d["tags"]
        item = Item(course_version_id=cv.id, request_id=req.id, parent_item_id=regenerate_of.id if regenerate_of else None,
                    type=item_type, status="suggested", clo_ids=tags["clo_numbers"], week_no=tags.get("week_no"),
                    bloom_level=tags.get("bloom_level"), difficulty=tags.get("difficulty"), body_json=d["body"],
                    answer_key_json=d.get("answer_key"), feedback_prompts_json=d.get("feedback"),
                    grounded=bool(hits), source_chunk_ids=[h.chunk.id for h in hits],
                    model=req.model, prompt_version=req.prompt_version)
        db.add(item)
        db.flush()
        item.revisions.append(ItemRevision(body_json=item.body_json, answer_key_json=item.answer_key_json,
                                           feedback_prompts_json=item.feedback_prompts_json, tags_json=tags,
                                           source="model"))
        _store_checks(item, quality.run_all(as_draft(item), ctx, others, llm))
        others.append((item.id, as_draft(item)))
    req.status = "done"
    db.flush()
    return req


def _store_checks(item: Item, checks: list[quality.Check]) -> None:
    item.scores.clear()
    for c in checks:
        item.scores.append(QualityScore(check=c.check, outcome=c.outcome, score=c.score, detail=c.detail))


def recheck(db: Session, item: Item, me: Faculty, use_llm: bool = True) -> Item:
    cv = item.course_version
    _owner(cv, me)
    llm = get_gateway(db, faculty_id=me.id, course_version_id=cv.id) if use_llm else None
    others = [(i.id, as_draft(i)) for i in db.scalars(select(Item).where(
        Item.course_version_id == cv.id, Item.id != item.id, Item.status != "rejected")).all()]
    _store_checks(item, quality.run_all(as_draft(item), course_context(cv), others, llm))
    db.flush()
    return item


# --------------------------------------------------------------------------- #
# Review (gate 2)
# --------------------------------------------------------------------------- #

def _event(item: Item, me: Faculty, action: str, notes: str | None) -> None:
    item.events.append(ReviewEvent(action=action, notes=(notes or "").strip() or None, by_id=me.id))


def edit(db: Session, item: Item, me: Faculty, tags: dict | None, body: dict | None, answer_key: dict | None,
         feedback: dict | None, notes: str | None) -> Item:
    _owner(item.course_version, me)
    if item.status == "rejected":
        raise WorkflowError("Rejected items can't be edited; reopen it first.", 409)
    new_tags = {**_tags(item), **(tags or {})}
    new_body = body if body is not None else item.body_json
    new_key = answer_key if answer_key is not None else item.answer_key_json
    new_fb = feedback if feedback is not None else item.feedback_prompts_json
    try:
        validate_parts(item.type, new_tags, new_body, new_key, new_fb)
    except ValidationError as e:
        raise WorkflowError("The edit doesn't fit this item type's structure.", 422,
                            detail=[{"loc": "/" + "/".join(map(str, x["loc"])), "msg": x["msg"]} for x in e.errors()]) from e
    item.clo_ids, item.week_no = new_tags["clo_numbers"], new_tags.get("week_no")
    item.bloom_level, item.difficulty = new_tags.get("bloom_level"), new_tags.get("difficulty")
    item.body_json, item.answer_key_json, item.feedback_prompts_json = new_body, new_key, new_fb
    item.revisions.append(ItemRevision(body_json=new_body, answer_key_json=new_key, feedback_prompts_json=new_fb,
                                       tags_json=new_tags, source="faculty", edited_by_id=me.id))
    # An edit returns the item to review, even if it was approved (§10).
    item.status = "under_review"
    item.approved_by_id = item.approved_at = None
    _event(item, me, "edit", notes)
    recheck(db, item, me)
    return item


def approve(db: Session, item: Item, me: Faculty, notes: str | None) -> Item:
    _owner(item.course_version, me)
    if item.status not in REVIEWABLE:
        raise WorkflowError(f"This item is {item.status}.", 409)
    blockers = [s for s in item.scores if s.check in quality.HARD_CHECKS and s.outcome == "fail"]
    if blockers:
        raise WorkflowError("Fix the failed checks before approving (edit the item).", 409,
                            detail=[{"rule_id": s.check, "message": s.detail} for s in blockers])
    item.status = "approved"
    item.approved_by_id, item.approved_at = me.id, utcnow()
    _event(item, me, "approve", notes)
    db.flush()
    return item


def reject(db: Session, item: Item, me: Faculty, notes: str | None) -> Item:
    _owner(item.course_version, me)
    if item.status == "rejected":
        raise WorkflowError("Already rejected.", 409)
    item.status = "rejected"
    item.approved_by_id = item.approved_at = None
    _event(item, me, "reject", notes)
    db.flush()
    return item


def reopen(db: Session, item: Item, me: Faculty, notes: str | None) -> Item:
    _owner(item.course_version, me)
    if item.status not in {"rejected", "approved"}:
        raise WorkflowError("Only approved or rejected items can be reopened.", 409)
    item.status = "under_review"
    item.approved_by_id = item.approved_at = None
    _event(item, me, "reopen", notes)
    db.flush()
    return item


def check_regenerate(item: Item, me: Faculty, notes: str | None) -> None:
    _owner(item.course_version, me)
    if not (notes and notes.strip()):
        raise WorkflowError("Say what should change so the replacement can address it.", 422)
    if item.course_version.status != "locked":
        raise WorkflowError("This item's course version is no longer the locked working version; "
                            "generate new drafts from the current one.", 409)


def regenerate(db: Session, item: Item, me: Faculty, notes: str | None,
               progress: Callable[[int, str], None] | None = None) -> GenerationRequest:
    """Reject the item and ask for a replacement that takes the faculty's notes into account."""
    check_regenerate(item, me, notes)
    req = request_drafts(db, item.course_version, me, item.type, item.clo_ids,
                         [item.week_no] if item.week_no else [], 1, item.difficulty, item.bloom_level, notes,
                         regenerate_of=item, allow_skills_questions=True, progress=progress)
    if item.status != "rejected":
        item.status = "rejected"
        item.approved_by_id = item.approved_at = None
    _event(item, me, "regenerate", notes)
    db.flush()
    return req
