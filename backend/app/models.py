"""Database models for Phase 1 (Course Registry) — HANDOFF §7.

While a CourseVersion is under review, the working data is the
``record`` JSON (an ExtractedSyllabus): faculty edits are JSON-Pointer ops on
it, each one logged in FieldEdit (D5). Locking materialises the record into
the normalised tables below (CLO, PLO, Assessment, Week …), which Draft
Studio reads in Phase 2. A locked version is never edited: changing it means
creating a new version.

Phase 2 tables (GenerationRequest, Item, ItemRevision, ReviewEvent,
QualityScore, Export) are at the end. Material/Chunk (grounding library) wait
on the team's decision on HANDOFF §13.A.1.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, JSONType


def utcnow() -> datetime:
    return datetime.now(UTC)


class Faculty(Base):
    __tablename__ = "faculty"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceFile(Base):
    __tablename__ = "source_file"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(400))
    mime: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(200))
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Program(Base):
    """A program as named in a syllabus appendix. Not a master list (D7):
    PLO text lives with each course version."""

    __tablename__ = "program"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_or_name: Mapped[str] = mapped_column(String(200), unique=True)


class Course(Base):
    __tablename__ = "course"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(300))
    credit_hours: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    prerequisites: Mapped[str | None] = mapped_column(Text)


class CourseVersion(Base):
    __tablename__ = "course_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("course.id"), index=True)  # set on lock
    term: Mapped[str | None] = mapped_column(String(40), index=True)  # set on lock (from record)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), index=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_file.id"))
    # extracted | in_review | locked | superseded
    status: Mapped[str] = mapped_column(String(20), default="extracted", index=True)
    version_no: Mapped[int | None] = mapped_column(Integer)  # set on lock, per course+term
    record: Mapped[dict] = mapped_column(JSONType)
    origin: Mapped[str] = mapped_column(String(20), default="upload")  # upload | revision | rollover
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("course_version.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))

    course: Mapped[Course | None] = relationship()
    source_file: Mapped[SourceFile | None] = relationship()
    faculty: Mapped[Faculty] = relationship(foreign_keys=[faculty_id])
    flags: Mapped[list[ValidationFlag]] = relationship(back_populates="course_version", cascade="all, delete-orphan",
                                                      order_by="ValidationFlag.id")
    edits: Mapped[list[FieldEdit]] = relationship(back_populates="course_version", cascade="all, delete-orphan",
                                                  order_by="FieldEdit.id")


class ValidationFlag(Base):
    __tablename__ = "validation_flag"
    __table_args__ = (UniqueConstraint("course_version_id", "fingerprint"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(10))  # error | warning | info
    message: Mapped[str] = mapped_column(Text)
    # The same problem written for a teacher (no rule ids, pointers or braces).
    # `message` stays for the team, behind a "Details" disclosure in the UI.
    plain_message: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(400))
    evidence_refs: Mapped[list] = mapped_column(JSONType, default=list)
    choices: Mapped[list | None] = mapped_column(JSONType)  # one-click fixes (plan 1.13)
    # open | resolved (faculty settled it) | cleared (no longer raised after an edit)
    status: Mapped[str] = mapped_column(String(10), default="open")
    resolution: Mapped[str | None] = mapped_column(String(20))  # accepted | corrected
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    course_version: Mapped[CourseVersion] = relationship(back_populates="flags")
    resolved_by: Mapped[Faculty | None] = relationship()


class FieldEdit(Base):
    """Edit log against the uploaded file: the audit trail (D5). Logged, not approved."""

    __tablename__ = "field_edit"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"), index=True)
    op: Mapped[str] = mapped_column(String(10))  # replace | add | remove | derive
    field_path: Mapped[str] = mapped_column(String(400))
    old_value: Mapped[object | None] = mapped_column(JSONType)
    new_value: Mapped[object | None] = mapped_column(JSONType)
    note: Mapped[str | None] = mapped_column(Text)
    edited_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    course_version: Mapped[CourseVersion] = relationship(back_populates="edits")
    edited_by: Mapped[Faculty] = relationship()


class LLMCall(Base):
    """Every gateway call: which provider, model and prompt version. Inputs are hashed, not stored."""

    __tablename__ = "llm_call"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(200))
    prompt_id: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    input_sha256: Mapped[str] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    course_version_id: Mapped[int | None] = mapped_column(ForeignKey("course_version.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Normalised working version (written on lock) ------------------------ #

class CLO(Base):
    __tablename__ = "clo"
    __table_args__ = (UniqueConstraint("course_version_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    bloom_verb: Mapped[str | None] = mapped_column(String(40))
    bloom_level: Mapped[str | None] = mapped_column(String(20))


class PLO(Base):
    __tablename__ = "plo"
    __table_args__ = (UniqueConstraint("course_version_id", "program_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"))
    number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class CLOPLOMap(Base):
    __tablename__ = "clo_plo_map"
    clo_id: Mapped[int] = mapped_column(ForeignKey("clo.id", ondelete="CASCADE"), primary_key=True)
    plo_id: Mapped[int] = mapped_column(ForeignKey("plo.id", ondelete="CASCADE"), primary_key=True)
    strength: Mapped[str] = mapped_column(String(10))


class AbetOutcomeAddressed(Base):
    __tablename__ = "abet_outcome_addressed"
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"),
                                                   primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"), primary_key=True)
    outcome_no: Mapped[int] = mapped_column(Integer, primary_key=True)


class Assessment(Base):
    __tablename__ = "assessment"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str | None] = mapped_column(String(40))  # quiz, homework, midterm, final, lab, project, …
    weight_pct: Mapped[float | None] = mapped_column(Float)  # from the schedule if listed there, else the table
    weight_table_name: Mapped[str | None] = mapped_column(String(200))
    weight_table_pct: Mapped[float | None] = mapped_column(Float)
    week: Mapped[int | None] = mapped_column(Integer)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_text_raw: Mapped[str | None] = mapped_column(String(300))


class AssessmentCLO(Base):
    __tablename__ = "assessment_clo"
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessment.id", ondelete="CASCADE"), primary_key=True)
    clo_id: Mapped[int] = mapped_column(ForeignKey("clo.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)  # weight_matrix | weekly_schedule


class Week(Base):
    __tablename__ = "week"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"), index=True)
    week_no: Mapped[int] = mapped_column(Integer)
    topics: Mapped[list] = mapped_column(JSONType, default=list)
    readings: Mapped[list] = mapped_column(JSONType, default=list)
    clo_ids_listed: Mapped[list] = mapped_column(JSONType, default=list)


class Resource(Base):
    __tablename__ = "resource"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # textbook | other | web
    citation: Mapped[str] = mapped_column(Text)
    isbn: Mapped[str | None] = mapped_column(String(20))


# ---- Phase 2: Draft Studio, Faculty Review, Quality Checks, Export -------- #

class GenerationRequest(Base):
    """One faculty request: type, CLO(s), week(s), count (§6 'Request drafts')."""

    __tablename__ = "generation_request"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    item_type: Mapped[str] = mapped_column(String(30))
    clo_numbers: Mapped[list] = mapped_column(JSONType, default=list)
    weeks: Mapped[list] = mapped_column(JSONType, default=list)
    count: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[str | None] = mapped_column(String(10))
    bloom_level: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    regenerate_of_item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id", use_alter=True))
    status: Mapped[str] = mapped_column(String(10), default="running")  # running | done | failed
    error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    # What retrieval found, in one sentence, so a draft can say why it is grounded
    # or ungrounded instead of just showing a badge (app/materials/service.py).
    grounding_note: Mapped[str | None] = mapped_column(Text)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Item(Base):
    """A draft. Every AI output is a draft until a named faculty member approves it."""

    __tablename__ = "item"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("generation_request.id"))
    parent_item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"))  # regenerated from
    type: Mapped[str] = mapped_column(String(30), index=True)
    # suggested | under_review | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="suggested", index=True)
    clo_ids: Mapped[list] = mapped_column(JSONType, default=list)  # CLO numbers in the locked version
    week_no: Mapped[int | None] = mapped_column(Integer)
    bloom_level: Mapped[str | None] = mapped_column(String(20))
    difficulty: Mapped[str | None] = mapped_column(String(10))
    body_json: Mapped[dict] = mapped_column(JSONType)
    answer_key_json: Mapped[dict | None] = mapped_column(JSONType)
    rubric_json: Mapped[dict | None] = mapped_column(JSONType)
    feedback_prompts_json: Mapped[dict | None] = mapped_column(JSONType)
    source_chunk_ids: Mapped[list] = mapped_column(JSONType, default=list)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    course_version: Mapped[CourseVersion] = relationship()
    request: Mapped[GenerationRequest | None] = relationship(foreign_keys=[request_id])
    approved_by: Mapped[Faculty | None] = relationship(foreign_keys=[approved_by_id])
    scores: Mapped[list[QualityScore]] = relationship(cascade="all, delete-orphan", order_by="QualityScore.id")
    revisions: Mapped[list[ItemRevision]] = relationship(cascade="all, delete-orphan", order_by="ItemRevision.id")
    events: Mapped[list[ReviewEvent]] = relationship(cascade="all, delete-orphan", order_by="ReviewEvent.id")


class ItemRevision(Base):
    __tablename__ = "item_revision"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    body_json: Mapped[dict] = mapped_column(JSONType)
    answer_key_json: Mapped[dict | None] = mapped_column(JSONType)
    feedback_prompts_json: Mapped[dict | None] = mapped_column(JSONType)
    tags_json: Mapped[dict | None] = mapped_column(JSONType)
    source: Mapped[str] = mapped_column(String(10), default="faculty")  # model | faculty
    edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))  # null for the model's draft
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    edited_by: Mapped[Faculty | None] = relationship()


class ReviewEvent(Base):
    __tablename__ = "review_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # approve | reject | edit | regenerate | reopen
    notes: Mapped[str | None] = mapped_column(Text)
    by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    by: Mapped[Faculty] = relationship()


class QualityScore(Base):
    __tablename__ = "quality_score"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    check: Mapped[str] = mapped_column(String(30))
    # pass | warn | fail | skipped
    outcome: Mapped[str] = mapped_column(String(10))
    score: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Export(Base):
    __tablename__ = "export"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    format: Mapped[str] = mapped_column(String(10))  # docx | pdf
    item_ids: Mapped[list] = mapped_column(JSONType)
    include_answer_key: Mapped[bool] = mapped_column(Boolean)
    by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Background jobs (plan 0.1 / 1.9 / 2.7) ------------------------------- #

class Job(Base):
    """A unit of slow work (extraction, generation) run by the worker."""

    __tablename__ = "job"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # extract | generate | regenerate | …
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    message: Mapped[str | None] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    error_status: Mapped[int | None] = mapped_column(Integer)  # HTTP-like status for the UI
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---- Phase 2A: course materials library (plan 2.1–2.4) --------------------- #

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON

# pgvector on Postgres; a JSON list on SQLite (development). No fixed dimension:
# the embedding model is swappable through the gateway (D10).
EmbeddingType = JSON().with_variant(Vector(), "postgresql")

MATERIAL_KINDS = ("slides", "notes", "past_exam", "textbook", "other")


class Material(Base):
    """A file a faculty member uploads to ground drafts in their own course content."""

    __tablename__ = "material"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id"))
    kind: Mapped[str] = mapped_column(String(20))  # slides | notes | past_exam | textbook | other
    week_no: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    # Licence guard (2.4): a commercial textbook is indexed only if marked licensed.
    licensed: Mapped[bool] = mapped_column(Boolean, default=False)
    # pending | indexed | blocked | failed
    status: Mapped[str] = mapped_column(String(10), default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embed_model: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    file: Mapped[SourceFile] = relationship()
    chunks: Mapped[list[Chunk]] = relationship(cascade="all, delete-orphan", order_by="Chunk.ord")


class Chunk(Base):
    __tablename__ = "chunk"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)  # denormalised for filtering
    ord: Mapped[int] = mapped_column(Integer)
    week_no: Mapped[int | None] = mapped_column(Integer, index=True)
    location: Mapped[str] = mapped_column(String(100))  # e.g. "slides 3–5", "page 2", "§ Regression"
    text: Mapped[str] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(Integer)
    embed_model: Mapped[str] = mapped_column(String(200))
    embedding: Mapped[list] = mapped_column(EmbeddingType)


class NotificationRead(Base):
    """Which dashboard notifications a teacher has already seen. Notifications
    are derived from live state (open things to check, drafts waiting, marks to
    confirm), so only the "seen" mark needs storing."""

    __tablename__ = "notification_read"
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    """Append-only security audit log (plan H.3)."""

    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---- Phase 3: Assessment Builder (plan 3.1–3.12) ---------------------------- #

class AssessmentForm(Base):
    """A quiz/exam assembled from approved items to match a blueprint (3.1–3.4)."""

    __tablename__ = "assessment_form"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    assessment_name: Mapped[str] = mapped_column(String(200))  # the syllabus row it serves, e.g. "Midterm"
    version_label: Mapped[str] = mapped_column(String(10), default="A")  # parallel versions A, B, …
    section: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | approved
    blueprint: Mapped[dict] = mapped_column(JSONType)
    gaps: Mapped[list] = mapped_column(JSONType, default=list)  # what the bank couldn't supply
    created_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list[FormItem]] = relationship(cascade="all, delete-orphan", order_by="FormItem.position")
    approved_by: Mapped[Faculty | None] = relationship(foreign_keys=[approved_by_id])


class FormItem(Base):
    __tablename__ = "form_item"
    form_id: Mapped[int] = mapped_column(ForeignKey("assessment_form.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    points: Mapped[float] = mapped_column(Float)
    option_order: Mapped[list | None] = mapped_column(JSONType)  # shuffled MCQ labels for this version

    item: Mapped[Item] = relationship()


class ItemUsage(Base):
    """Exposure history (3.5): an item went out in a form, for a term and section."""

    __tablename__ = "item_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("assessment_form.id"))
    term: Mapped[str | None] = mapped_column(String(40))
    section: Mapped[str | None] = mapped_column(String(40))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BankImport(Base):
    __tablename__ = "bank_import"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id"))
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VersionDiff(Base):
    """Term-to-term comparison (3.8), computed when a version is locked."""

    __tablename__ = "version_diff"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"))
    to_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    diff: Mapped[dict] = mapped_column(JSONType)
    affected_item_ids: Mapped[list] = mapped_column(JSONType, default=list)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SolvabilityCheck(Base):
    """Can a strong model solve this item unaided? (3.9) Informational only."""

    __tablename__ = "solvability_check"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(200))
    verdict: Mapped[str] = mapped_column(String(10))  # trivial | partly | not | unknown
    detail: Mapped[str] = mapped_column(Text)
    suggestions: Mapped[list] = mapped_column(JSONType, default=list)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SharedBankItem(Base):
    """Opt-in sharing of an approved item with colleagues teaching the same course (3.10)."""

    __tablename__ = "shared_bank_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), unique=True)
    shared_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Phase 4: Grading & Feedback Assist (plan 14.7). Students are data subjects
# only (D3): everything here is keyed by a pseudonym. Real identities live in
# StudentIdentity, encrypted, and only the course's faculty member reads them
# (every read is audit-logged).
# --------------------------------------------------------------------------- #

class Section(Base):
    __tablename__ = "section"
    __table_args__ = (UniqueConstraint("course_version_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    # Calibration sets (4.13) live in their own sections and are never released.
    calibration: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Student(Base):
    __tablename__ = "student"
    id: Mapped[int] = mapped_column(primary_key=True)
    pseudonym: Mapped[str] = mapped_column(String(20), unique=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentIdentity(Base):
    """Real identity, Fernet-encrypted (IDENTITY_KEY). ``lookup_mac`` finds a student
    by ID at intake without decrypting. ``token_macs`` are keyed hashes of every
    identity token, used to prove that no identity is in text bound for a model."""

    __tablename__ = "student_identity"
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id", ondelete="CASCADE"), primary_key=True)
    lookup_mac: Mapped[str] = mapped_column(String(64), index=True)
    external_id_enc: Mapped[str] = mapped_column(Text)
    name_enc: Mapped[str | None] = mapped_column(Text)
    email_enc: Mapped[str | None] = mapped_column(Text)
    token_macs: Mapped[list] = mapped_column(JSONType, default=list)


class Submission(Base):
    __tablename__ = "submission"
    __table_args__ = (UniqueConstraint("form_id", "student_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("assessment_form.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id", ondelete="CASCADE"), index=True)
    # [{"item_id", "position", "text"}], already anonymised (4.3). Original files are not kept.
    answers: Mapped[list] = mapped_column(JSONType, default=list)
    source: Mapped[str] = mapped_column(String(20), default="csv")  # csv | file | blackboard
    redactions: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="received")  # received | scored
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    student: Mapped[Student] = relationship()
    scores: Mapped[list[ResponseScore]] = relationship(cascade="all, delete-orphan")


class ResponseScore(Base):
    """One cell of the students × items grid: the suggestion and the faculty member's mark."""

    __tablename__ = "response_score"
    __table_args__ = (UniqueConstraint("submission_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    method: Mapped[str] = mapped_column(String(10))  # key | code | llm | manual
    max_points: Mapped[float] = mapped_column(Float)
    suggested_points: Mapped[float | None] = mapped_column(Float)
    level_step: Mapped[float] = mapped_column(Float)  # points between adjacent levels (override rule, 4.10)
    criteria: Mapped[list] = mapped_column(JSONType, default=list)  # per criterion: level, points, evidence, confidence
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    needs_faculty: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    confirmed_points: Mapped[float | None] = mapped_column(Float)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    override_reason: Mapped[str | None] = mapped_column(Text)
    history: Mapped[list] = mapped_column(JSONType, default=list)  # every confirmation and re-mark (4.12)


class FeedbackDraft(Base):
    __tablename__ = "feedback_draft"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"))  # None = overall feedback
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))  # key | llm | summary | faculty
    status: Mapped[str] = mapped_column(String(10), default="suggested")  # suggested | approved | rejected
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GradeRelease(Base):
    __tablename__ = "grade_release"
    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("assessment_form.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    channel: Mapped[str] = mapped_column(String(12), default="csv")  # csv | blackboard
    n_students: Mapped[int] = mapped_column(Integer)
    marks: Mapped[dict] = mapped_column(JSONType)  # pseudonym -> total released (the release log)
    by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Appeal(Base):
    __tablename__ = "appeal"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | upheld | changed
    outcome: Mapped[str | None] = mapped_column(Text)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CalibrationSet(Base):
    __tablename__ = "calibration_set"
    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("assessment_form.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    description: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CalibrationScore(Base):
    __tablename__ = "calibration_score"
    __table_args__ = (UniqueConstraint("calibration_id", "submission_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    calibration_id: Mapped[int] = mapped_column(ForeignKey("calibration_set.id", ondelete="CASCADE"), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submission.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    faculty_points: Mapped[float] = mapped_column(Float)


class GradingScale(Base):
    """The scale a faculty member confirmed for a course version (4.4). Release needs it."""

    __tablename__ = "grading_scale"
    __table_args__ = (UniqueConstraint("course_version_id", "letter"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    letter: Mapped[str] = mapped_column(String(4))
    min_pct: Mapped[float] = mapped_column(Float)
    max_pct: Mapped[float] = mapped_column(Float)
    points: Mapped[float | None] = mapped_column(Float)
    confirmed_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)  # e.g. an acknowledged difference from other syllabi


# --------------------------------------------------------------------------- #
# Phase 5: Blackboard (plan 14.8)
# --------------------------------------------------------------------------- #

class StoredBlob(Base):
    """Uploaded file bytes when STORAGE_BACKEND=db (hosts with an ephemeral disk)."""

    __tablename__ = "stored_blob"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class LmsToken(Base):
    """A faculty member's own LMS authorisation (3-legged OAuth), encrypted with IDENTITY_KEY."""

    __tablename__ = "lms_token"
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    lms_user_id: Mapped[str] = mapped_column(String(80))
    access_enc: Mapped[str] = mapped_column(Text)
    refresh_enc: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LmsLink(Base):
    """Course version (+ section) ↔ LMS course (5.2)."""

    __tablename__ = "lms_link"
    __table_args__ = (UniqueConstraint("course_version_id", "section_id", "lms_course_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_version_id: Mapped[int] = mapped_column(ForeignKey("course_version.id"), index=True)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("section.id"))
    lms_course_id: Mapped[str] = mapped_column(String(80))
    lms_course_code: Mapped[str] = mapped_column(String(120))
    lms_course_name: Mapped[str] = mapped_column(String(300))
    lms_term: Mapped[str | None] = mapped_column(String(120))
    linked_by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LmsColumnLink(Base):
    """An approved form ↔ its Grade Center column. ``last_written`` = what this tool last
    wrote per LMS user, to spot grades changed in the LMS since (5.5)."""

    __tablename__ = "lms_column_link"
    __table_args__ = (UniqueConstraint("link_id", "form_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("lms_link.id", ondelete="CASCADE"), index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("assessment_form.id"))
    column_id: Mapped[str] = mapped_column(String(80))
    column_name: Mapped[str] = mapped_column(String(300))
    last_written: Mapped[dict] = mapped_column(JSONType, default=dict)


class LmsSync(Base):
    __tablename__ = "lms_sync"
    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("lms_link.id", ondelete="CASCADE"), index=True)
    form_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_form.id"))
    kind: Mapped[str] = mapped_column(String(20))  # pool_push | submission_pull | grade_push | grade_dry_run
    status: Mapped[str] = mapped_column(String(10))  # ok | partial | failed
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    request_log: Mapped[list] = mapped_column(JSONType, default=list)
    by_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
