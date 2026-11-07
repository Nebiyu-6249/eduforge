"""Build the grading demo: a confirmed STAT 100 syllabus, ten approved
questions, an approved paper, a class of 30 invented students and their
answers.

No model is called: the ten questions are written out in ``demo_data.py``.
Run it against any database::

    cd backend
    uv run python -m scripts.seed_demo                       # the configured DATABASE_URL
    uv run python -m scripts.seed_demo --database-url ...    # somewhere else
    uv run python -m scripts.seed_demo --score               # also run the marking

It is idempotent: running it again finds the demo and leaves it alone unless
``--reset`` is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import Base, make_engine
from app.extraction.pipeline import extract
from app.models import (
    AssessmentForm,
    CourseVersion,
    Faculty,
    FormItem,
    Item,
    ItemRevision,
    Section,
)
from app.services import course_versions as registry
from scripts import demo_data

DEMO_ASSESSMENT = "Quiz 2 (demo)"
DEMO_SECTION = "Demo section"
DEMO_FILENAME = "STAT100_demo.pdf"


def _faculty(db: Session, email: str, name: str) -> Faculty:
    f = db.scalar(select(Faculty).where(Faculty.email == email))
    if f is None:
        f = Faculty(email=email, name=name)
        db.add(f)
        db.flush()
    return f


def _syllabus_bytes() -> bytes:
    """The synthetic STAT 100 syllabus, rendered as a PDF."""
    from tests.synth.render import to_pdf
    from tests.synth.specs import STAT100, build

    return to_pdf(build(STAT100))


def _confirm(db: Session, cv: CourseVersion, me: Faculty) -> None:
    """Settle everything the validator raised, then confirm the syllabus. A
    demo has no teacher to make the calls, so each one is accepted with a note
    that says so."""
    for f in cv.flags:
        if f.status == "open":
            registry.resolve_flag(db, cv, me, f.id, "accept", "Accepted for the demo data set.")
    registry.lock(db, cv, me)
    db.flush()


def _add_questions(db: Session, cv: CourseVersion, me: Faculty) -> list[Item]:
    items: list[Item] = []
    for q in demo_data.QUESTIONS:
        it = Item(course_version_id=cv.id, type=q.type, status="approved", clo_ids=[q.clo], week_no=q.week,
                  bloom_level="understand" if q.type == "mcq" else "apply", difficulty="medium",
                  body_json=q.body, answer_key_json=q.answer_key, feedback_prompts_json=q.feedback,
                  grounded=False, source_chunk_ids=[], model="demo", prompt_version="demo",
                  approved_by_id=me.id)
        db.add(it)
        db.flush()
        it.revisions.append(ItemRevision(
            body_json=q.body, answer_key_json=q.answer_key, feedback_prompts_json=q.feedback,
            tags_json={"clo_numbers": [q.clo], "week_no": q.week, "bloom_level": "understand",
                       "difficulty": "medium"}, source="model"))
        items.append(it)
    db.flush()
    return items


def _add_form(db: Session, cv: CourseVersion, me: Faculty, items: list[Item]) -> AssessmentForm:
    form = AssessmentForm(
        course_version_id=cv.id, assessment_name=DEMO_ASSESSMENT, version_label="A", status="approved",
        blueprint={"assessment": DEMO_ASSESSMENT, "weeks": sorted({q.week for q in demo_data.QUESTIONS}),
                   "types": {"mcq": 6, "problem": 2, "short_answer": 2},
                   "total_points": demo_data.TOTAL_POINTS, "minutes": 40, "demo": True},
        gaps=[], created_by_id=me.id, approved_by_id=me.id)
    db.add(form)
    db.flush()
    for pos, (q, it) in enumerate(zip(demo_data.QUESTIONS, items), 1):
        # No option shuffle on the demo paper: the committed answers CSV uses
        # the letters as written, so A means A for anyone who uploads it.
        form.items.append(FormItem(item_id=it.id, position=pos, points=q.points, option_order=None))
    db.flush()
    return form


def _add_class(db: Session, cv: CourseVersion, me: Faculty, form: AssessmentForm) -> Section:
    from app.grading import intake
    from app.grading import service as grading

    section = db.scalar(select(Section).where(Section.course_version_id == cv.id,
                                              Section.label == DEMO_SECTION))
    if section is None:
        section = grading.create_section(db, me, cv, DEMO_SECTION)
        db.flush()
    grading.add_roster(db, me, section, intake.parse_roster(demo_data.roster_csv().encode()))
    grading.intake_csv(db, me, form, section, demo_data.answers_csv().encode())
    db.flush()
    return section


def find_demo(db: Session, me: Faculty) -> tuple[CourseVersion, AssessmentForm] | None:
    form = db.scalar(select(AssessmentForm).where(AssessmentForm.created_by_id == me.id,
                                                  AssessmentForm.assessment_name == DEMO_ASSESSMENT))
    if form is None:
        return None
    cv = db.get(CourseVersion, form.course_version_id)
    return (cv, form) if cv else None


def seed(db: Session, email: str = "demo.faculty@prototype.eduforge", name: str = "Demo Faculty",
         reset: bool = False, score: bool = False) -> dict:
    """Create the demo, or report the one that is already there."""
    me = _faculty(db, email, name)
    found = find_demo(db, me)
    if found and not reset:
        cv, form = found
        section = db.scalar(select(Section).where(Section.course_version_id == cv.id,
                                                  Section.label == DEMO_SECTION))
        return {"created": False, "course_version_id": cv.id, "form_id": form.id,
                "section_id": section.id if section else None,
                "message": "The demo is already here; nothing changed."}
    if found and reset:
        # Keep the old demo rather than delete it: once a paper has been
        # marked, deleting it would take the marks with it. Renaming it leaves
        # the audit trail intact and frees the name for the new one.
        _old_cv, old_form = found
        old_form.assessment_name = f"{DEMO_ASSESSMENT} (replaced)"
        db.flush()

    rec = extract(DEMO_FILENAME, _syllabus_bytes())
    sf = registry.store_file(db, me, DEMO_FILENAME, _syllabus_bytes())
    cv = registry.build_version(db, me, sf, _syllabus_bytes())
    assert rec.course.code == "STAT 100"
    _confirm(db, cv, me)
    items = _add_questions(db, cv, me)
    form = _add_form(db, cv, me, items)
    section = _add_class(db, cv, me, form)
    db.commit()

    out = {"created": True, "course_version_id": cv.id, "form_id": form.id, "section_id": section.id,
           "questions": len(items), "students": 30,
           "message": "Demo ready: a confirmed STAT 100 syllabus, 10 approved questions, "
                      f"'{DEMO_ASSESSMENT}' and a class of 30 students with their answers."}
    if score:
        from app.grading import service as grading
        from app.llm.factory import get_gateway

        if not get_settings().grading_enabled:
            out["scored"] = False
            out["message"] += (" Marking was not run: Grading Assist is switched off. Set GRADING_ENABLED=true "
                               "(and IDENTITY_KEY) to run it.")
            return out
        grading.score(db, form, section, get_gateway(db, faculty_id=me.id, course_version_id=cv.id))
        db.commit()
        out["scored"] = True
    return out


def write_fixtures(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "roster_30_students.csv").write_text(demo_data.roster_csv(), encoding="utf-8")
    (folder / "answers_30_students.csv").write_text(demo_data.answers_csv(), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database-url", default=None, help="defaults to the configured DATABASE_URL")
    ap.add_argument("--email", default="demo.faculty@prototype.eduforge")
    ap.add_argument("--name", default="Demo Faculty")
    ap.add_argument("--reset", action="store_true", help="rebuild the demo even if it is already there")
    ap.add_argument("--score", action="store_true", help="also run the marking pass")
    ap.add_argument("--write-fixtures", metavar="DIR", default=None,
                    help="write the roster and answers CSVs to this folder and exit")
    args = ap.parse_args()

    if args.write_fixtures:
        write_fixtures(Path(args.write_fixtures))
        print(f"Wrote the demo CSVs to {args.write_fixtures}")
        return

    url = args.database_url or get_settings().database_url
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
        out = seed(db, args.email, args.name, reset=args.reset, score=args.score)
    print(out["message"])
    print(f"  course version {out['course_version_id']} · paper {out['form_id']} · "
          f"section {out.get('section_id')}")


if __name__ == "__main__":
    main()
