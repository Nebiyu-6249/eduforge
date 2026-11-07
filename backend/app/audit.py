"""Security audit log (plan 11 'audit log', H.3).

Records security-relevant actions in one append-only table: sign-ins, syllabus
uploads, locks, exports and downloads of assessment material, materials
added/removed. Content edits and review decisions have their own detailed
trails (FieldEdit, ReviewEvent, ItemRevision); model calls are in LLMCall.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditEvent, Faculty


def record(db: Session, who: Faculty | None, action: str, detail: dict | None = None) -> None:
    db.add(AuditEvent(faculty_id=who.id if who else None, action=action, detail=detail or {}))
