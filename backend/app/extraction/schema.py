"""Fixed JSON schema for an extracted AURAK syllabus (HANDOFF §8.2).

Every parser (DOCX, PDF, LLM-assisted) must produce an ``ExtractedSyllabus``.
The validator runs on this record, faculty edits are JSON-Pointer patches
against it, and locking materialises it into the normalised tables.

Raw text is always kept next to normalised values (e.g. ``due_text_raw``) so
faculty can see what the file actually said.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

Strength = Literal["high", "medium", "low"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseInfo(_Base):
    code: str | None = None
    title: str | None = None
    credit_hours: float | None = None
    prerequisites: str | None = None
    description: str | None = None
    additional_info: str | None = None
    methods_of_instruction: str | None = None


class ClassMeeting(_Base):
    """One section/time slot parsed from 'Class Timing(s)'."""

    days: list[Weekday] = Field(default_factory=list)
    time_text: str | None = None


class Offering(_Base):
    term: str | None = None  # normalised, e.g. "Fall 2026"
    term_raw: str | None = None
    class_timing_raw: str | None = None
    meetings: list[ClassMeeting] = Field(default_factory=list)
    instructor_name: str | None = None
    instructor_contact: str | None = None


class Resources(_Base):
    textbooks: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)
    web: list[str] = Field(default_factory=list)


class CLOItem(_Base):
    number: int
    text: str


class WeightEntry(_Base):
    """A column of the Assessment Activities weight table."""

    name: str
    weight_pct: float | None = None


class MatrixEntry(_Base):
    """CLO × assessment 'X' matrix, one entry per assessment column."""

    assessment: str
    clo_numbers: list[int] = Field(default_factory=list)


class ScheduledAssessment(_Base):
    """An assessment as listed in the Weekly Course Information table."""

    name: str
    weight_pct: float | None = None
    due_text_raw: str | None = None
    due_date: date | None = None
    due_week: int | None = None


class WeekRow(_Base):
    week_no: int
    topics: list[str] = Field(default_factory=list)
    readings: list[str] = Field(default_factory=list)
    assessments: list[ScheduledAssessment] = Field(default_factory=list)
    clo_numbers: list[int] = Field(default_factory=list)
    clo_text_raw: str | None = None


class PLOItem(_Base):
    number: int
    text: str


class CLOPLOLink(_Base):
    clo: int
    plo: int
    strength: Strength


class ProgramBlock(_Base):
    """One APPENDIX block; a syllabus may contain several (D7, §9)."""

    name: str
    plos: list[PLOItem] = Field(default_factory=list)
    clo_plo: list[CLOPLOLink] = Field(default_factory=list)
    abet_addressed: list[int] = Field(default_factory=list)


class SourceRef(_Base):
    """Where a value was read from (plan 0.6). Numbers are 1-based; page is
    None for DOCX (Word has no fixed pages); table counts tables in document
    order; row is the row within that table."""

    page: int | None = None
    table: int | None = None
    row: int | None = None
    raw_text: str | None = None


class GradeBand(_Base):
    """One row of the Grading Scale table (plan 4.4, D12): letter, percentage range, grade points."""

    letter: str
    min_pct: float
    max_pct: float
    points: float | None = None


class ExtractionNote(_Base):
    """Parser-level warning, e.g. a table that could not be read."""

    where: str
    message: str


class ExtractedSyllabus(_Base):
    schema_version: str = SCHEMA_VERSION
    course: CourseInfo = Field(default_factory=CourseInfo)
    offering: Offering = Field(default_factory=Offering)
    resources: Resources = Field(default_factory=Resources)
    clos: list[CLOItem] = Field(default_factory=list)
    weights: list[WeightEntry] = Field(default_factory=list)
    clo_matrix: list[MatrixEntry] = Field(default_factory=list)
    weekly: list[WeekRow] = Field(default_factory=list)
    programs: list[ProgramBlock] = Field(default_factory=list)
    # Read from the "Grading Scale" section; matters from Phase 4 (V13), where letters depend on it.
    grading_scale: list[GradeBand] = Field(default_factory=list)
    # Heading -> verbatim section text; used by V10 (template leftovers).
    raw_sections: dict[str, str] = Field(default_factory=dict)
    notes: list[ExtractionNote] = Field(default_factory=list)
    # JSON Pointer -> where it came from in the file. Look up with source_for(),
    # which falls back to the nearest parent ('/weekly/4/assessments/0' -> '/weekly/4').
    sources: dict[str, SourceRef] = Field(default_factory=dict)

    def source_for(self, ptr: str) -> SourceRef | None:
        p = ptr
        while p:
            if p in self.sources:
                return self.sources[p]
            p = p.rsplit("/", 1)[0]
        return None

    # ---- convenience -------------------------------------------------------
    def scheduled_assessments(self) -> list[tuple[int, int, ScheduledAssessment]]:
        """(week_index, assessment_index, item) for every scheduled assessment."""
        out = []
        for wi, w in enumerate(self.weekly):
            for ai, a in enumerate(w.assessments):
                out.append((wi, ai, a))
        return out

    def meeting_days(self) -> set[str]:
        days: set[str] = set()
        for m in self.offering.meetings:
            days.update(m.days)
        return days
