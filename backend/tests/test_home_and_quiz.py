"""The home screen (dashboard, search, notifications) and the one-step quiz.

Round 2 is about a teacher understanding the tool on first sight, so these
tests check the words as well as the numbers: no rule ids, no pointers, no
braces in anything the API offers the UI as its main text.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.models import AssessmentForm, Item
from tests.synth.specs import CSAI351, STAT100
from tests.test_api_workflow import A, B, upload
from tests.test_drafts import drafts_post, fake, locked, mcq

JARGON = re.compile(r"\b(CLO|PLO|matrix|schema|canonical|json|pointer|fingerprint|prompt version)\b", re.I)


# --------------------------------------------------------------------------- #
# Plain language on the flags
# --------------------------------------------------------------------------- #

def test_flags_come_with_plain_words(env):
    client, _ = env
    v = upload(client, STAT100, "pdf")
    flags = v["flags"]
    assert flags, "STAT 100 should raise things to check"
    for f in flags:
        assert f["plain_title"], f
        assert f["plain_message"], f
        assert f["plain_severity"] in ("Must fix before confirming", "Worth a look", "Note")
        # No braces, no JSON Pointers, no rule ids in what the teacher reads.
        assert "{" not in f["plain_message"] and "}" not in f["plain_message"], f["plain_message"]
        assert "/weekly/" not in f["plain_message"] and "/clo_matrix/" not in f["plain_message"]
        assert not JARGON.search(f["plain_message"]), f["plain_message"]
        assert not JARGON.search(f["plain_title"]), f["plain_title"]

    v5 = next(f for f in flags if f["rule_id"] == "V5")
    assert v5["plain_title"] == "An assessment lists different learning outcomes in two places"
    assert "the assessment table says" in v5["plain_message"].lower()
    assert "the weekly plan says" in v5["plain_message"].lower()
    assert "outcome" in v5["plain_message"]
    # The one-click fixes are worded for a teacher too.
    assert [c["label"] for c in v5["choices"]] and all(
        "everywhere" in c["label"] and "{" not in c["label"] for c in v5["choices"])

    v9 = next(f for f in flags if f["rule_id"] == "V9")
    assert v9["plain_title"] == "An in-class assessment falls on a day with no class"
    assert "Tuesday and Thursday" in v9["plain_message"]


def test_rule_ids_stay_available_for_the_team(env):
    client, _ = env
    v = upload(client, STAT100, "pdf")
    f = v["flags"][0]
    assert f["rule_id"].startswith(("V", "E"))
    assert f["rule_title"] and f["message"]  # the technical text is still there, for "Details"


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

def test_dashboard_has_everything_the_home_screen_shows(env):
    client, _ = env
    upload(client, STAT100, "pdf")
    cv = locked(client, CSAI351, "docx")
    fake({"mcq": {"items": [mcq(), mcq(stem="Which display best shows a distribution?")]}})
    items = drafts_post(client, cv, {"item_type": "mcq", "clo_numbers": [1], "count": 2}).json()["items"]
    client.post(f"/api/drafts/{items[0]['id']}/action", headers=A, json={"action": "approve"})

    d = client.get("/api/dashboard", headers=A).json()
    assert d["teacher"] == "Dr A"
    kpis = {k["key"]: k for k in d["kpis"]}
    assert set(kpis) == {"courses", "to_check", "waiting", "approved"}
    assert kpis["approved"]["value"] == 1
    assert kpis["waiting"]["value"] == 1
    assert kpis["to_check"]["value"] > 0  # STAT 100 is not confirmed
    for k in kpis.values():
        assert k["note"] and not JARGON.search(k["note"]), k
        assert k["href"].startswith("/")

    assert len(d["week"]) == 7
    assert [w["day"] for w in d["week"]][-1] == __import__("datetime").date.today().strftime("%a")
    assert sum(w["created"] for w in d["week"]) == 2
    assert sum(w["approved"] for w in d["week"]) == 1

    codes = {c["code"] for c in d["courses"]}
    assert {"STAT 100", "CSAI 351"} <= codes
    stat = next(c for c in d["courses"] if c["code"] == "STAT 100")
    assert "to check" in stat["status"] and stat["tone"] == "attention"
    csai = next(c for c in d["courses"] if c["code"] == "CSAI 351")
    assert csai["status"] in ("Confirmed", "1 questions to review")
    assert csai["initials"] == "CS"

    r = d["readiness"]
    assert r["total"] == r["confirmed"] + r["ready"] + r["needs_checking"] == 2


def test_dashboard_next_assessment_points_at_the_quiz_flow(env):
    client, _ = env
    cv = locked(client, CSAI351, "docx")
    d = client.get("/api/dashboard", headers=A).json()
    nxt = d["next_assessment"]
    # CSAI 351 is a Fall 2026 syllabus; dates may be past by the time this runs.
    if nxt is not None:
        assert nxt["course_version_id"] == cv
        assert nxt["days_away"] >= 0
        assert "/quiz" in nxt["href"]
        assert not JARGON.search(nxt["name"])


def test_dashboard_is_per_teacher(env):
    client, _ = env
    upload(client, STAT100, "pdf")
    d = client.get("/api/dashboard", headers=B).json()
    assert d["courses"] == [] and {k["key"]: k["value"] for k in d["kpis"]}["courses"] == 0


# --------------------------------------------------------------------------- #
# Search and notifications
# --------------------------------------------------------------------------- #

def test_search_finds_courses_and_approved_questions_of_this_teacher(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    fake({"mcq": {"items": [mcq(stem="Which measure of center is most affected by outliers?")]}})
    it = drafts_post(client, cv, {"item_type": "mcq", "clo_numbers": [1], "count": 1}).json()["items"][0]

    assert client.get("/api/search?q=s", headers=A).json() == []  # one letter is not a search
    hits = client.get("/api/search?q=STAT", headers=A).json()
    assert hits and hits[0]["kind"] == "course" and "STAT 100" in hits[0]["title"]

    # Only approved questions are searchable; a draft is not.
    assert client.get("/api/search?q=outliers", headers=A).json() == []
    client.post(f"/api/drafts/{it['id']}/action", headers=A, json={"action": "approve"})
    hits = client.get("/api/search?q=outliers", headers=A).json()
    assert hits and hits[0]["kind"] == "question"

    assert client.get("/api/search?q=STAT", headers=B).json() == []  # not their course


def test_notifications_list_and_mark_as_read(env):
    client, _ = env
    upload(client, STAT100, "pdf")
    notes = client.get("/api/notifications", headers=A).json()
    assert notes and all(n["read"] is False for n in notes)
    first = next(n for n in notes if "to check" in n["title"])
    assert "STAT 100" in first["title"] and not JARGON.search(first["body"])

    assert client.post("/api/notifications/read", headers=A, json={"keys": [first["key"]]}).status_code == 204
    notes = client.get("/api/notifications", headers=A).json()
    assert next(n for n in notes if n["key"] == first["key"])["read"] is True

    # Marking everything read is idempotent.
    for _ in range(2):
        assert client.post("/api/notifications/read", headers=A, json={}).status_code == 204
    assert all(n["read"] for n in client.get("/api/notifications", headers=A).json())
    assert client.get("/api/notifications", headers=B).json() == []


# --------------------------------------------------------------------------- #
# One-step quiz
# --------------------------------------------------------------------------- #

def test_quiz_options_describe_the_choices_in_plain_words(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    o = client.get(f"/api/course-versions/{cv}/quiz-options", headers=A).json()
    assert o["can_create"] is True
    assert o["course"].startswith("STAT 100")
    names = [c["name"] for c in o["choices"]]
    assert "Midterm" in names and "Final" in names
    mid = next(c for c in o["choices"] if c["name"] == "Midterm")
    assert "% of the grade" in mid["subtitle"] and "week" in mid["subtitle"]
    assert mid["weeks"] and max(mid["weeks"]) <= mid["week"]
    assert mid["clo_numbers"]
    assert [t["type"] for t in o["types"]][:2] == ["mcq", "short_answer"]
    assert all(t["label"] and t["points"] > 0 for t in o["types"])
    assert o["slides"] == []  # none added yet
    assert [w["number"] for w in o["outcomes"]] == [1, 2, 3, 4, 5]


def test_create_a_quiz_in_one_request(env):
    """3 multiple-choice and 2 short-answer, one button, one paper."""
    client, Session = env
    cv = locked(client, STAT100, "pdf")
    fake({
        "mcq": {"items": [mcq(stem=f"Multiple choice {i}") for i in range(1, 4)]},
        "short_answer": {"items": [_short(f"Short answer {i}") for i in (1, 2)]},
    })
    r = client.post(f"/api/course-versions/{cv}/quizzes", headers=A, json={
        "assessment_name": "Quiz 2", "weeks": [1, 2, 3], "clo_numbers": [1],
        "difficulty": "medium",
        "mix": [{"type": "mcq", "count": 3, "points": 2}, {"type": "short_answer", "count": 2, "points": 5}],
    })
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "done", job
    form_id = job["result"]["form_id"]

    forms = client.get(f"/api/course-versions/{cv}/forms", headers=A).json()
    form = next(f for f in forms if f["id"] == form_id)
    assert form["assessment_name"] == "Quiz 2" and form["status"] == "draft"
    assert [i["position"] for i in form["items"]] == [1, 2, 3, 4, 5]
    # The mix is kept in the order asked for: the three multiple-choice first.
    assert [i["type"] for i in form["items"]] == ["mcq"] * 3 + ["short_answer"] * 2
    assert [i["points"] for i in form["items"]] == [2, 2, 2, 5, 5]
    assert form["gaps"] == []

    with Session() as db:
        items = list(db.scalars(select(Item).where(Item.course_version_id == cv)).all())
        assert len(items) == 5 and {i.status for i in items} == {"suggested"}
        assert db.get(AssessmentForm, form_id).blueprint["total_points"] == 16


def test_a_quiz_cannot_be_made_from_an_unconfirmed_syllabus(env):
    client, _ = env
    v = upload(client, STAT100, "pdf")
    r = client.post(f"/api/course-versions/{v['id']}/quizzes", headers=A,
                    json={"mix": [{"type": "mcq", "count": 1}]})
    assert r.status_code == 409
    assert "Confirm the syllabus" in r.json()["detail"]


def test_a_quiz_needs_at_least_one_question_and_has_a_ceiling(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    r = client.post(f"/api/course-versions/{cv}/quizzes", headers=A, json={"mix": []})
    assert r.status_code == 422 and "at least one question" in r.json()["detail"]
    r = client.post(f"/api/course-versions/{cv}/quizzes", headers=A,
                    json={"mix": [{"type": "mcq", "count": 50}]})
    assert r.status_code == 422 and "at a time" in r.json()["detail"]
    r = client.post(f"/api/course-versions/{cv}/quizzes", headers=A,
                    json={"mix": [{"type": "sonnet", "count": 1}]})
    assert r.status_code == 422


def test_a_new_quiz_cannot_be_exported_until_it_is_approved(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    fake({"mcq": {"items": [mcq(stem="Only question")]}})
    job = client.post(f"/api/course-versions/{cv}/quizzes", headers=A,
                      json={"mix": [{"type": "mcq", "count": 1}]}).json()
    form_id = job["result"]["form_id"]
    r = client.post(f"/api/forms/{form_id}/export", headers=A, json={"format": "docx"})
    assert r.status_code == 409  # the invariant holds for quizzes made in one step too


def test_another_teacher_cannot_make_a_quiz_on_your_course(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    r = client.post(f"/api/course-versions/{cv}/quizzes", headers=B,
                    json={"mix": [{"type": "mcq", "count": 1}]})
    assert r.status_code == 404
    assert client.get(f"/api/course-versions/{cv}/quiz-options", headers=B).status_code == 404


def _short(question: str) -> dict:
    return {
        "tags": {"clo_numbers": [1], "week_no": 2, "bloom_level": "understand", "difficulty": "medium"},
        "body": {"question": question, "expected_length": "3 to 4 sentences"},
        "answer_key": {"model_answer": "A clear answer naming the key idea.",
                       "key_points": ["names the idea", "gives an example"]},
        "feedback": {"hint": "Think about the definition.", "explanation": "The definition is the key."},
    }


# --------------------------------------------------------------------------- #
# Work a teacher can walk away from (round 3, section 1)
# --------------------------------------------------------------------------- #

def test_the_quiz_exists_before_a_single_question_is_written(env):
    """A teacher who presses Create and leaves must still find the quiz.

    The route creates the paper and only then queues the writing, so the form
    is there from the first second with status 'writing'.
    """
    client, Session = env
    cv = locked(client, STAT100, "pdf")
    from app.builder import quiz
    from app.models import CourseVersion, Faculty

    with Session() as db:
        cvr = db.get(CourseVersion, cv)
        me = db.get(Faculty, cvr.faculty_id)
        form = quiz.start(db, cvr, me, assessment_name="Quiz 2",
                          mix=quiz.parse_mix([{"type": "mcq", "count": 3}]),
                          clo_numbers=[1], weeks=[1, 2], difficulty="medium")
        db.commit()
        form_id, label = form.id, form.version_label

    listed = client.get(f"/api/course-versions/{cv}/forms", headers=A).json()
    row = next(f for f in listed if f["id"] == form_id)
    assert row["status"] == "writing"
    assert row["assessment_name"] == "Quiz 2" and label == "A"
    assert row["blueprint"]["asked_for"] == 3
    # Nothing half-written may be approved or exported.
    assert client.post(f"/api/forms/{form_id}/edit", headers=A,
                       json={"action": "approve"}).status_code == 409


def test_a_create_quiz_request_names_its_job_and_links_back_to_the_quiz(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    fake({"mcq": {"items": [mcq(stem=f"Multiple choice {i}") for i in range(1, 3)]}})
    job = client.post(f"/api/course-versions/{cv}/quizzes", headers=A, json={
        "assessment_name": "Quiz 1", "weeks": [1], "clo_numbers": [1],
        "mix": [{"type": "mcq", "count": 2}]}).json()
    assert job["title"] == "Quiz 1 · 2 questions"
    assert job["course_version_id"] == cv
    form_id = job["result"]["form_id"]
    assert job["link"] == f"/v/{cv}/quiz/{form_id}"
    # Finished work has no time left to show, and the form ended as a draft.
    assert job["time_left"] is None and job["status"] == "done"
    row = next(f for f in client.get(f"/api/course-versions/{cv}/forms", headers=A).json()
               if f["id"] == form_id)
    assert row["status"] == "draft"


def test_a_quiz_that_cannot_be_written_says_so_instead_of_writing_for_ever(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    fake({"mcq": {"error": "the model is unavailable"}})
    job = client.post(f"/api/course-versions/{cv}/quizzes", headers=A, json={
        "assessment_name": "Quiz 1", "weeks": [1], "clo_numbers": [1],
        "mix": [{"type": "mcq", "count": 2}]}).json()
    assert job["status"] == "failed"
    rows = client.get(f"/api/course-versions/{cv}/forms", headers=A).json()
    form = next(f for f in rows if f["job_id"] == job["id"])
    assert form["status"] == "failed"
    assert form["error"] and "{" not in form["error"]


def test_jobs_list_shows_this_teachers_work_only(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    fake({"mcq": {"items": [mcq(stem="One")]}})
    client.post(f"/api/course-versions/{cv}/quizzes", headers=A,
                json={"assessment_name": "Quiz 1", "mix": [{"type": "mcq", "count": 1}]})

    active = client.get("/api/jobs?active=1", headers=A).json()
    assert active == []  # the test worker runs jobs there and then
    recent = client.get("/api/jobs?recent=1", headers=A).json()
    assert recent, "the finished quiz should be in the last 24 hours"
    assert recent[0]["finished_at"] is not None
    assert all(j["title"] for j in recent)
    assert client.get("/api/jobs?recent=1", headers=B).json() == []


def test_time_left_is_said_in_words_not_seconds(env):
    from app.api.schemas import time_left_words
    from app.models import Job

    assert time_left_words(Job(status="running", progress=10, eta_seconds=20)) == "Less than a minute left"
    assert time_left_words(Job(status="running", progress=10, eta_seconds=95)) == "About 2 minutes left"
    assert time_left_words(Job(status="running", progress=95, eta_seconds=600)) == "Almost done"
    assert time_left_words(Job(status="running", progress=10, eta_seconds=None)) == "Working it out"
    assert time_left_words(Job(status="done", progress=100, eta_seconds=0)) is None


def test_a_job_left_running_by_a_restart_is_failed_not_left_spinning(env):
    client, Session = env
    cv = locked(client, STAT100, "pdf")
    from datetime import timedelta

    from app import jobs as jobmod
    from app.builder import quiz
    from app.models import CourseVersion, Faculty, Job, utcnow

    with Session() as db:
        cvr = db.get(CourseVersion, cv)
        me = db.get(Faculty, cvr.faculty_id)
        form = quiz.start(db, cvr, me, assessment_name="Quiz 2",
                          mix=quiz.parse_mix([{"type": "mcq", "count": 2}]),
                          clo_numbers=[1], weeks=[1], difficulty="medium")
        job = Job(kind="create_quiz", faculty_id=me.id, payload={}, status="running",
                  started_at=utcnow() - timedelta(seconds=jobmod.STALE_AFTER_SECONDS + 60))
        db.add(job)
        db.flush()
        form.job_id = job.id
        db.commit()
        form_id, job_id = form.id, job.id

        assert jobmod.sweep_stale(db) == 1
        db.expire_all()
        assert db.get(Job, job_id).status == "failed"
        assert db.get(__import__("app.models", fromlist=["AssessmentForm"]).AssessmentForm,
                      form_id).status == "failed"


def test_after_a_restart_nothing_from_before_is_still_running(env):
    """Inline workers die with the web process (a free host sleeping, a redeploy).
    On start-up, running work is failed in plain words and the quiz says why."""
    client, Session = env
    cv = locked(client, STAT100, "pdf")
    from app import jobs as jobmod
    from app.builder import quiz
    from app.models import CourseVersion, Faculty, Job, utcnow

    with Session() as db:
        cvr = db.get(CourseVersion, cv)
        me = db.get(Faculty, cvr.faculty_id)
        form = quiz.start(db, cvr, me, assessment_name="Quiz 2",
                          mix=quiz.parse_mix([{"type": "mcq", "count": 2}]),
                          clo_numbers=[1], weeks=[1], difficulty="medium")
        job = Job(kind="create_quiz", faculty_id=me.id, payload={}, status="running", progress=40,
                  started_at=utcnow())  # only seconds old: the age-based sweep would not catch it
        db.add(job)
        db.flush()
        form.job_id = job.id
        db.commit()
        form_id, job_id = form.id, job.id

        failed, restarted = jobmod.recover_after_restart(db)
        assert (failed, restarted) == (1, 0)
        db.expire_all()
        assert db.get(Job, job_id).status == "failed"
        f = db.get(AssessmentForm, form_id)
        assert f.status == "failed" and f.error == "Something went wrong while writing this quiz. Try again."


def test_finished_work_lands_in_the_bell_with_a_link_back(env):
    client, _ = env
    cv = locked(client, STAT100, "pdf")
    fake({"mcq": {"items": [mcq(stem=f"Question {i}") for i in range(1, 3)]}})
    job = client.post(f"/api/course-versions/{cv}/quizzes", headers=A, json={
        "assessment_name": "Quiz 1", "weeks": [1], "clo_numbers": [1],
        "mix": [{"type": "mcq", "count": 2}]}).json()
    notes = client.get("/api/notifications", headers=A).json()
    done = next(n for n in notes if n["key"] == f"job:{job['id']}")
    assert done["title"] == "Quiz 1 · 2 questions is ready"
    assert done["href"] == job["link"] == f"/v/{cv}/quiz/{job['result']['form_id']}"
    assert not JARGON.search(done["title"] + done["body"])
    assert not [n for n in client.get("/api/notifications", headers=B).json() if n["key"].startswith("job:")]
