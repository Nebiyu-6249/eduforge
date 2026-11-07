"""Program-wide coverage (plan 3.11).

Across all locked versions of one program's courses in a term: a PLO × course
matrix with strengths and ABET 'addressed' marks. PLOs are per syllabus (D7),
so they are matched across courses by program + number; where the wording
differs between syllabi, that is shown, not resolved.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extraction.normalize import label_key
from app.models import CourseVersion, Program

_RANK = {"high": 3, "medium": 2, "low": 1}


def programs(db: Session) -> list[dict]:
    return [{"id": p.id, "name": p.code_or_name} for p in db.scalars(select(Program).order_by(Program.code_or_name))]


def coverage(db: Session, program_id: int, term: str | None) -> dict:
    prog = db.get(Program, program_id)
    if prog is None:
        raise LookupError("No such program.")
    key = label_key(prog.code_or_name)
    q = select(CourseVersion).where(CourseVersion.status == "locked")
    if term:
        q = q.where(CourseVersion.term == term)
    courses: list[dict] = []
    wording: dict[int, dict[str, list[str]]] = {}
    for cv in db.scalars(q).all():
        rec = cv.record
        block = next((p for p in rec.get("programs", []) if label_key(p["name"]) == key), None)
        if block is None:
            continue
        cells: dict[str, dict] = {}
        for link in block.get("clo_plo", []):
            c = cells.setdefault(str(link["plo"]), {"strength": None, "clos": []})
            c["clos"].append(link["clo"])
            if c["strength"] is None or _RANK[link["strength"]] > _RANK[c["strength"]]:
                c["strength"] = link["strength"]
        for plo in block.get("plos", []):
            wording.setdefault(plo["number"], {}).setdefault(plo["text"].strip(), []).append(rec["course"]["code"])
        courses.append({"course_version_id": cv.id, "code": rec["course"]["code"], "title": rec["course"]["title"],
                        "term": cv.term, "cells": cells, "addressed": block.get("abet_addressed", [])})
    plo_numbers = sorted(wording) or sorted({int(p) for c in courses for p in c["cells"]})
    return {
        "program": prog.code_or_name, "term": term,
        "plos": [{"number": n, "wordings": [{"text": t, "courses": cs} for t, cs in (wording.get(n) or {}).items()]}
                 for n in plo_numbers],
        "courses": sorted(courses, key=lambda c: c["code"] or ""),
        "uncovered": [n for n in plo_numbers if not any(str(n) in c["cells"] for c in courses)],
    }
