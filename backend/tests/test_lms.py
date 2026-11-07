"""Phase 5: Blackboard integration (plan 5.1–5.6), against the fake Learn REST server."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.lms import service as lms
from app.lms.blackboard import BlackboardAdapter
from app.lms.fake_blackboard import BASE, FakeBlackboard
from app.models import AssessmentForm, LmsSync, LmsToken
from tests.synth.specs import STAT100
from tests.test_api_workflow import A
from tests.test_drafts import locked
from tests.test_grading import _form, _rubric_fake, _setup, on  # noqa: F401  (fixture)

STUDENTS = [("20231234", "Mariam Al Hashimi"), ("20235678", "Omar Khalid"), ("B00123456", "Will Turner")]


@pytest.fixture()
def bb(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "lms_mode", "blackboard")
    monkeypatch.setattr(s, "session_secret", "test-secret-" + "x" * 20)
    fb = FakeBlackboard()
    lms.set_adapter_override(lambda log, on_refresh: BlackboardAdapter(
        BASE, "key", "secret", "http://localhost:8000/api/lms/callback", client=fb.client(), log=log, min_interval=0,
        sleep=lambda _s: None, on_refresh=on_refresh))
    fb.instructor = fb.add_user("a.faculty", "Dr A", email=A["X-Dev-User"])  # type: ignore[attr-defined]
    fb.studs = [fb.add_user(sid.lower(), name, sid, None) for sid, name in STUDENTS]  # type: ignore[attr-defined]
    fall, spring = fb.add_term("Fall 2026"), fb.add_term("Spring 2026")
    fb.right = fb.add_course("STAT100-F26-01", "STAT 100 Intro Probability and Statistics", fall, fb.instructor, fb.studs)  # type: ignore[attr-defined]
    fb.wrong_term = fb.add_course("STAT100-S26-01", "STAT 100", spring, fb.instructor, fb.studs)  # type: ignore[attr-defined]
    fb.wrong_code = fb.add_course("MATH101-F26-01", "MATH 101 Calculus", fall, fb.instructor, fb.studs)  # type: ignore[attr-defined]
    other = fb.add_user("someone", "Some One")
    fb.add_course("STAT100-F26-02", "STAT 100 (not mine)", fall, other, [fb.instructor])  # student role only
    yield fb
    lms.set_adapter_override(None)


def _connect(client, fb):
    r = client.post("/api/lms/connect", headers=A).json()
    assert r["connected"] is False and r["authorize_url"].startswith(BASE)
    q = parse_qs(urlparse(r["authorize_url"]).query)
    assert q["scope"] == ["read write offline"] and q["response_type"] == ["code"]
    cb = client.get("/api/lms/callback", params={"code": fb.authorize(fb.instructor), "state": q["state"][0]},
                    follow_redirects=False)
    assert cb.status_code == 302, cb.text
    assert client.get("/api/lms/status", headers=A).json() == {"mode": "blackboard", "connected": True}


def test_off_by_default(env):
    client, _ = env
    assert client.get("/api/lms/status", headers=A).json() == {"mode": "off", "connected": False}
    r = client.get("/api/lms/courses", headers=A)
    assert r.status_code == 403 and "13.C" in r.json()["detail"]


def test_connect_and_wrong_course_protection(env, on, bb):  # noqa: F811
    client, Session = env
    cv = locked(client, STAT100)
    _connect(client, bb)
    with Session() as db:
        tok = db.scalar(select(LmsToken))
        assert tok is not None and tok.access_enc not in bb.tokens  # stored encrypted
    courses = client.get("/api/lms/courses", headers=A).json()
    assert {c["course_id"] for c in courses} == {"STAT100-F26-01", "STAT100-S26-01", "MATH101-F26-01"}  # paged; student-role course left out
    assert next(c for c in courses if c["id"] == bb.right)["term"] == "Fall 2026"
    r = client.post("/api/lms/links", headers=A, json={"course_version_id": cv, "lms_course_id": bb.wrong_term})
    assert r.status_code == 409 and "Spring 2026" in r.json()["detail"]["message"]
    r = client.post("/api/lms/links", headers=A, json={"course_version_id": cv, "lms_course_id": bb.wrong_code})
    assert r.status_code == 409 and "STAT 100" in r.json()["detail"]["message"]
    r = client.post("/api/lms/links", headers=A, json={"course_version_id": cv, "lms_course_id": "_999_c"})
    assert r.status_code == 404
    r = client.post("/api/lms/links", headers=A, json={"course_version_id": cv, "lms_course_id": bb.right})
    assert r.status_code == 201 and r.json()["lms_course_code"] == "STAT100-F26-01"


def _linked_and_pulled(env, bb):
    client, Session = env
    cv, sec, form_id, _items = _setup(env)
    _connect(client, bb)
    ln = client.post("/api/lms/links", headers=A, json={"course_version_id": cv, "lms_course_id": bb.right,
                                                         "section_id": sec}).json()
    # 5.3: unapproved forms never go out.
    with Session() as db:
        f = db.get(AssessmentForm, form_id)
        f.status = "draft"
        db.commit()
    assert client.post(f"/api/lms/links/{ln['id']}/push", headers=A, json={"form_id": form_id}).status_code == 409
    with Session() as db:
        db.get(AssessmentForm, form_id).status = "approved"
        db.commit()
    p = client.post(f"/api/lms/links/{ln['id']}/push", headers=A, json={"form_id": form_id}).json()
    assert p["status"] == "ok" and p["requests"] >= 1
    col = p["summary"]["column_id"]
    assert bb.columns[bb.right][col]["score"]["possible"] == 100
    again = client.post(f"/api/lms/links/{ln['id']}/push", headers=A, json={"form_id": form_id}).json()
    assert again["summary"]["column_id"] == col and len(bb.columns[bb.right]) == 1  # idempotent

    # 5.4: pull text attempts; identities removed on arrival.
    _rubric_fake()
    for uid, (_sid, name) in zip(bb.studs, STUDENTS, strict=True):
        bb.add_attempt(bb.right, col, uid, f"Q1: B\nQ2: wrong\nQ1: A\nQ2: t = 2\nQ3: It uses every value. {name}\nQ4: ")
    bb.add_attempt(bb.right, col, bb.studs[0], "Q1: A\nQ2: t = 2\nQ3: It uses every value. Mariam Al Hashimi\nQ4: ")
    r = client.post(f"/api/lms/links/{ln['id']}/pull", headers=A, json={"form_id": form_id}).json()
    assert r["summary"]["blackboard_students"] == r["summary"]["stored"] == 3  # matches Blackboard counts
    assert r["summary"]["blackboard_attempts"] == 4 and r["job"]["status"] == "done"
    grid = client.get(f"/api/grading/forms/{form_id}/sections/{sec}/grid", headers=A).json()
    assert len(grid["rows"]) == 3
    stored = " ".join(client.get(f"/api/grading/submissions/{x['submission_id']}", headers=A).text for x in grid["rows"])
    assert "Mariam" not in stored and "Khalid" not in stored and "Turner" not in stored
    return cv, sec, form_id, ln["id"], col


def _confirm_all(client, cv, sec, form_id):
    client.post(f"/api/grading/forms/{form_id}/sections/{sec}/confirm-key", headers=A, json={})
    grid = client.get(f"/api/grading/forms/{form_id}/sections/{sec}/grid", headers=A).json()
    for r in grid["rows"]:
        for c in r["cells"].values():
            if c["confirmed"] is None:
                pts = c["suggested"] if c["suggested"] is not None else 10
                assert client.post(f"/api/grading/scores/{c['id']}/confirm", headers=A,
                                   json={"points": pts, "reason": "ok"}).status_code == 200
    view = client.get(f"/api/grading/course-versions/{cv}/scale", headers=A).json()
    client.post(f"/api/grading/course-versions/{cv}/scale", headers=A, json={"bands": view["extracted"]})
    grid = client.get(f"/api/grading/forms/{form_id}/sections/{sec}/grid", headers=A).json()
    assert grid["blockers"] == []
    return {r["pseudonym"]: r["confirmed_total"] for r in grid["rows"]}


def _patches(fb):
    return [p for m, p in fb.requests if m == "PATCH"]


def test_end_to_end_push_pull_confirm_passback(env, on, bb):  # noqa: F811
    client, Session = env
    cv, sec, form_id, link, col = _linked_and_pulled(env, bb)
    body = {"form_id": form_id}

    # No unconfirmed mark is ever written.
    r = client.post(f"/api/lms/links/{link}/passback", headers=A, json={**body, "dry_run": False})
    assert r.status_code == 409 and r.json()["detail"]["blockers"] and not _patches(bb)

    totals = _confirm_all(client, cv, sec, form_id)
    # Approve one student's overall feedback: it travels with the grade.
    grid = client.get(f"/api/grading/forms/{form_id}/sections/{sec}/grid", headers=A).json()
    first = grid["rows"][0]
    fb_id = next(f["id"] for f in client.get(f"/api/grading/submissions/{first['submission_id']}", headers=A).json()["feedback"]
                 if f["item_id"] is None)
    client.post(f"/api/grading/feedback/{fb_id}", headers=A, json={"action": "approve"})

    # A grade the faculty member changed in Blackboard is not overwritten silently.
    bb.grades[(bb.right, col)] = {bb.studs[2]: {"score": 11.0, "feedback": None}}
    dry = client.post(f"/api/lms/links/{link}/passback", headers=A, json={**body, "dry_run": True}).json()
    assert dry["kind"] == "grade_dry_run" and not _patches(bb)
    actions = sorted(r["action"] for r in dry["summary"]["rows"])
    assert actions == ["changed in Blackboard: skipped", "write", "write"]

    real = client.post(f"/api/lms/links/{link}/passback", headers=A, json={**body, "dry_run": False}).json()
    assert real["status"] == "ok" and real["summary"]["counts"]["written"] == 2 and len(_patches(bb)) == 2
    by_sid = {r["student_id"]: r for r in real["summary"]["rows"]}
    g = bb.grades[(bb.right, col)]
    assert g[bb.studs[0]]["score"] == by_sid["20231234"]["new"] and g[bb.studs[2]]["score"] == 11.0
    assert sorted(r["new"] for r in real["summary"]["rows"]) == sorted(totals.values())
    assert any(v.get("feedback") for v in g.values())  # approved overall feedback went with the grade

    # Idempotent re-run: nothing new is written.
    n = len(_patches(bb))
    rerun = client.post(f"/api/lms/links/{link}/passback", headers=A, json={**body, "dry_run": False}).json()
    assert len(_patches(bb)) == n and "written" not in rerun["summary"]["counts"]
    # Overwrite on request.
    pseudo = next(r["pseudonym"] for r in real["summary"]["rows"] if r["student_id"] == "B00123456")
    ow = client.post(f"/api/lms/links/{link}/passback", headers=A, json={**body, "dry_run": False, "overwrite": [pseudo]}).json()
    assert ow["summary"]["counts"]["written"] == 1 and bb.grades[(bb.right, col)][bb.studs[2]]["score"] == by_sid["B00123456"]["new"]

    syncs = client.get(f"/api/lms/links/{link}/syncs", headers=A).json()
    assert {s["kind"] for s in syncs} >= {"pool_push", "submission_pull", "grade_dry_run", "grade_push"}
    with Session() as db:
        push = db.scalar(select(LmsSync).where(LmsSync.kind == "grade_push").order_by(LmsSync.id))
        assert any(e["method"] == "PATCH" for e in push.request_log)  # every write logged


def test_chaos_retries_token_refresh_and_partial_failure(env, on, bb):  # noqa: F811
    client, Session = env
    cv, sec, form_id, link, _col = _linked_and_pulled(env, bb)
    _confirm_all(client, cv, sec, form_id)
    body = {"form_id": form_id, "dry_run": False}

    bb.fail_next = [429, 503, 500]          # rate limit + outages: retried with backoff
    bb.expire_tokens()                      # 401: refreshed with the refresh token, then saved
    bb.broken_users = {bb.studs[1]}         # one write keeps failing
    with Session() as db:
        before = db.scalar(select(LmsToken)).access_enc
    r = client.post(f"/api/lms/links/{link}/passback", headers=A, json=body).json()
    assert r["status"] == "partial" and r["summary"]["counts"]["written"] == 2
    failed = [x for x in r["summary"]["rows"] if x.get("result", "").startswith("failed")]
    assert len(failed) == 1 and failed[0]["student_id"] == "20235678"
    with Session() as db:
        assert db.scalar(select(LmsToken)).access_enc != before
    # After the fault clears, a re-run writes only what's missing.
    bb.broken_users = set()
    n = len(_patches(bb))
    r = client.post(f"/api/lms/links/{link}/passback", headers=A, json=body).json()
    assert r["status"] == "ok" and r["summary"]["counts"]["written"] == 1 and len(_patches(bb)) == n + 1


def test_mock_mode_connects_without_a_browser(env, on, monkeypatch):  # noqa: F811
    client, _ = env
    monkeypatch.setattr(get_settings(), "lms_mode", "mock")
    import app.lms.fake_blackboard as fbmod

    monkeypatch.setattr(fbmod, "_shared", None)
    locked(client, STAT100)
    assert client.post("/api/lms/connect", headers=A).json()["connected"] is True
    codes = {c["course_id"] for c in client.get("/api/lms/courses", headers=A).json()}
    assert codes == {"STAT100-F26-01", "MATH101-F26-01"}
