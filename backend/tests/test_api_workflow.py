"""Gate 1 workflow through the HTTP API: upload -> correct (logged) -> settle
flags -> lock -> revise / roll over."""

from __future__ import annotations

from sqlalchemy import select

from app import models
from app.llm.factory import set_provider_override
from app.llm.gateway import FakeProvider
from tests.synth.render import to_docx, to_pdf
from tests.synth.specs import CENG401, CENG411, CSCI372, STAT100, build

A = {"X-Dev-User": "a.faculty@example.edu", "X-Dev-Name": "Dr A"}
B = {"X-Dev-User": "b.faculty@example.edu", "X-Dev-Name": "Dr B"}


def upload(client, spec, fmt, headers=A, name=None):
    data = to_pdf(build(spec)) if fmt == "pdf" else to_docx(build(spec))
    mime = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    r = client.post("/api/syllabi", headers=headers, files={"file": (name or f"x.{fmt}", data, mime)})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "extract" and job["status"] == "done", job  # sync mode in tests
    assert client.get(f"/api/jobs/{job['id']}", headers=headers).json()["status"] == "done"
    v = client.get(f"/api/course-versions/{job['result']['course_version_id']}", headers=headers)
    assert v.status_code == 200, v.text
    return v.json()


def open_blocking(v):
    return [f for f in v["flags"] if f["status"] == "open" and f["severity"] in ("error", "warning")]


def test_requires_sign_in(env):
    client, _ = env
    assert client.get("/api/course-versions").status_code == 401


def test_upload_clean_syllabus_and_lock(env):
    client, Session = env
    v = upload(client, CSCI372, "pdf")
    assert v["status"] == "extracted"
    assert v["course_code"] == "CSCI 372" and v["term"] == "Spring 2026"
    assert v["can_lock"] is True

    r = client.post(f"/api/course-versions/{v['id']}/lock", headers=A)
    assert r.status_code == 200, r.text
    locked = r.json()
    assert locked["status"] == "locked" and locked["version_no"] == 1

    with Session() as db:
        cv = db.get(models.CourseVersion, v["id"])
        assert cv.course.code == "CSCI 372"
        assert len(db.scalars(select(models.CLO).where(models.CLO.course_version_id == cv.id)).all()) == 4
        assert len(db.scalars(select(models.Week).where(models.Week.course_version_id == cv.id)).all()) == 16
        assessments = db.scalars(select(models.Assessment).where(models.Assessment.course_version_id == cv.id)).all()
        hw1 = next(a for a in assessments if a.name == "HW1")
        assert hw1.weight_table_name == "Homework Assignments" and hw1.weight_pct == 10
        assert db.scalars(select(models.PLO).where(models.PLO.course_version_id == cv.id)).all()
        links = db.scalars(select(models.AssessmentCLO).where(models.AssessmentCLO.assessment_id == hw1.id)).all()
        assert {(l.source) for l in links} == {"weekly_schedule", "weight_matrix"}

    # Locked versions are read-only.
    r = client.patch(f"/api/course-versions/{v['id']}/record", headers=A,
                     json={"ops": [{"op": "replace", "path": "/course/title", "value": "X"}]})
    assert r.status_code == 409


def test_lock_blocked_until_flags_settled_and_edits_logged(env):
    client, _ = env
    v = upload(client, CENG411, "docx")
    vid = v["id"]
    assert v["can_lock"] is False
    r = client.post(f"/api/course-versions/{vid}/lock", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["items"]

    # Fix the V2 contradiction by editing the schedule's midterm weight to 25%.
    rec = v["record"]
    wi = next(i for i, w in enumerate(rec["weekly"]) if w["week_no"] == 8)
    r = client.patch(f"/api/course-versions/{vid}/record", headers=A, json={
        "ops": [{"op": "replace", "path": f"/weekly/{wi}/assessments/0/weight_pct", "value": 25}],
        "note": "Weight table is authoritative per the department."})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["status"] == "in_review"
    v2 = [f for f in v["flags"] if f["rule_id"] == "V2"]
    assert v2 and all(f["status"] == "cleared" for f in v2)

    edits = client.get(f"/api/course-versions/{vid}/edits", headers=A).json()
    assert edits[0]["old_value"] == 20 and edits[0]["new_value"] == 25 and edits[0]["edited_by"] == "Dr A"

    # Plan 1.13: dismissing takes an OPTIONAL note.
    err = next(f for f in open_blocking(v) if f["severity"] == "error")
    r = client.post(f"/api/course-versions/{vid}/flags/{err['id']}/resolve", headers=A, json={"action": "accept"})
    assert r.status_code == 200
    v = r.json()

    for f in open_blocking(v):
        r = client.post(f"/api/course-versions/{vid}/flags/{f['id']}/resolve", headers=A,
                        json={"action": "accept", "note": "Confirmed with the department."})
        assert r.status_code == 200, r.text
    v = r.json()
    assert v["can_lock"] is True
    assert client.post(f"/api/course-versions/{vid}/lock", headers=A).status_code == 200

    # Revise: new version in review, settlements carried over, still locked original.
    r = client.post(f"/api/course-versions/{vid}/revise", headers=A)
    assert r.status_code == 201
    nv = r.json()
    assert nv["status"] == "in_review" and nv["parent_version_id"] == vid
    assert nv["can_lock"] is True
    r = client.post(f"/api/course-versions/{nv['id']}/lock", headers=A)
    assert r.status_code == 200 and r.json()["version_no"] == 2
    assert client.get(f"/api/course-versions/{vid}", headers=A).json()["status"] == "superseded"


def test_invalid_edit_rejected_by_schema(env):
    client, _ = env
    v = upload(client, CSCI372, "pdf")
    r = client.patch(f"/api/course-versions/{v['id']}/record", headers=A,
                     json={"ops": [{"op": "replace", "path": "/clos/0/number", "value": "one"}]})
    assert r.status_code == 422
    r = client.patch(f"/api/course-versions/{v['id']}/record", headers=A,
                     json={"ops": [{"op": "replace", "path": "/nope", "value": 1}]})
    assert r.status_code == 422


def test_term_raw_edit_derives_term(env):
    client, _ = env
    v = upload(client, CSCI372, "pdf")
    r = client.patch(f"/api/course-versions/{v['id']}/record", headers=A,
                     json={"ops": [{"op": "replace", "path": "/offering/term_raw", "value": "Fall Semester 2027"}]})
    assert r.json()["record"]["offering"]["term"] == "Fall 2027"


def test_faculty_see_only_their_own(env):
    client, _ = env
    v = upload(client, CSCI372, "pdf")
    assert client.get(f"/api/course-versions/{v['id']}", headers=B).status_code == 404
    assert client.get("/api/course-versions", headers=B).json() == []


def test_second_faculty_cannot_supersede_anothers_lock(env):
    client, _ = env
    v = upload(client, CSCI372, "pdf")
    assert client.post(f"/api/course-versions/{v['id']}/lock", headers=A).status_code == 200
    w = upload(client, CSCI372, "pdf", headers=B)
    r = client.post(f"/api/course-versions/{w['id']}/lock", headers=B)
    assert r.status_code == 409 and "another faculty" in r.text


def test_rollover_to_next_term(env):
    client, _ = env
    v = upload(client, CSCI372, "pdf")
    client.post(f"/api/course-versions/{v['id']}/lock", headers=A)
    r = client.post(f"/api/course-versions/{v['id']}/rollover", headers=A, json={"term": "Spring 2027"})
    assert r.status_code == 201, r.text
    nv = r.json()
    assert nv["term"] == "Spring 2027" and nv["origin"] == "rollover"
    assert all(a["due_date"] is None for w in nv["record"]["weekly"] for a in w["assessments"])


def test_v11_uses_llm_gateway_and_logs_call(env):
    client, Session = env
    set_provider_override(FakeProvider({"validate.on_topic": {
        "description_on_topic": True, "additional_info_on_topic": False,
        "additional_info_reason": "Describes embedded systems design.", "other_subject": "embedded systems"}}))
    v = upload(client, CENG401, "pdf")
    v11 = [f for f in v["flags"] if f["rule_id"] == "V11"]
    assert len(v11) == 1 and "embedded systems" in v11[0]["message"] and "heuristic" not in v11[0]["message"]
    with Session() as db:
        calls = db.scalars(select(models.LLMCall)).all()
        assert len(calls) == 1 and calls[0].prompt_id == "validate.on_topic" and calls[0].prompt_version == "1"
        assert calls[0].model == "fake-1" and calls[0].ok


def test_coverage_report(env):
    client, _ = env
    v = upload(client, STAT100, "pdf")
    cov = client.get(f"/api/course-versions/{v['id']}/coverage", headers=A).json()
    assert len(cov["clos"]) == 5
    assert round(sum(c["weight_pct"] for c in cov["clos"])) == 100
    assert cov["programs"][0]["uncovered_plos"] == [1, 4]


def test_rejects_unsupported_file(env):
    client, _ = env
    r = client.post("/api/syllabi", headers=A, files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_choose_a_value_fixes_v2_and_is_logged(env):
    client, _ = env
    v = upload(client, CENG411, "docx")
    v2 = next(f for f in v["flags"] if f["rule_id"] == "V2")
    assert [c["label"] for c in v2["choices"]] == ["Use the weight table's 25%", "Use the schedule's 20%"]
    r = client.post(f"/api/course-versions/{v['id']}/flags/{v2['id']}/choose", headers=A, json={"choice": 0})
    assert r.status_code == 200, r.text
    after = next(f for f in r.json()["flags"] if f["id"] == v2["id"])
    assert after["status"] == "cleared"
    log = client.get(f"/api/course-versions/{v['id']}/edits.csv", headers=A)
    assert log.status_code == 200 and "text/csv" in log.headers["content-type"]
    assert "V2: Use the weight table's 25%" in log.text and "/weight_pct" in log.text


def test_new_upload_offers_carry_over_from_last_locked_version(env):
    client, _ = env
    first = upload(client, CENG411, "docx")
    for f in first["flags"]:
        if f["status"] == "open" and f["severity"] != "info":
            client.post(f"/api/course-versions/{first['id']}/flags/{f['id']}/resolve", headers=A,
                        json={"action": "accept", "note": "Department confirmed"})
    assert client.post(f"/api/course-versions/{first['id']}/lock", headers=A).status_code == 200

    second = upload(client, CENG411, "docx")  # the next term's syllabus arrives
    prev = second["previous"]
    assert prev["id"] == first["id"] and prev["matching_settled_flags"] > 0
    r = client.post(f"/api/course-versions/{second['id']}/carry-over", headers=A,
                    json={"from_version_id": first["id"]})
    v = r.json()
    carried = [f for f in v["flags"] if (f["resolution_note"] or "").startswith("Carried over")]
    assert len(carried) == prev["matching_settled_flags"]
    assert "Department confirmed" in carried[0]["resolution_note"]
    assert v["can_lock"] is True
