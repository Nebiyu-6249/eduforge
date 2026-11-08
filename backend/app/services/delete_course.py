"""Deleting a course from "My courses": the syllabus and everything made from it.

A row on "My courses" is one course and term. Deleting it removes that version,
the earlier versions it replaced (same course and term), and everything that
hangs off them: the things to check, the change log, the question bank, the
quizzes and exams, rosters, Blackboard links and background jobs. Slides go too
when no other term of the course is left for this teacher, and the course
itself when nobody else uses it. The uploaded files are removed when nothing
else points at them.

It refuses, and says why, when students' answers or marks belong to it (those
are records a released mark depends on), when work for it is still running, or
when one of its questions sits on a paper of another course.

The rows to remove are found by walking the foreign keys, so a table added
later is covered without editing this file. A few references are cut instead
of followed (the AI-call cost log keeps its rows; a version made from this one
keeps existing).
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import Table, delete, select, update
from sqlalchemy.orm import Session

from app import storage
from app.audit import record
from app.models import (
    Base,
    Course,
    CourseVersion,
    Faculty,
    Job,
    Material,
    SourceFile,
    StoredBlob,
)
from app.services.course_versions import WorkflowError

# (table, column) references that are set to NULL rather than followed.
CUT = {("llm_call", "course_version_id"), ("course_version", "parent_version_id"),
       ("lms_sync", "form_id"), ("item_usage", "form_id")}
# Student records: their presence stops the delete.
STUDENT_WORK = ("submission", "grade_release", "calibration_set")


def _tables() -> dict[str, Table]:
    return {t.name: t for t in Base.metadata.sorted_tables}


Rows = dict[str, set[int]]
Refs = dict[tuple[str, str], set[int]]


def _closure(db: Session, roots: Rows) -> tuple[Rows, Refs, Refs]:
    """Every row that would have to go with ``roots``; the references to cut;
    and, for link tables without an id, the parent ids whose links go."""
    tables = _tables()
    doomed: Rows = defaultdict(set)
    cut: Refs = defaultdict(set)
    links: Refs = defaultdict(set)
    todo = [(name, set(ids)) for name, ids in roots.items()]
    while todo:
        parent, ids = todo.pop()
        ids = ids - doomed[parent]
        if not ids:
            continue
        doomed[parent] |= ids
        for t in tables.values():
            for fk in t.foreign_keys:
                if fk.column.table.name != parent:
                    continue
                col = fk.parent
                if "id" not in t.c:  # a link table (form_item, assessment_clo …)
                    links[(t.name, col.name)] |= ids
                    continue
                rows = {r for (r,) in db.execute(select(t.c.id).where(col.in_(ids)))}
                if (t.name, col.name) in CUT:
                    cut[(t.name, col.name)] |= rows
                elif rows:
                    todo.append((t.name, rows))
    return doomed, cut, links


def delete_course(db: Session, cv: CourseVersion, me: Faculty) -> dict:
    # The row and the versions it replaced for the same course and term.
    versions = {cv.id}
    if cv.course_id is not None and cv.status != "superseded":  # a replaced version on its own goes alone
        versions |= set(db.scalars(select(CourseVersion.id).where(
            CourseVersion.faculty_id == me.id, CourseVersion.course_id == cv.course_id,
            CourseVersion.term == cv.term, CourseVersion.status == "superseded")))

    running = db.scalar(select(Job.id).where(Job.course_version_id.in_(versions),
                                             Job.status.in_(("queued", "running"))).limit(1))
    if running is not None:
        raise WorkflowError("Something for this course is still running. Wait until it is done, then delete it.", 409)

    roots: dict[str, set[int]] = {"course_version": versions}
    # Slides belong to the course, not the term: they go when this teacher has no other term of it.
    course = db.get(Course, cv.course_id) if cv.course_id else None
    if course is not None:
        others = db.scalar(select(CourseVersion.id).where(
            CourseVersion.faculty_id == me.id, CourseVersion.course_id == course.id,
            CourseVersion.id.not_in(versions)).limit(1))
        if others is None:
            mats = set(db.scalars(select(Material.id).where(Material.course_id == course.id,
                                                            Material.faculty_id == me.id)))
            if mats:
                roots["material"] = mats

    doomed, cut, links = _closure(db, roots)

    if any(doomed.get(t) for t in STUDENT_WORK):
        raise WorkflowError("Students' answers or marks are attached to a quiz in this course, so the course is "
                            "kept with them and cannot be deleted.", 409)
    forms = doomed.get("assessment_form", set())
    tables = _tables()
    fi = tables["form_item"]
    foreign = db.execute(select(fi.c.form_id).where(fi.c.item_id.in_(doomed.get("item", set())),
                                                     fi.c.form_id.not_in(forms)).limit(1)).first()
    if foreign is not None:
        raise WorkflowError("Some questions from this course are on a paper in another course. Remove them from "
                            "that paper first.", 409)

    # Files to tidy afterwards: the uploads these rows point at.
    bi = tables["bank_import"]
    found: set[int | None] = set(db.scalars(select(CourseVersion.source_file_id).where(CourseVersion.id.in_(versions))))
    found |= set(db.scalars(select(Material.file_id).where(Material.id.in_(doomed.get("material", set())))))
    found |= {f for (f,) in db.execute(select(bi.c.file_id).where(bi.c.id.in_(doomed.get("bank_import", set()))))}
    files = {f for f in found if f is not None}

    code = ((cv.record or {}).get("course") or {}).get("code")
    summary = {"course_version_ids": sorted(versions), "code": code, "term": cv.term, "status": cv.status,
               "removed": {t: len(ids) for t, ids in sorted(doomed.items()) if ids}}

    for (tname, col), ids in cut.items():
        if ids:
            t = tables[tname]
            db.execute(update(t).where(t.c.id.in_(ids)).values({col: None}))
    # Cut every nullable reference among the doomed rows first, so cycles
    # (a question rewritten from another, a version made from another) do not
    # block the deletes; then delete children before parents.
    for name, ids in doomed.items():
        t = tables[name]
        for c in t.c:
            if c.foreign_keys and c.nullable and ids:
                db.execute(update(t).where(t.c.id.in_(ids)).values({c.name: None}))
    for (tname, col), ids in links.items():
        t = tables[tname]
        db.execute(delete(t).where(t.c[col].in_(ids)))
    for t in reversed(Base.metadata.sorted_tables):
        if doomed.get(t.name):
            db.execute(delete(t).where(t.c.id.in_(doomed[t.name])))
    db.flush()
    db.expire_all()

    # The course row goes when nothing points at it any more.
    if course is not None:
        still = db.scalar(select(CourseVersion.id).where(CourseVersion.course_id == course.id).limit(1)) or \
            db.scalar(select(Material.id).where(Material.course_id == course.id).limit(1)) or \
            db.execute(select(tables["shared_bank_item"].c.id)
                       .where(tables["shared_bank_item"].c.course_id == course.id).limit(1)).first()
        if not still:
            db.execute(delete(Course).where(Course.id == course.id))

    _tidy_files(db, files)
    record(db, me, "course_deleted", summary)
    db.flush()
    return summary


def _tidy_files(db: Session, file_ids: set[int]) -> None:
    """Remove uploads no remaining row points at, and their stored bytes."""
    tables = _tables()
    for fid in file_ids:
        used = False
        for t in tables.values():
            for fk in t.foreign_keys:
                if fk.column.table.name == "source_file" and \
                        db.execute(select(fk.parent).where(fk.parent == fid).limit(1)).first():
                    used = True
        if used:
            continue
        sf = db.get(SourceFile, fid)
        if sf is None:
            continue
        key = sf.storage_key
        db.delete(sf)
        db.flush()
        if db.scalar(select(SourceFile.id).where(SourceFile.storage_key == key).limit(1)) is None:
            if storage._db_mode():
                db.execute(delete(StoredBlob).where(StoredBlob.key == key))
            else:
                path = storage.cache_dir() / key
                if path.is_file() and path.resolve().is_relative_to(storage.cache_dir().resolve()):
                    path.unlink()


__all__ = ["delete_course"]
