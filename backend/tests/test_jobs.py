"""Database-backed job queue (plan 0.1 / 1.9)."""

from __future__ import annotations

from app import jobs
from app.config import get_settings
from app.models import Faculty, Job
from tests.synth.render import to_pdf
from tests.synth.specs import CSCI372, build
from tests.test_api_workflow import A


def test_external_mode_waits_for_a_worker(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(get_settings(), "worker_mode", "external")
    r = client.post("/api/syllabi", headers=A, files={"file": ("c.pdf", to_pdf(build(CSCI372)), "application/pdf")})
    job = r.json()
    assert r.status_code == 202 and job["status"] == "queued"

    with Session() as db:
        claimed = jobs.claim_next(db)
        assert claimed is not None and claimed.id == job["id"] and claimed.status == "running"
        assert jobs.claim_next(db) is None  # nothing else queued; can't take the same job twice
    jobs.run(job["id"])

    done = client.get(f"/api/jobs/{job['id']}", headers=A).json()
    assert done["status"] == "done" and done["progress"] == 100
    v = client.get(f"/api/course-versions/{done['result']['course_version_id']}", headers=A).json()
    assert v["course_code"] == "CSCI 372"


def test_failure_is_recorded_on_the_job(env):
    _, Session = env
    with Session() as db:
        me = Faculty(email="x@example.edu", name="X")
        db.add(me)
        db.commit()
        job = jobs.enqueue(db, "extract", me, {"source_file_id": 999})  # no such file
        db.refresh(job)
        assert job.status == "failed" and job.error_status == 410 and "gone" in job.error


def test_other_faculty_cannot_read_a_job(env):
    client, Session = env
    r = client.post("/api/syllabi", headers=A, files={"file": ("c.pdf", to_pdf(build(CSCI372)), "application/pdf")})
    other = {"X-Dev-User": "b.faculty@example.edu"}
    assert client.get(f"/api/jobs/{r.json()['id']}", headers=other).status_code == 404
    with Session() as db:
        assert db.get(Job, r.json()["id"]).kind == "extract"
