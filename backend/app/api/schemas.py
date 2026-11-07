from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FacultyOut(BaseModel):
    id: int
    email: str
    name: str
    is_team: bool = False  # may open the team metrics dashboard


class FlagOut(BaseModel):
    id: int
    rule_id: str
    rule_title: str
    severity: str
    message: str
    evidence_refs: list[str]
    choices: list[dict[str, Any]] = []
    status: str
    resolution: str | None
    resolution_note: str | None
    resolved_by: str | None
    resolved_at: datetime | None


class VersionSummary(BaseModel):
    id: int
    status: str
    origin: str
    course_code: str | None
    course_title: str | None
    term: str | None
    version_no: int | None
    source_filename: str | None
    open_blocking: int
    created_at: datetime
    updated_at: datetime
    locked_at: datetime | None
    parent_version_id: int | None


class PreviousVersion(BaseModel):
    id: int
    term: str | None
    version_no: int | None
    matching_settled_flags: int  # open flags here that were settled there


class VersionDetail(VersionSummary):
    record: dict[str, Any]
    flags: list[FlagOut]
    edit_count: int
    can_lock: bool
    previous: PreviousVersion | None = None  # plan 1.15: offer last term's locked version
    export_count: int = 0  # so the course page can show how far the workflow has got


class EditOp(BaseModel):
    op: Literal["replace", "add", "remove"] = "replace"
    path: str
    value: Any = None


class EditRequest(BaseModel):
    ops: list[EditOp] = Field(min_length=1)
    note: str | None = None


class ResolveRequest(BaseModel):
    action: Literal["accept", "reopen"]
    note: str | None = None


class RolloverRequest(BaseModel):
    term: str


class EditOut(BaseModel):
    id: int
    op: str
    field_path: str
    old_value: Any
    new_value: Any
    note: str | None
    edited_by: str
    at: datetime
    # Plain-English rendering (app/services/labels.py); the UI never shows JSON.
    op_label: str = ""
    label: str = ""
    old_text: str = ""
    new_text: str = ""
    # Edits saved together (same editor, seconds apart) share a group number so
    # one save reads as one row.
    group: int = 0


class JobOut(BaseModel):
    id: int
    kind: str
    status: str  # queued | running | done | failed
    progress: int
    message: str | None
    result: dict[str, Any] | None
    error: str | None
    error_status: int | None
    created_at: datetime
    finished_at: datetime | None


def job_out(job) -> JobOut:
    return JobOut(id=job.id, kind=job.kind, status=job.status, progress=job.progress or 0, message=job.message,
                  result=job.result, error=job.error, error_status=job.error_status, created_at=job.created_at,
                  finished_at=job.finished_at)
