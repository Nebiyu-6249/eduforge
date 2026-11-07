"""Course Registry workflow (HANDOFF §6, gate 1):

upload -> extract + validate -> faculty corrects (logged) and settles flags
-> lock one working version per course + term.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from app import storage
from app.extraction.normalize import canonical_name, category_of, normalise_term, parse_meetings
from app.extraction.pipeline import DOCX_MIME, PDF_MIME, extract, sniff
from app.extraction.schema import ExtractedSyllabus
from app.llm.factory import get_gateway
from app.models import (
    CLO,
    PLO,
    AbetOutcomeAddressed,
    Assessment,
    AssessmentCLO,
    CLOPLOMap,
    Course,
    CourseVersion,
    Faculty,
    FieldEdit,
    Program,
    Resource,
    SourceFile,
    ValidationFlag,
    Week,
    utcnow,
)
from app.validation.matching import match_all
from app.validation.rules import Flag, validate

from . import jsonptr

EDITABLE = {"extracted", "in_review"}
BLOCKING = {"error", "warning"}
# Edits under these paths change what V11 reads, so V11 is re-run.
_V11_PATHS = ("/course/description", "/course/additional_info", "/course/title", "/course/code", "/clos", "/weekly")


class WorkflowError(Exception):
    def __init__(self, message: str, status: int = 409, detail: object | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #

def store_file(db: Session, me: Faculty, filename: str, data: bytes) -> SourceFile:
    kind = sniff(filename, data)
    sha = hashlib.sha256(data).hexdigest()
    key = f"{sha[:2]}/{sha}.{kind}"
    storage.put(db, key, data)
    sf = SourceFile(filename=filename, mime=PDF_MIME if kind == "pdf" else DOCX_MIME, sha256=sha,
                    size_bytes=len(data), storage_key=key, uploaded_by_id=me.id)
    db.add(sf)
    db.flush()
    return sf


def create_from_upload(db: Session, me: Faculty, filename: str, data: bytes) -> CourseVersion:
    """Synchronous path (scripts and tests): store, extract, validate."""
    sf = store_file(db, me, filename, data)
    return build_version(db, me, sf, data)


def read_source(sf: SourceFile) -> bytes:
    data = storage.get(object_session(sf), sf.storage_key)
    if data is None:
        raise FileNotFoundError(f"The stored file {sf.filename} is missing.")
    return data


def build_version(db: Session, me: Faculty, sf: SourceFile, data: bytes,
                  progress: Callable[[int, str], None] | None = None) -> CourseVersion:
    """Extract a stored file into a new CourseVersion and validate it (the
    'extract' job, plan 1.8/1.9)."""
    step = progress or (lambda pct, msg: None)
    step(10, "Reading the file")
    # The model is used only for sections the parser couldn't read (logged per call).
    rec = extract(sf.filename, data, llm=get_gateway(db, faculty_id=me.id))
    step(70, "Checking the syllabus (V1–V12)")
    cv = CourseVersion(faculty_id=me.id, source_file_id=sf.id, status="extracted",
                       record=rec.model_dump(mode="json"), origin="upload")
    db.add(cv)
    db.flush()
    revalidate(db, cv, me, run_v11=True)
    return cv


# --------------------------------------------------------------------------- #
# Validation + flag reconciliation
# --------------------------------------------------------------------------- #

def revalidate(db: Session, cv: CourseVersion, me: Faculty | None, run_v11: bool) -> list[ValidationFlag]:
    """Re-run the validator and reconcile with stored flags by fingerprint:
    resolutions survive while a flag is still raised; flags that are no
    longer raised become 'cleared'; new ones are added as 'open'."""
    rec = ExtractedSyllabus.model_validate(cv.record)
    llm = get_gateway(db, faculty_id=me.id if me else None, course_version_id=cv.id) if run_v11 else None
    new = {f.fingerprint: f for f in validate(rec, llm, run_v11=run_v11)}
    existing = {f.fingerprint: f for f in cv.flags}
    for fp, f in new.items():
        row = existing.get(fp)
        if row is None:
            cv.flags.append(_flag_row(f))
            continue
        row.message, row.severity, row.evidence_refs = f.message, f.severity, f.evidence
        row.choices = f.choices or None
        if row.status == "cleared":
            row.status, row.resolution, row.resolution_note = "open", None, None
            row.resolved_by_id = row.resolved_at = None
    for fp, row in existing.items():
        if fp in new or row.status == "cleared":
            continue
        if not run_v11 and row.rule_id == "V11":
            continue  # V11 wasn't re-run; keep it as is
        row.status = "cleared"
        if row.resolution is None:
            row.resolution = "corrected"
            row.resolution_note = "No longer raised after an edit."
            row.resolved_by_id = me.id if me else None
            row.resolved_at = utcnow()
    db.flush()
    return cv.flags


def _flag_row(f: Flag) -> ValidationFlag:
    return ValidationFlag(rule_id=f.rule_id, severity=f.severity, message=f.message, fingerprint=f.fingerprint,
                          evidence_refs=f.evidence, choices=f.choices or None, status="open")


def blocking_flags(cv: CourseVersion) -> list[ValidationFlag]:
    return [f for f in cv.flags if f.status == "open" and f.severity in BLOCKING]


# --------------------------------------------------------------------------- #
# Edits (logged, not approved — D5)
# --------------------------------------------------------------------------- #

def _require_owner(cv: CourseVersion, me: Faculty) -> None:
    if cv.faculty_id != me.id:
        raise WorkflowError("Not your course version.", 404)


def _require_editable(cv: CourseVersion) -> None:
    if cv.status not in EDITABLE:
        raise WorkflowError(f"This version is {cv.status}; create a new version to change it.", 409)


def apply_edits(db: Session, cv: CourseVersion, me: Faculty, ops: list[dict], note: str | None) -> CourseVersion:
    _require_owner(cv, me)
    _require_editable(cv)
    if not ops:
        raise WorkflowError("No edits given.", 422)
    doc = cv.record
    log: list[FieldEdit] = []
    touched_v11 = False
    for op in ops:
        path, kind = op.get("path", ""), op.get("op", "replace")
        if path.startswith(("/schema_version", "/notes")):
            raise WorkflowError(f"'{path}' can't be edited.", 422)
        try:
            doc, old = jsonptr.apply(doc, kind, path, op.get("value"))
        except jsonptr.PatchError as e:
            raise WorkflowError(str(e), 422) from e
        log.append(FieldEdit(op=kind, field_path=path, old_value=old, new_value=op.get("value"),
                             note=note, edited_by_id=me.id))
        touched_v11 = touched_v11 or path.startswith(_V11_PATHS)
        # Derived fields follow their raw text.
        if path == "/offering/term_raw":
            derived = normalise_term(op.get("value"))
            old_t = doc["offering"].get("term")
            if derived and derived != old_t:
                doc["offering"]["term"] = derived
                log.append(FieldEdit(op="derive", field_path="/offering/term", old_value=old_t, new_value=derived,
                                     note="Derived from term_raw", edited_by_id=me.id))
        if path == "/offering/class_timing_raw":
            old_m = doc["offering"].get("meetings")
            new_m = [m.model_dump() for m in parse_meetings(op.get("value"))]
            doc["offering"]["meetings"] = new_m
            log.append(FieldEdit(op="derive", field_path="/offering/meetings", old_value=old_m, new_value=new_m,
                                 note="Derived from class_timing_raw", edited_by_id=me.id))
    try:
        rec = ExtractedSyllabus.model_validate(doc)
    except ValidationError as e:
        raise WorkflowError("The edit doesn't fit the syllabus schema.", 422,
                            detail=[{"loc": "/" + "/".join(map(str, err["loc"])), "msg": err["msg"]}
                                    for err in e.errors()]) from e
    cv.record = rec.model_dump(mode="json")
    cv.edits.extend(log)
    if cv.status == "extracted":
        cv.status = "in_review"
    revalidate(db, cv, me, run_v11=touched_v11)
    return cv


def resolve_flag(db: Session, cv: CourseVersion, me: Faculty, flag_id: int, action: str, note: str | None) -> ValidationFlag:
    _require_owner(cv, me)
    _require_editable(cv)
    flag = next((f for f in cv.flags if f.id == flag_id), None)
    if flag is None:
        raise WorkflowError("Flag not found.", 404)
    if action == "accept":
        # Plan 1.13: dismissing takes an optional note (any reason is kept on the flag).
        flag.status, flag.resolution = "resolved", "accepted"
    elif action == "reopen":
        if flag.status == "cleared":
            raise WorkflowError("This flag is no longer raised.", 409)
        flag.status, flag.resolution = "open", None
    else:
        raise WorkflowError(f"Unknown action '{action}'.", 422)
    flag.resolution_note = note.strip() if note else None
    flag.resolved_by_id = me.id if action == "accept" else None
    flag.resolved_at = utcnow() if action == "accept" else None
    if cv.status == "extracted":
        cv.status = "in_review"
    db.flush()
    return flag


# --------------------------------------------------------------------------- #
# Lock (gate 1)
# --------------------------------------------------------------------------- #

def lock(db: Session, cv: CourseVersion, me: Faculty) -> CourseVersion:
    _require_owner(cv, me)
    _require_editable(cv)
    blockers = blocking_flags(cv)
    if blockers:
        raise WorkflowError(f"{len(blockers)} flag(s) still need settling before this version can be locked.", 409,
                            detail=[{"id": f.id, "rule_id": f.rule_id, "message": f.message} for f in blockers])
    rec = ExtractedSyllabus.model_validate(cv.record)
    if not rec.course.code or not rec.offering.term:
        raise WorkflowError("Course code and term are needed to lock a working version.", 422)
    if not rec.clos:
        raise WorkflowError("A working version needs at least one CLO.", 422)

    course = db.scalar(select(Course).where(Course.code == rec.course.code))
    if course is None:
        course = Course(code=rec.course.code)
        db.add(course)
    course.title = rec.course.title
    course.credit_hours = rec.course.credit_hours
    course.description = rec.course.description
    course.prerequisites = rec.course.prerequisites
    db.flush()

    # One locked working version per course + term (HANDOFF §13.B: current rule).
    current = db.scalars(select(CourseVersion).where(
        CourseVersion.course_id == course.id, CourseVersion.term == rec.offering.term,
        CourseVersion.status == "locked")).all()
    for other in current:
        if other.faculty_id != me.id:
            raise WorkflowError(
                f"{course.code} {rec.offering.term} already has a working version locked by another faculty member. "
                "Who locks when two instructors share a course and term is still an open team decision.", 409)
    for other in current:
        other.status = "superseded"

    prev_no = db.scalar(select(func.max(CourseVersion.version_no)).where(
        CourseVersion.course_id == course.id, CourseVersion.term == rec.offering.term)) or 0
    cv.course_id = course.id
    cv.term = rec.offering.term
    cv.version_no = prev_no + 1
    cv.status = "locked"
    cv.locked_at = utcnow()
    cv.locked_by_id = me.id
    _materialise(db, cv, rec)
    db.flush()
    # Plan 3.8: compare with the previous locked version; items tied to changed CLOs need review.
    from app.builder.term_diff import on_lock

    on_lock(db, cv, me)
    return cv


def _materialise(db: Session, cv: CourseVersion, rec: ExtractedSyllabus) -> None:
    clo_ids: dict[int, int] = {}
    for c in rec.clos:
        row = CLO(course_version_id=cv.id, number=c.number, text=c.text)
        db.add(row)
        db.flush()
        clo_ids[c.number] = row.id

    for p in rec.programs:
        prog = db.scalar(select(Program).where(Program.code_or_name == p.name))
        if prog is None:
            prog = Program(code_or_name=p.name)
            db.add(prog)
            db.flush()
        plo_ids: dict[int, int] = {}
        for plo in p.plos:
            plo_row = PLO(course_version_id=cv.id, program_id=prog.id, number=plo.number, text=plo.text)
            db.add(plo_row)
            db.flush()
            plo_ids[plo.number] = plo_row.id
        for mapping in p.clo_plo:
            if mapping.clo in clo_ids and mapping.plo in plo_ids:
                db.add(CLOPLOMap(clo_id=clo_ids[mapping.clo], plo_id=plo_ids[mapping.plo], strength=mapping.strength))
        for n in p.abet_addressed:
            db.add(AbetOutcomeAddressed(course_version_id=cv.id, program_id=prog.id, outcome_no=n))

    for wk in rec.weekly:
        db.add(Week(course_version_id=cv.id, week_no=wk.week_no, topics=wk.topics, readings=wk.readings,
                    clo_ids_listed=[clo_ids[n] for n in wk.clo_numbers if n in clo_ids]))

    m = match_all(rec)
    sched_to_weight: dict[tuple[int, int], int] = {}
    for wi, match in m.weight_to_sched.items():
        for ref in match.sched:
            sched_to_weight.setdefault(ref, wi)
    matrix_by_key = {canonical_name(me.assessment): me.clo_numbers for me in rec.clo_matrix}

    def add_assessment(**kw) -> Assessment:
        a = Assessment(course_version_id=cv.id, **kw)
        db.add(a)
        db.flush()
        return a

    def link_clos(a: Assessment, clos: list[int], source: str) -> None:
        for n in sorted(set(clos)):
            if n in clo_ids:
                db.add(AssessmentCLO(assessment_id=a.id, clo_id=clo_ids[n], source=source))

    used_weights: set[int] = set()
    for wi, ai, s in rec.scheduled_assessments():
        w_idx = sched_to_weight.get((wi, ai))
        went = rec.weights[w_idx] if w_idx is not None else None
        if w_idx is not None:
            used_weights.add(w_idx)
        a = add_assessment(name=s.name, type=category_of(s.name), weight_pct=s.weight_pct,
                           weight_table_name=went.name if went else None,
                           weight_table_pct=went.weight_pct if went else None,
                           week=s.due_week or rec.weekly[wi].week_no, due_date=s.due_date, due_text_raw=s.due_text_raw)
        link_clos(a, rec.weekly[wi].clo_numbers, "weekly_schedule")
        mclos = matrix_by_key.get(canonical_name(s.name)) or (
            matrix_by_key.get(canonical_name(went.name)) if went else None) or []
        link_clos(a, mclos, "weight_matrix")
    for i, w in enumerate(rec.weights):
        if i in used_weights:
            continue
        a = add_assessment(name=w.name, type=category_of(w.name), weight_pct=w.weight_pct,
                           weight_table_name=w.name, weight_table_pct=w.weight_pct)
        link_clos(a, matrix_by_key.get(canonical_name(w.name), []), "weight_matrix")

    for kind, items in (("textbook", rec.resources.textbooks), ("other", rec.resources.other),
                        ("web", rec.resources.web)):
        for cit in items:
            isbn = _isbn(cit)
            db.add(Resource(course_version_id=cv.id, kind=kind, citation=cit, isbn=isbn))


def _isbn(text: str) -> str | None:
    import re
    m = re.search(r"\b(97[89][-\s]?\d{1,5}[-\s]?\d{1,7}[-\s]?\d{1,7}[-\s]?\d|\d{9}[\dX])\b", text)
    return re.sub(r"[-\s]", "", m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# New versions: revise a locked version; roll over to another term
# --------------------------------------------------------------------------- #

def revise(db: Session, cv: CourseVersion, me: Faculty) -> CourseVersion:
    """Changing a locked working version creates a new version (§7 locking rule).
    Existing drafts keep pointing at the version they came from."""
    _require_owner(cv, me)
    if cv.status not in {"locked", "superseded"}:
        raise WorkflowError("Only a locked version can be revised; edit this one directly.", 409)
    new = CourseVersion(faculty_id=me.id, source_file_id=cv.source_file_id, status="in_review",
                        record=cv.record, origin="revision", parent_version_id=cv.id)
    db.add(new)
    db.flush()
    revalidate(db, new, me, run_v11=False)
    # Carry over the faculty's settlements for flags that are still raised.
    prior = {f.fingerprint: f for f in cv.flags if f.status == "resolved"}
    for f in new.flags:
        p = prior.get(f.fingerprint)
        if p:
            f.status, f.resolution, f.resolution_note = p.status, p.resolution, p.resolution_note
            f.resolved_by_id, f.resolved_at = p.resolved_by_id, p.resolved_at
    # V11 wasn't re-run; copy its rows as they were.
    for f in cv.flags:
        if f.rule_id == "V11" and f.status != "cleared":
            new.flags.append(ValidationFlag(rule_id=f.rule_id, severity=f.severity, message=f.message,
                                            fingerprint=f.fingerprint, evidence_refs=f.evidence_refs,
                                            status=f.status, resolution=f.resolution,
                                            resolution_note=f.resolution_note, resolved_by_id=f.resolved_by_id,
                                            resolved_at=f.resolved_at))
    db.flush()
    return new


def rollover(db: Session, cv: CourseVersion, me: Faculty, term: str) -> CourseVersion:
    """Copy a locked version to another term for review. Dates are cleared
    (they belong to the old calendar) but their raw text is kept."""
    _require_owner(cv, me)
    if cv.status not in {"locked", "superseded"}:
        raise WorkflowError("Roll over from a locked working version.", 409)
    norm = normalise_term(term)
    if not norm:
        raise WorkflowError(f"'{term}' isn't a term like 'Spring 2027'.", 422)
    rec = ExtractedSyllabus.model_validate(cv.record)
    old_term = rec.offering.term
    rec.offering.term = norm
    rec.offering.term_raw = norm
    for w in rec.weekly:
        for a in w.assessments:
            a.due_date = None
    new = CourseVersion(faculty_id=me.id, source_file_id=cv.source_file_id, status="in_review",
                        record=rec.model_dump(mode="json"), origin="rollover", parent_version_id=cv.id)
    db.add(new)
    db.flush()
    new.edits.append(FieldEdit(op="replace", field_path="/offering/term", old_value=old_term, new_value=norm,
                               note=f"Rolled over from version {cv.id}; assessment dates cleared.",
                               edited_by_id=me.id))
    revalidate(db, new, me, run_v11=True)
    return new


# --------------------------------------------------------------------------- #
# Coverage report (CLO–PLO import and coverage, §5)
# --------------------------------------------------------------------------- #

def coverage(cv: CourseVersion) -> dict:
    rec = ExtractedSyllabus.model_validate(cv.record)
    m = match_all(rec)
    matrix_by_key = {canonical_name(me.assessment): set(me.clo_numbers) for me in rec.clo_matrix}

    # Grade weight carried by each CLO, using the weight table + matrix (split evenly
    # across the CLOs an assessment maps to — an approximation, labelled as such).
    clo_weight = {c.number: 0.0 for c in rec.clos}
    clo_assessments: dict[int, list[str]] = {c.number: [] for c in rec.clos}
    for i, w in enumerate(rec.weights):
        clos = matrix_by_key.get(canonical_name(w.name), set())
        if not clos:
            for wi, _ in m.weight_to_sched[i].sched:
                clos |= set(rec.weekly[wi].clo_numbers)
        clos &= set(clo_weight)
        for n in clos:
            clo_assessments[n].append(w.name)
            if w.weight_pct:
                clo_weight[n] += w.weight_pct / len(clos)

    programs = []
    for p in rec.programs:
        grid: dict[int, dict[int, str]] = {c.number: {} for c in rec.clos}
        for link in p.clo_plo:
            grid.setdefault(link.clo, {})[link.plo] = link.strength
        covered = sorted({link.plo for link in p.clo_plo})
        programs.append({
            "name": p.name,
            "plos": [{"number": x.number, "text": x.text, "covered": x.number in covered,
                      "addressed": x.number in p.abet_addressed} for x in p.plos],
            "grid": {str(k): {str(pk): v for pk, v in row.items()} for k, row in grid.items()},
            "uncovered_plos": [x.number for x in p.plos if x.number not in covered],
        })
    return {
        "clos": [{"number": c.number, "text": c.text, "weight_pct": round(clo_weight[c.number], 2),
                  "assessments": clo_assessments[c.number]} for c in rec.clos],
        "weight_note": "Each assessment's weight is split evenly across the CLOs it maps to.",
        "programs": programs,
    }


def choose_value(db: Session, cv: CourseVersion, me: Faculty, flag_id: int, choice: int) -> CourseVersion:
    """Apply one of a flag's 'choose a value' fixes (plan 1.13). It is an ordinary
    logged edit; re-validation then clears the flag if the contradiction is gone."""
    _require_owner(cv, me)
    flag = next((f for f in cv.flags if f.id == flag_id), None)
    if flag is None:
        raise WorkflowError("Flag not found.", 404)
    options = flag.choices or []
    if not 0 <= choice < len(options):
        raise WorkflowError("That choice isn't offered for this flag.", 422)
    picked = options[choice]
    return apply_edits(db, cv, me, picked["ops"], note=f"{flag.rule_id}: {picked['label']}")


# --------------------------------------------------------------------------- #
# Roll-over on upload (plan 1.15)
# --------------------------------------------------------------------------- #

def previous_version(cv: CourseVersion) -> CourseVersion | None:
    """The faculty member's most recent locked (or superseded) version of the same
    course, offered as a starting point when a new syllabus arrives."""
    db = object_session(cv)
    code = (cv.record.get("course") or {}).get("code")
    if db is None or not code:
        return None
    course = db.scalar(select(Course).where(Course.code == code))
    if course is None:
        return None
    return db.scalar(select(CourseVersion).where(
        CourseVersion.course_id == course.id, CourseVersion.faculty_id == cv.faculty_id,
        CourseVersion.status.in_(("locked", "superseded")), CourseVersion.id != cv.id,
    ).order_by(CourseVersion.locked_at.desc()).limit(1))


def carry_over_matches(cv: CourseVersion, src: CourseVersion) -> list[tuple[ValidationFlag, ValidationFlag]]:
    settled = {f.fingerprint: f for f in src.flags if f.status == "resolved"}
    return [(f, settled[f.fingerprint]) for f in cv.flags if f.status == "open" and f.fingerprint in settled]


def carry_over(db: Session, cv: CourseVersion, me: Faculty, from_id: int) -> int:
    """Settle this version's open flags the way they were settled in an earlier
    version of the course (same rule and same subject). Returns how many."""
    _require_owner(cv, me)
    _require_editable(cv)
    src = db.get(CourseVersion, from_id)
    if src is None or src.faculty_id != me.id or src.status not in {"locked", "superseded"}:
        raise WorkflowError("Carry over from one of your locked versions.", 404)
    label = f"{src.term or 'earlier term'} v{src.version_no or '?'}"
    n = 0
    for flag, old in carry_over_matches(cv, src):
        flag.status, flag.resolution = "resolved", "accepted"
        flag.resolution_note = f"Carried over from {label}" + (f": {old.resolution_note}" if old.resolution_note else ".")
        flag.resolved_by_id, flag.resolved_at = me.id, utcnow()
        n += 1
    if n and cv.status == "extracted":
        cv.status = "in_review"
    db.flush()
    return n
