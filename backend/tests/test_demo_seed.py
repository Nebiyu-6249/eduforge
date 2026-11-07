"""The grading demo: 30 invented students, their answers, and the seed script.

The point of the demo is that a teacher can watch marking work end to end
without any real student data, so these tests check the shape of the data as
much as the plumbing: a spread of ability, the tempting wrong answer chosen
more often, blanks, two identical answers, and one answer carrying a name and
a phone number that anonymisation has to remove.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.grading.identity import PHONE, Person, scrub
from app.models import AssessmentForm, Item, ResponseScore, Section, Student, Submission
from scripts import demo_data, seed_demo

A = {"X-Dev-User": "a.faculty@example.edu", "X-Dev-Name": "Dr A"}


# --------------------------------------------------------------------------- #
# The data itself
# --------------------------------------------------------------------------- #

def test_the_class_is_clearly_invented():
    people = demo_data.students()
    assert len(people) == 30
    assert len({s.student_id for s in people}) == 30
    assert all(s.email.endswith("@example.edu") for s in people)
    assert all(" " in s.name for s in people)
    # A spread of ability, not everyone the same.
    abilities = [s.ability for s in people]
    assert min(abilities) < 0.45 < max(abilities)
    assert 0.6 < sum(abilities) / len(abilities) < 0.76


def test_the_paper_is_six_multiple_choice_two_numeric_two_written():
    kinds = [q.type for q in demo_data.QUESTIONS]
    assert kinds.count("mcq") == 6
    assert kinds.count("problem") == 2
    assert kinds.count("short_answer") == 2
    assert demo_data.TOTAL_POINTS == 34
    for q in demo_data.QUESTIONS:
        if q.type == "mcq":
            assert len(q.body["options"]) == 4
            assert q.answer_key["correct"] in {o["label"] for o in q.body["options"]}
            assert len(q.answer_key["why_others_wrong"]) == 3
        if q.type == "problem":
            assert q.answer_key["numeric_answer"] is not None


def test_the_answers_look_like_a_real_class():
    rows = demo_data.answers()
    assert len(rows) == 30

    # Multiple choice: the key wins, and the tempting distractor beats the rest.
    for n, q in enumerate(demo_data.QUESTIONS, 1):
        if q.type != "mcq":
            continue
        picked = [row[n] for _s, row in rows]
        right = picked.count(q.correct)
        tempting = picked.count(q.tempting)
        others = [picked.count(o) for o in q.others]
        assert right > tempting >= max(others or [0]), (n, right, tempting, others)
        assert 0.4 < right / 30 < 0.95

    # Numeric: some right answers are written with different rounding.
    numeric_cols = [n for n, q in enumerate(demo_data.QUESTIONS, 1) if q.type == "problem"]
    forms_of_ten = {row[numeric_cols[0]] for _s, row in rows}
    assert {"10", "10.0"} & forms_of_ten and len(forms_of_ten) > 2

    written = [n for n, q in enumerate(demo_data.QUESTIONS, 1) if q.type == "short_answer"]
    texts = [row[n] for _s, row in rows for n in written]
    assert sum(1 for t in texts if not t.strip()) == 2  # two blanks
    assert len({t for t in texts if t.strip()}) >= 5  # varied quality
    assert sum(1 for t in texts if t == demo_data.TWIN_TEXT) == 2  # for the consistency check
    leaky = [t for t in texts if "My name is" in t]
    assert len(leaky) == 1 and "050 412 7788" in leaky[0]


def test_the_csv_files_match_the_paper():
    roster = demo_data.roster_csv().splitlines()
    assert roster[0] == "Student ID,Name,Email" and len(roster) == 31
    answers = demo_data.answers_csv().splitlines()
    assert answers[0].startswith("Student ID,Q1,") and answers[0].endswith("Q10")
    assert len(answers) == 31


def test_committed_fixtures_are_the_same_data():
    """fixtures/demo/*.csv is what the script writes, so the files a teacher can
    upload by hand always match the demo."""
    import pathlib

    folder = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "demo"
    assert (folder / "roster_30_students.csv").read_text(encoding="utf-8") == demo_data.roster_csv()
    assert (folder / "answers_30_students.csv").read_text(encoding="utf-8") == demo_data.answers_csv()


# --------------------------------------------------------------------------- #
# Anonymisation: the planted identity must not survive
# --------------------------------------------------------------------------- #

def test_a_phone_number_at_the_end_of_a_sentence_is_removed():
    """It used to survive: the pattern refused any following dot, to protect
    decimals, which also excluded sentence-final numbers."""
    assert PHONE.sub("[PHONE]", "call me on 050 412 7788.") == "call me on [PHONE]."
    assert PHONE.sub("[PHONE]", "phone +971 50 412 7788.") == "phone [PHONE]."
    # Decimals are still left alone.
    assert PHONE.sub("[PHONE]", "the value is 3.14159265358979") == "the value is 3.14159265358979"
    assert PHONE.sub("[PHONE]", "the mean of 12345678.9 marks") == "the mean of 12345678.9 marks"


def test_the_planted_answer_loses_the_name_the_id_and_the_phone():
    st = demo_data.students()[demo_data.LEAKY_INDEX]
    text = demo_data.LEAKY_TEMPLATE.format(name=st.name, sid=st.student_id)
    roster = [Person(external_id=s.student_id, name=s.name, email=s.email) for s in demo_data.students()]
    clean, n = scrub(text, roster)
    assert st.name not in clean and st.student_id not in clean and "050 412 7788" not in clean
    assert "[NAME]" in clean and "[PHONE]" in clean and n >= 3
    assert "The median is better" in clean  # the answer itself survives


# --------------------------------------------------------------------------- #
# The seed script
# --------------------------------------------------------------------------- #

@pytest.fixture()
def grading_on(monkeypatch):
    from cryptography.fernet import Fernet

    s = get_settings()
    monkeypatch.setattr(s, "grading_enabled", True)
    monkeypatch.setattr(s, "identity_key", Fernet.generate_key().decode())
    return s


def test_seed_builds_the_whole_demo_and_is_idempotent(env, grading_on):
    _client, Session = env
    with Session() as db:
        out = seed_demo.seed(db)
        assert out["created"] is True and out["questions"] == 10 and out["students"] == 30

        cv = db.get(__import__("app.models", fromlist=["CourseVersion"]).CourseVersion,
                    out["course_version_id"])
        assert cv.status == "locked", "the demo syllabus is confirmed"
        assert not [f for f in cv.flags if f.status == "open"]

        items = list(db.scalars(select(Item).where(Item.course_version_id == cv.id)).all())
        assert len(items) == 10 and {i.status for i in items} == {"approved"}

        form = db.get(AssessmentForm, out["form_id"])
        assert form.status == "approved" and len(form.items) == 10
        assert all(fi.option_order is None for fi in form.items), "the committed CSV uses the letters as written"

        section = db.get(Section, out["section_id"])
        assert len(list(db.scalars(select(Student).where(Student.section_id == section.id)).all())) == 30
        subs = list(db.scalars(select(Submission).where(Submission.form_id == form.id)).all())
        assert len(subs) == 30
        assert sum(s.redactions for s in subs) >= 2  # the planted identity was removed on the way in

        again = seed_demo.seed(db)
        assert again["created"] is False and again["form_id"] == out["form_id"]


def test_seed_then_mark_gives_a_believable_spread(env, grading_on):
    from app.grading import service as grading

    _client, Session = env
    with Session() as db:
        out = seed_demo.seed(db)
        form = db.get(AssessmentForm, out["form_id"])
        section = db.get(Section, out["section_id"])
        grading.score(db, form, section, None)  # no model: key marking only
        db.commit()

        auto = sum(q.points for q in demo_data.QUESTIONS if q.type in ("mcq", "problem"))
        totals = []
        for sub in db.scalars(select(Submission).where(Submission.form_id == form.id)).all():
            scores = list(db.scalars(select(ResponseScore)
                                     .where(ResponseScore.submission_id == sub.id)).all())
            totals.append(sum(s.suggested_points or 0 for s in scores))
        share = [t / auto for t in totals]
        assert 0.55 < sum(share) / len(share) < 0.85, share
        assert min(share) < 0.5 < max(share), "a spread, not everyone the same"

        # Written answers are left for the teacher; nothing is auto-confirmed.
        all_scores = list(db.scalars(select(ResponseScore)).all())
        assert {s.method for s in all_scores} == {"key", "manual"}
        assert all(s.confirmed_points is None for s in all_scores)


def test_sample_class_button_fills_an_empty_section(env, grading_on, monkeypatch):
    """The Grading page offers this when a section has no answers; it only
    exists in the open prototype."""
    client, Session = env
    with Session() as db:
        out = seed_demo.seed(db)
    form_id = out["form_id"]

    monkeypatch.setattr(get_settings(), "auth_mode", "open")
    with Session() as db:
        cv_id = db.get(AssessmentForm, form_id).course_version_id
        me = db.scalar(select(__import__("app.models", fromlist=["Faculty"]).Faculty))
    headers = {"X-Dev-User": me.email, "X-Dev-Name": me.name}

    r = client.post(f"/api/grading/course-versions/{cv_id}/sections", headers=headers,
                    json={"label": "Empty section"})
    assert r.status_code == 201, r.text
    new_section = r.json()["id"]

    r = client.post(f"/api/grading/forms/{form_id}/sections/{new_section}/sample-class", headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["sample"] is True and r.json()["students"] == 30

    # A second press is refused rather than doubling the class.
    r = client.post(f"/api/grading/forms/{form_id}/sections/{new_section}/sample-class", headers=headers)
    assert r.status_code == 409 and "already has answers" in r.json()["detail"]


def test_sample_class_is_refused_outside_the_open_prototype(env, grading_on):
    client, Session = env
    with Session() as db:
        out = seed_demo.seed(db)
        me = db.scalar(select(__import__("app.models", fromlist=["Faculty"]).Faculty))
    headers = {"X-Dev-User": me.email, "X-Dev-Name": me.name}
    r = client.post(f"/api/grading/forms/{out['form_id']}/sections/{out['section_id']}/sample-class",
                    headers=headers)
    assert r.status_code == 403 and "open prototype" in r.json()["detail"]


def test_nothing_in_the_demo_looks_like_a_real_address():
    """The repo is public: the invented class must not carry anything that
    could be mistaken for a real person's contact details."""
    text = demo_data.roster_csv() + demo_data.answers_csv()
    emails = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text))
    assert emails and all(e.endswith("@example.edu") for e in emails)
