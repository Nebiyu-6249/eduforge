"""The LMS interface (plan 5.1). Blackboard is the only implementation; another
LMS would implement the same methods. Every call runs as the faculty member
(3-legged OAuth), never as a service account."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class LmsError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Token:
    access_token: str
    refresh_token: str | None
    expires_at: float
    user_id: str


@dataclass
class LmsCourse:
    id: str          # primary id, e.g. _123_1
    course_id: str   # human id, e.g. CSCI372-S26-01
    name: str
    term: str | None = None


@dataclass
class LmsColumn:
    id: str
    name: str
    possible: float | None = None


@dataclass
class LmsGrade:
    user_id: str
    score: float | None
    feedback: str | None = None


@dataclass
class LmsUser:
    id: str
    user_name: str
    student_id: str | None
    name: str | None
    email: str | None


@dataclass
class LmsAttempt:
    id: str
    user_id: str
    text: str
    status: str = "NeedsGrading"


@dataclass
class CallLog:
    """Every request made, for LmsSync.request_log (plan 5.5 'every write logged')."""

    entries: list[dict] = field(default_factory=list)

    def add(self, method: str, path: str, status: int, note: str = "") -> None:
        self.entries.append({"method": method, "path": path, "status": status, **({"note": note} if note else {})})


class LmsAdapter(Protocol):
    name: str

    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Token: ...
    def refresh(self, token: Token) -> Token: ...
    def courses(self, token: Token) -> list[LmsCourse]: ...
    def columns(self, token: Token, course: str) -> list[LmsColumn]: ...
    def create_column(self, token: Token, course: str, name: str, possible: float, description: str) -> LmsColumn: ...
    def grades(self, token: Token, course: str, column: str) -> list[LmsGrade]: ...
    def put_grade(self, token: Token, course: str, column: str, user: str, score: float, feedback: str | None) -> None: ...
    def attempts(self, token: Token, course: str, column: str) -> list[LmsAttempt]: ...
    def user(self, token: Token, user: str) -> LmsUser: ...
    def roster(self, token: Token, course: str) -> list[LmsUser]: ...
