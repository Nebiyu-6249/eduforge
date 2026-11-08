"""Deleting a course from "My courses" (round 4): the syllabus and everything made from it."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import (
    AssessmentForm,
    AuditEvent,
    Chunk,
    Course,
    CourseVersion,
    Item,
    Job,
    Material,
    SourceFile,
    ValidationFlag,
)
from tests.synth.specs import CSCI372, STAT100
from tests.test_api_workflow import A, B, upload
from tests.test_drafts import fake, locked, mcq
from tests.test_materials import _upload as upload_material


def _count(db, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _listed(client) -> list[int]:
    return [v["id"] for v in client.get("/api/course-versions", headers=A).json()]


def test_a_syllabus_still_being_checked_can_be_deleted(env):
    client, Session = env
    v = upload(client, STAT100, "pdf")
    assert v["status"] != "locked"
    with Session() as db:
        src = db.get(CourseVersion, v["id"]).source_file_id
        assert _count(db, ValidationFlag, ValidationFlag.course_version_id == v["id"]) > 0
    assert client.delete(f"/api/course-versions/{v['id']}", headers=B).status_code == 404  # not someone else's
    assert client.delete(f"/api/course-versions/{v['id']}", headers=A).status_code == 204
    assert v["id"] not in _listed(client)
    with Session() as db:
        assert db.get(CourseVersion, v["id"]) is None
        assert _count(db, ValidationFlag, ValidationFlag.course_version_id == v["id"]) == 0
        assert _count(db, Job, Job.course_version_id == v["id"]) == 0
        assert db.get(SourceFile, src) is None  # the uploaded file (with the teacher's name on it) goes too


def test_a_confirmed_course_goes_with_its_quizzes_questions_and_slides(env):
    client, Session = env
    cv = locked(client, STAT100, "pdf")
    fake({"mcq": {"items": [mcq(stem=f"Gone {i}") for i in range(1, 3)]}})
    job = client.post(f"/api/course-versions/{cv}/quizzes", headers=A, json={
        "assessment_name": "Quiz 1", "weeks": [1], "clo_numbers": [1], "mix": [{"type": "mcq", "count": 2}]}).json()
    form_id = job["result"]["form_id"]
    for fi in client.get(f"/api/forms/{form_id}", headers=A).json()["items"]:
        client.post(f"/api/drafts/{fi['item_id']}/action", headers=A, json={"action": "approve"})
    assert client.post(f"/api/forms/{form_id}/edit", headers=A, json={"action": "approve"}).json()["status"] == "approved"
    upload_material(client, cv, "week1.txt", b"The mean uses every value. " * 200, kind="notes", week_no=1)
    with Session() as db:
        course_id = db.get(CourseVersion, cv).course_id
        assert _count(db, Material, Material.course_id == course_id) == 1

    assert client.delete(f"/api/course-versions/{cv}", headers=A).status_code == 204
    assert cv not in _listed(client)
    with Session() as db:
        assert _count(db, Item, Item.course_version_id == cv) == 0
        assert _count(db, AssessmentForm, AssessmentForm.course_version_id == cv) == 0
        assert _count(db, Material, Material.course_id == course_id) == 0
        assert _count(db, Chunk, Chunk.course_id == course_id) == 0
        assert db.get(Course, course_id) is None
        ev = db.scalar(select(AuditEvent).where(AuditEvent.action == "course_deleted"))
        assert ev is not None and ev.detail["code"] == "STAT 100" and ev.detail["removed"]["item"] == 2
    # Nothing about it is left on the home screen.
    assert not [n for n in client.get("/api/notifications", headers=A).json() if f"/v/{cv}/" in n["href"]]


def test_the_versions_it_replaced_go_too_and_a_later_term_stays(env):
    client, Session = env
    v = upload(client, CSCI372, "pdf")
    assert client.post(f"/api/course-versions/{v['id']}/lock", headers=A).status_code == 200
    nv = client.post(f"/api/course-versions/{v['id']}/revise", headers=A).json()
    assert client.post(f"/api/course-versions/{nv['id']}/lock", headers=A).status_code == 200
    nxt = client.post(f"/api/course-versions/{nv['id']}/rollover", headers=A, json={"term": "Spring 2027"}).json()

    assert client.delete(f"/api/course-versions/{nv['id']}", headers=A).status_code == 204
    with Session() as db:
        assert db.get(CourseVersion, v["id"]) is None  # the replaced version went with it
        kept = db.get(CourseVersion, nxt["id"])
        assert kept is not None and kept.parent_version_id is None  # the next term stays, unlinked
    assert nxt["id"] in _listed(client)
    assert client.get(f"/api/course-versions/{nxt['id']}", headers=A).status_code == 200
