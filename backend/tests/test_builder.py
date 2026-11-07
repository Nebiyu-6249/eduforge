"""Phase 3: Assessment Builder (plan 3.1–3.12)."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

from app.config import get_settings
from app.llm.factory import set_provider_override
from app.llm.gateway import FakeProvider
from tests.synth.specs import STAT100
from tests.test_api_workflow import A, B
from tests.test_drafts import drafts_post, fake, judge, locked, mcq

STEMS = [
    ("Which statistic is the middle value of an ordered data set?", 1, 3),
    ("What does a histogram with a long right tail indicate about the mean and median?", 1, 2),
    ("If P(A) = 0.3 and P(B) = 0.5 for independent events, what is P(A and B)?", 2, 4),
    ("How many ways can a committee of 3 be chosen from 8 people?", 2, 5),
    ("What is the expected number of successes in a binomial experiment with n = 20 and p = 0.25?", 3, 6),
    ("What proportion of a normal distribution lies within one standard deviation of the mean?", 3, 7),
    ("Which describes the sampling distribution of the mean for large samples?", 1, 9),
    ("What happens to a confidence interval's width when the confidence level increases?", 2, 10),
]


def _bank(client, cv, n=len(STEMS)):
    """Approved MCQs spread over CLOs 1–3 and weeks 2–10."""
    ids = []
    for stem, clo, week in STEMS[:n]:
        fake({"mcq": {"items": [mcq(stem=stem, clo=clo, week=week)]}})
        it = drafts_post(client, cv, {"item_type": "mcq", "clo_numbers": [clo], "count": 1}).json()["items"][0]
        r = client.post(f"/api/drafts/{it['id']}/action", headers=A, json={"action": "approve"})
        assert r.status_code == 200, r.text
        ids.append(it["id"])
    return ids


def _bp(client, cv, **over):
    bp = client.get(f"/api/course-versions/{cv}/blueprint", headers=A, params={"name": "Midterm"}).json()
    bp.update({"types": {"mcq": 3}, "minutes": 0, **over})
    return bp


def test_blueprint_from_syllabus_row(env):
    client, _ = env
    cv = locked(client, STAT100)
    rows = client.get(f"/api/course-versions/{cv}/assessments", headers=A).json()
    assert {"Quiz 1", "Midterm", "HW2", "Final"} <= {r["name"] for r in rows}
    bp = client.get(f"/api/course-versions/{cv}/blueprint", headers=A, params={"name": "Midterm"}).json()
    assert bp["weeks"] == [1, 2, 3, 4, 5, 6, 7]          # due week 8, covers what came before
    assert set(bp["clo_shares"]) == {"1", "2", "3"}      # schedule ∪ matrix
    assert bp["minutes"] == 75 and bp["types"]["mcq"] == 12 and bp["weight_pct"] == 25


def test_build_parallel_versions_review_and_export(env):
    client, _ = env
    cv = locked(client, STAT100)
    _bank(client, cv)
    forms = client.post(f"/api/course-versions/{cv}/forms", headers=A,
                        json={"blueprint": _bp(client, cv), "versions": 2, "sections": ["S1", "S2"]}).json()
    a, b = forms
    ids_a, ids_b = {i["item_id"] for i in a["items"]}, {i["item_id"] for i in b["items"]}
    assert len(ids_a) == 3 and len(ids_b) == 3 and not ids_a & ids_b  # parallel, zero overlap
    assert all(i["week_no"] <= 7 for i in a["items"])                  # inside the blueprint's weeks
    assert sum(i["points"] for i in a["items"]) == 100
    assert a["coverage"]["types"]["mcq"] == {"have": 3, "want": 3}

    # Unapproved forms don't export; approve, then edits return it to draft (3.4).
    assert client.post(f"/api/forms/{a['id']}/export", headers=A, json={"format": "docx"}).status_code == 409
    order = [i["item_id"] for i in reversed(a["items"])]
    assert client.post(f"/api/forms/{a['id']}/edit", headers=A, json={"action": "approve"}).json()["status"] == "approved"
    f = client.post(f"/api/forms/{a['id']}/edit", headers=A, json={"action": "reorder", "item_ids": order}).json()
    assert f["status"] == "draft" and [i["item_id"] for i in f["items"]] == order
    client.post(f"/api/forms/{a['id']}/edit", headers=A, json={"action": "approve"})

    docx = client.post(f"/api/forms/{a['id']}/export", headers=A, json={"format": "docx", "include_answer_key": True})
    assert docx.status_code == 200 and "Midterm_A" in docx.headers["content-disposition"]
    q = client.post(f"/api/forms/{a['id']}/export", headers=A, json={"format": "qti"})
    z = zipfile.ZipFile(io.BytesIO(q.content))
    assert "imsmanifest.xml" in z.namelist() and "test.xml" in z.namelist()
    for n in z.namelist():
        ET.fromstring(z.read(n))  # every file is well-formed XML
    assert len([n for n in z.namelist() if n.startswith("items/")]) == 3

    # Usage history (3.5): the next build avoids items used this term and says so.
    again = client.post(f"/api/course-versions/{cv}/forms", headers=A,
                        json={"blueprint": _bp(client, cv), "versions": 1}).json()[0]
    assert not {i["item_id"] for i in again["items"]} & ids_a
    assert any("used in the last" in g.get("warning", "") for g in again["gaps"])


def test_gaps_are_reported(env):
    client, _ = env
    cv = locked(client, STAT100)
    _bank(client, cv, n=2)
    f = client.post(f"/api/course-versions/{cv}/forms", headers=A,
                    json={"blueprint": _bp(client, cv, types={"mcq": 5, "problem": 2}), "versions": 1}).json()[0]
    kinds = {(g.get("type"), g.get("count")) for g in f["gaps"] if "type" in g}
    assert ("mcq", 3) in kinds and ("problem", 2) in kinds
    assert f["coverage"]["meets_blueprint"] is False


def test_bank_import_text_and_qti_roundtrip(env):
    client, _ = env
    cv = locked(client, STAT100)
    text = (b"1. Which measure of spread uses every value in the data set?\n"
            b"A. Range\nB. Standard deviation\nC. Mode\nD. Median\nAnswer: B\n\n"
            b"2. A coin is tossed three times. What is the probability of exactly two heads?\n"
            b"A. 1/8\nB. 3/8\nC. 1/2\nD. 5/8\n\n"
            b"3. Explain the difference between a parameter and a statistic.\n")
    job = client.post(f"/api/course-versions/{cv}/bank-import", headers=A,
                      files={"file": ("old_quiz.txt", text, "text/plain")}).json()
    assert job["status"] == "done", job
    items = [client.get(f"/api/drafts/{i}", headers=A).json() for i in job["result"]["item_ids"]]
    assert [i["type"] for i in items] == ["mcq", "mcq", "short_answer"]
    assert items[0]["answer_key"]["correct"] == "B" and items[0]["status"] == "suggested"
    # No answer in the file: the key is left empty, so the schema check fails until faculty add it.
    s1 = {s["check"]: s for s in items[1]["scores"]}
    assert s1["schema"]["outcome"] == "fail" and items[1]["can_approve"] is False
    assert items[0]["clo_numbers"] and items[0]["model"] == "import"

    # Round trip: export the course's approved questions as QTI, import them back.
    client.post(f"/api/drafts/{items[0]['id']}/action", headers=A, json={"action": "approve"})
    pkg = client.post(f"/api/course-versions/{cv}/qti", headers=A).content
    job2 = client.post(f"/api/course-versions/{cv}/bank-import", headers=A,
                       files={"file": ("bank.zip", pkg, "application/zip")}).json()
    back = client.get(f"/api/drafts/{job2['result']['item_ids'][0]}", headers=A).json()
    assert back["answer_key"]["correct"] == "B" and "standard deviation" in str(back["body"]).lower()
    assert job2["result"]["duplicates"] == 1  # it's the same question as an existing item


def test_term_diff_marks_items_for_review(env):
    client, _ = env
    cv = locked(client, STAT100)
    ids = _bank(client, cv, n=3)  # CLO 1, 1, 2
    nv = client.post(f"/api/course-versions/{cv}/revise", headers=A).json()
    i = next(k for k, c in enumerate(nv["record"]["clos"]) if c["number"] == 2)
    client.patch(f"/api/course-versions/{nv['id']}/record", headers=A, json={"ops": [
        {"op": "replace", "path": f"/clos/{i}/text", "value": "Use simulation to estimate probabilities of events."}]})
    assert client.post(f"/api/course-versions/{nv['id']}/lock", headers=A).status_code == 200
    d = client.get(f"/api/course-versions/{nv['id']}/diff", headers=A).json()
    assert "2" in d["diff"]["clos_changed"] and d["affected_item_ids"] == [ids[2]]
    it = client.get(f"/api/drafts/{ids[2]}", headers=A).json()
    assert it["status"] == "needs_review" and it["events"][-1]["action"] == "needs_review"
    assert client.get(f"/api/drafts/{ids[0]}", headers=A).json()["status"] == "approved"
    # Re-approving puts it back into use.
    assert client.post(f"/api/drafts/{ids[2]}/action", headers=A, json={"action": "approve"}).status_code == 200


def test_solvability_check(env, monkeypatch):
    client, _ = env
    cv = locked(client, STAT100)
    item = {"tags": {"clo_numbers": [1], "week_no": 3, "bloom_level": "apply", "difficulty": "easy"},
            "body": {"language": "python", "prompt": "Write mean(xs).", "starter_code": "def mean(xs):\n    return 0\n",
                     "figure": None},
            "answer_key": {"solution_code": "def mean(xs):\n    return sum(xs) / len(xs)\n",
                           "tests_code": "def test_a():\n    assert mean([1, 2, 3]) == 2\n", "explanation": "x"},
            "feedback": {"hint": "h", "explanation": "e"}}
    fake({"code_exercise": {"items": [item]}})
    it = drafts_post(client, cv, {"item_type": "code_exercise", "clo_numbers": [1], "count": 1}).json()["items"][0]
    set_provider_override(FakeProvider({
        "solvability.solve": {"answer": "done", "code": "def mean(xs):\n    return sum(xs) / len(xs)\n"},
        "quality.judge": judge()}))
    job = client.post(f"/api/drafts/{it['id']}/solvability", headers=A).json()
    assert job["status"] == "done" and job["result"]["verdict"] == "trivial"
    res = client.get(f"/api/drafts/{it['id']}/solvability", headers=A).json()
    assert res[0]["suggestions"]  # AI-resistant variants suggested
    # A hosted model that may not see exam items is refused.
    monkeypatch.setattr(get_settings(), "llm_provider", "gemini")
    assert client.post(f"/api/drafts/{it['id']}/solvability", headers=A).status_code == 409


def test_shared_bank_membership(env):
    client, _ = env
    cv_a = locked(client, STAT100)
    ids = _bank(client, cv_a, n=2)
    assert client.post(f"/api/drafts/{ids[0]}/share", headers=A, json={"shared": True}).status_code == 204
    # B teaches the same course: lock their own version, then they see A's shared item.
    from tests.test_api_workflow import upload

    vb = upload(client, STAT100, "pdf", headers=B)
    for f in vb["flags"]:
        if f["status"] == "open" and f["severity"] != "info":
            client.post(f"/api/course-versions/{vb['id']}/flags/{f['id']}/resolve", headers=B, json={"action": "accept"})
    # 13.B is unresolved: B can't lock the same course+term while A's lock stands. Use another term.
    client.patch(f"/api/course-versions/{vb['id']}/record", headers=B,
                 json={"ops": [{"op": "replace", "path": "/offering/term_raw", "value": "Spring 2027"}]})
    vb2 = client.get(f"/api/course-versions/{vb['id']}", headers=B).json()
    for f in vb2["flags"]:
        if f["status"] == "open" and f["severity"] != "info":
            client.post(f"/api/course-versions/{vb['id']}/flags/{f['id']}/resolve", headers=B, json={"action": "accept"})
    assert client.post(f"/api/course-versions/{vb['id']}/lock", headers=B).status_code == 200
    bank = client.get(f"/api/course-versions/{vb['id']}/shared-bank", headers=B).json()
    assert [b["item_id"] for b in bank] == [ids[0]]
    # B can't share or open A's items directly.
    assert client.post(f"/api/drafts/{ids[1]}/share", headers=B, json={"shared": True}).status_code == 404
    assert client.get(f"/api/drafts/{ids[1]}", headers=B).status_code == 404


def test_program_coverage_and_qa_viewer(env, monkeypatch):
    client, _ = env
    cv = locked(client, STAT100)
    progs = client.get("/api/programs", headers=A).json()
    ge = next(p for p in progs if p["name"] == "General Education")
    cov = client.get(f"/api/programs/{ge['id']}/coverage", headers=A, params={"term": "Fall 2026"}).json()
    row = cov["courses"][0]
    assert row["code"] == "STAT 100" and row["cells"]["2"]["strength"] == "high" and cov["uncovered"] == [1, 4]

    qa = {"X-Dev-User": "qa.office@example.edu"}
    monkeypatch.setattr(get_settings(), "qa_viewer_emails", [qa["X-Dev-User"]])
    assert client.get(f"/api/qa/programs/{ge['id']}/coverage", headers=qa).status_code == 200
    assert client.get(f"/api/qa/syllabi/{cv}", headers=qa).json()["record"]["course"]["code"] == "STAT 100"
    # The viewer can never open items, exams or course versions through faculty endpoints.
    assert client.get(f"/api/course-versions/{cv}/drafts", headers=qa).status_code == 403
    assert client.get(f"/api/course-versions/{cv}", headers=qa).status_code == 403
    assert client.get("/api/auth/whoami", headers=qa).json()["role"] == "viewer"
    assert client.get("/api/qa/programs", headers=A).status_code == 403  # faculty aren't QA viewers
