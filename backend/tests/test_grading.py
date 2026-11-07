"""Phase 4: Grading & Feedback Assist (plan 4.1–4.13)."""

from __future__ import annotations

import csv
import io
import re
import zipfile

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import get_settings
from app.extraction.pipeline import extract
from app.grading import calibration as cal
from app.grading import identity, scoring
from app.grading.scale import letter_for, parse_scale, problems
from app.llm.factory import set_provider_override
from app.llm.gateway import FakeProvider, LLMGateway
from app.models import AssessmentForm, AuditEvent, Faculty, FormItem, Item, StudentIdentity
from app.validation.rules import validate
from tests.synth.render import to_docx
from tests.synth.specs import CSAI351, CSCI372, STAT100, build
from tests.test_api_workflow import A, B
from tests.test_drafts import locked

ROSTER = ("Student ID,Name,Email\n"
          "20231234,Mariam Al Hashimi,mariam.h@students.aurak.ac.ae\n"
          "20235678,Omar Khalid,omar.k@students.aurak.ac.ae\n"
          "B00123456,Will Turner,\n")
IDENTITY_STRINGS = ["Mariam", "Hashimi", "20231234", "mariam.h", "Omar", "Khalid", "20235678", "Turner",
                    "B00123456", "+971", "123 4567"]


@pytest.fixture()
def on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "grading_enabled", True)
    monkeypatch.setattr(s, "identity_key", Fernet.generate_key().decode())
    monkeypatch.setattr(s, "grading_llm_approved", True)
    monkeypatch.setattr(s, "sandbox_mode", "subprocess")  # no Docker in tests: student code must not run
    return s


def _item(db, cv_id, type_, body, key, clo=1, feedback=None):
    it = Item(course_version_id=cv_id, type=type_, status="approved", clo_ids=[clo], week_no=3, bloom_level="apply",
              difficulty="easy", body_json=body, answer_key_json=key, feedback_prompts_json=feedback, model="test",
              prompt_version="t")
    db.add(it)
    db.flush()
    return it


def _form(env, cv_id):
    """An approved 4-question quiz: MCQ (options shuffled so the key B shows as A), numeric problem,
    short answer, code exercise. 25 points each."""
    _, Session = env
    with Session() as db:
        me = db.scalar(select(Faculty).where(Faculty.email == A["X-Dev-User"]))
        mcq = _item(db, cv_id, "mcq", {"stem": "Which measure of center is most affected by outliers?", "options": [
            {"label": "A", "text": "The median"}, {"label": "B", "text": "The mean"},
            {"label": "C", "text": "The mode"}, {"label": "D", "text": "The IQR"}]},
            {"correct": "B", "why_correct": "The mean uses every value.", "why_others_wrong": {"A": "The median is resistant."}})
        prob = _item(db, cv_id, "problem", {"statement": "A sample of 25 has mean 52 and SD 5.", "given": [],
                                            "asks_for": "the t statistic for H0: mu = 50"},
                     {"solution_steps": ["SE = 1", "t = 2"], "final_answer_text": "t = 2", "numeric_answer": 2.0,
                      "tolerance": 0.01}, clo=2, feedback={"hint": "Standard error first.", "explanation": "."})
        sa = _item(db, cv_id, "short_answer", {"question": "Why is the mean sensitive to outliers?", "expected_length": "1-2 sentences"},
                   {"model_answer": "Because it uses every value.", "key_points": ["uses every value", "extreme values pull it"]})
        code = _item(db, cv_id, "code_exercise", {"language": "python", "prompt": "Write mean(xs).", "starter_code": "def mean(xs):\n    pass\n"},
                     {"solution_code": "def mean(xs):\n    return sum(xs)/len(xs)\n",
                      "tests_code": "def test_mean():\n    assert mean([1, 2, 3]) == 2\n", "explanation": "."}, clo=3)
        form = AssessmentForm(course_version_id=cv_id, assessment_name="Quiz 1", version_label="A", status="approved",
                              blueprint={}, created_by_id=me.id)
        db.add(form)
        db.flush()
        for pos, (it, order) in enumerate([(mcq, ["B", "A", "C", "D"]), (prob, None), (sa, None), (code, None)], 1):
            form.items.append(FormItem(item_id=it.id, position=pos, points=25.0, option_order=order))
        db.commit()
        return form.id, [mcq.id, prob.id, sa.id, code.id]


def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student ID", "Name", "Q1", "Q2", "Q3", "Q4"])
    w.writerows(rows)
    return buf.getvalue().encode()


def _rubric_fake(confidence=0.9, fake_quote=False) -> FakeProvider:
    def answer(user: str) -> dict:
        ans = user.split("<<<", 1)[1].split(">>>", 1)[0].strip()
        crits = re.findall(r"^- (Key point \d+|Method and working|Final answer|Answer)", user, re.M)
        words = ans.split()
        quote = " ".join(words[:4]) if words else ""
        out = [{"criterion": c, "level": "Full" if words else "None", "evidence": [quote] if words else [],
                "confidence": confidence} for c in crits]
        if fake_quote and out:
            out[0]["evidence"].append("a sentence the student never wrote")
        return {"criteria": out, "feedback": "Good use of the idea that every value counts; mention extreme values."}
    p = FakeProvider({"grading.rubric": answer})
    set_provider_override(p)
    return p


def _setup(env):
    client, _ = env
    cv = locked(client, STAT100)
    sec = client.post(f"/api/grading/course-versions/{cv}/sections", headers=A, json={"label": "S1"}).json()
    r = client.post(f"/api/grading/sections/{sec['id']}/roster", headers=A, files={"file": ("roster.csv", ROSTER, "text/csv")})
    assert r.status_code == 200, r.text
    form_id, items = _form(env, cv)
    return cv, sec["id"], form_id, items


def _grid(client, form_id, sec):
    return client.get(f"/api/grading/forms/{form_id}/sections/{sec}/grid", headers=A).json()


# --------------------------------------------------------------------------- #
def test_off_by_default(env):
    client, _ = env
    cv = locked(client, STAT100)
    assert client.get("/api/grading/status", headers=A).json()["enabled"] is False
    r = client.get(f"/api/grading/course-versions/{cv}/sections", headers=A)
    assert r.status_code == 403 and "data-protection" in r.json()["detail"]
    rec = extract("x.docx", to_docx(build(CSCI372)))
    assert not [f for f in validate(rec, run_v11=False) if f.rule_id == "V13"]  # D12: irrelevant until Phase 4


def test_scale_extraction_v13_and_confirmation(env, on):
    client, _ = env
    rec = extract("x.docx", to_docx(build(CSCI372)))
    assert [b.letter for b in rec.grading_scale][:3] == ["A", "A-", "B+"]
    v13 = [f.message for f in validate(rec, run_v11=False) if f.rule_id == "V13"]
    assert any("76–83" in m for m in v13) and any("66–73" in m for m in v13)  # the spec's scale has gaps
    assert letter_for(89.6, rec.grading_scale) == "B+" and letter_for(95, rec.grading_scale) == "A"
    assert problems(parse_scale(extract("x.docx", to_docx(build(STAT100))))) == []

    cv = locked(client, STAT100)
    locked(client, CSAI351)  # same term (Fall 2026), same scale
    view = client.get(f"/api/grading/course-versions/{cv}/scale", headers=A).json()
    assert view["problems"] == [] and view["others"] == [] and not view["confirmed"]
    bands = view["extracted"]
    gap = [dict(b) for b in bands]
    gap[1]["min_pct"] = 82  # B 82–89 and C 70–79: nothing covers 79–82
    r = client.post(f"/api/grading/course-versions/{cv}/scale", headers=A, json={"bands": gap})
    assert r.status_code == 422 and r.json()["detail"]["problems"]
    minus = [{"letter": "A", "min_pct": 95, "max_pct": 100}, {"letter": "A-", "min_pct": 90, "max_pct": 94},
             *[{**b} for b in bands[1:]]]
    r = client.post(f"/api/grading/course-versions/{cv}/scale", headers=A, json={"bands": minus})
    assert r.status_code == 409 and r.json()["detail"]["others"][0]["course"] == "CSAI 351"
    r = client.post(f"/api/grading/course-versions/{cv}/scale", headers=A,
                    json={"bands": minus, "acknowledge_difference": True})
    assert r.status_code == 200 and len(r.json()["confirmed"]) == 6 and "CSAI 351" in r.json()["note"]


def test_identities_encrypted_pseudonymised_and_reveal_logged(env, on):
    client, Session = env
    _cv, sec, form_id, _ = _setup(env)
    with Session() as db:
        blob = " ".join(f"{i.external_id_enc} {i.name_enc} {i.email_enc} {i.token_macs}" for i in db.scalars(select(StudentIdentity)))
    assert not any(s in blob for s in IDENTITY_STRINGS)  # nothing in the clear at rest
    plain = client.get(f"/api/grading/sections/{sec}/roster", headers=A).json()
    assert len(plain) == 3 and all(set(r) == {"pseudonym"} and r["pseudonym"].startswith("S-") for r in plain)
    full = client.get(f"/api/grading/sections/{sec}/roster", headers=A, params={"reveal": True}).json()
    assert {r["name"] for r in full} == {"Mariam Al Hashimi", "Omar Khalid", "Will Turner"}
    with Session() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "reidentify")) is not None
    # Only the course's faculty member: another faculty member sees nothing.
    assert client.get(f"/api/grading/sections/{sec}/roster", headers=B).status_code == 404
    assert client.get(f"/api/grading/forms/{form_id}/sections/{sec}/grid", headers=B).status_code == 404


def test_red_team_no_identity_reaches_the_model(env, on):
    client, Session = env
    _cv, sec, form_id, items = _setup(env)
    p = _rubric_fake()
    planted = ("Name: Mariam Al Hashimi\nThe mean uses every value, so extreme values pull it. My ID is 20231234, "
               "email mariam.h@students.aurak.ac.ae, phone +971 50 123 4567. I worked with Omar on this.")
    rows = [["20231234", "Mariam Al Hashimi", "A", "t = 2.00", planted, "def mean(xs): return 0"],
            ["B00123456", "Will Turner", "B", "2.5", "My name is Will Turner. The mean will change because it uses every value.", ""],
            ["20235678", "Omar Khalid", "The mean", "SE = 1 so t is 2 then t = 3", "OMAR KHALID: it uses every value", ""]]
    r = client.post(f"/api/grading/forms/{form_id}/sections/{sec}/submissions", headers=A,
                    files={"file": ("answers.csv", _csv(rows), "text/csv")})
    assert r.status_code == 202, r.text
    assert r.json()["redactions"] >= 7 and r.json()["job"]["status"] == "done"
    sent = " ".join(u + s for s, u in p.calls)
    assert p.calls, "the short answers should have gone to the model"
    leaked = [s for s in IDENTITY_STRINGS if s.lower() in sent.lower()]
    assert leaked == []  # 100% of planted identities stopped
    with Session() as db:  # Gate 4 audit trail
        run = db.scalar(select(AuditEvent).where(AuditEvent.action == "grading_run"))
        assert run is not None and run.detail["sent_to_model"] >= 1 and run.detail["model"].startswith("fake")
    stored = " ".join(client.get(f"/api/grading/submissions/{r['submission_id']}", headers=A).text
                      for r in _grid(client, form_id, sec)["rows"])
    assert "will change" in stored  # lower-case "will" kept: only capitalised name parts are redacted
    assert not [x for x in IDENTITY_STRINGS if x.lower() in stored.lower()]  # stored answers are clean too

    # Second line of defence: an unscrubbed identity is caught before the call and not sent.
    with Session() as db:
        from app.grading import service as svc
        from app.models import Section

        section = db.get(Section, sec)
        macs = svc.section_macs(db, section)
        form = db.get(AssessmentForm, form_id)
        fi = next(f for f in form.items if f.item_id == items[2])
        n = len(p.calls)
        sg = scoring.by_rubric(fi.item, fi, "Mariam thinks the mean uses every value", LLMGateway(p), macs)
        assert sg.method == "manual" and "Not sent" in (sg.note or "")
        assert identity.leaks("contact 20235678 please", macs) == ["student id"]
        assert len(p.calls) == n


def test_key_scoring_bulk_confirm_override_release_and_appeal(env, on):
    client, _Session = env
    cv, sec, form_id, items = _setup(env)
    _rubric_fake()
    rows = [["20231234", "Mariam Al Hashimi", "A", "t = 2.00", "Because it uses every value.", "def mean(xs): return 0"],
            ["B00123456", "Will Turner", "B", "2.5", "", ""],
            ["20235678", "Omar Khalid", "the mean", "SE = 2 so ... t = 2 is wrong, I get 3", "It uses every value.", ""]]
    client.post(f"/api/grading/forms/{form_id}/sections/{sec}/submissions", headers=A,
                files={"file": ("answers.csv", _csv(rows), "text/csv")})
    g = _grid(client, form_id, sec)
    mcq, prob, sa, code = (str(i) for i in items)
    by = {r["pseudonym"]: r for r in g["rows"]}
    # MCQ: "A" is right on this version (options shuffled), "B" wrong, the option text "the mean" right.
    assert sorted(r["cells"][mcq]["suggested"] for r in g["rows"]) == [0, 25, 25]
    assert all(r["cells"][mcq]["method"] == "key" and r["cells"][mcq]["confidence"] == 1 for r in g["rows"])
    # Numeric with tolerance: 2.00 right, 2.5 wrong; 2 in the working but 3 as the final answer is flagged.
    probs = sorted((r["cells"][prob]["suggested"], r["cells"][prob]["needs_faculty"]) for r in g["rows"])
    assert probs == [(0, False), (25, False), (25, True)]
    assert any(r["cells"][sa]["method"] == "key" and r["cells"][sa]["suggested"] == 25 for r in g["rows"])  # exact
    coded = [r["cells"][code] for r in g["rows"]]
    assert any(c["method"] == "manual" and "Docker" in c["note"] for c in coded)  # student code never runs unisolated

    # Bulk confirm takes only unflagged key-scored cells (4.10).
    n = client.post(f"/api/grading/forms/{form_id}/sections/{sec}/confirm-key", headers=A, json={}).json()["confirmed"]
    g = _grid(client, form_id, sec)
    done = [c for r in g["rows"] for c in r["cells"].values() if c["confirmed"] is not None]
    left = [c for r in g["rows"] for c in r["cells"].values() if c["confirmed"] is None]
    assert n == len(done) == 9 and all(c["method"] == "key" and not c["needs_faculty"] for c in done)
    assert {c["method"] for c in left} == {"key", "llm", "manual"} and len(left) == 3
    assert any("aren't confirmed" in b for b in g["blockers"]) and any("grading scale" in b for b in g["blockers"])
    assert client.post(f"/api/grading/forms/{form_id}/sections/{sec}/release", headers=A).status_code == 409

    # Changing a high-confidence suggestion by more than one level needs a reason (4.10).
    llm_cell = next(c for c in left if c["method"] == "llm")
    assert llm_cell["suggested"] == 25 and llm_cell["level_step"] == 6.25
    r = client.post(f"/api/grading/scores/{llm_cell['id']}/confirm", headers=A, json={"points": 10})
    assert r.status_code == 422 and "reason" in r.json()["detail"]
    assert client.post(f"/api/grading/scores/{llm_cell['id']}/confirm", headers=A,
                       json={"points": 10, "reason": "Misses extreme values."}).status_code == 200
    for c in left:
        if c["id"] != llm_cell["id"]:
            rr = client.post(f"/api/grading/scores/{c['id']}/confirm", headers=A, json={"points": 20, "reason": "Checked."})
            assert rr.status_code == 200, rr.text
    view = client.get(f"/api/grading/course-versions/{cv}/scale", headers=A).json()
    client.post(f"/api/grading/course-versions/{cv}/scale", headers=A, json={"bands": view["extracted"]})
    g = _grid(client, form_id, sec)
    assert g["blockers"] == [] and all(r["confirmed_total"] is not None for r in g["rows"])

    # Feedback: approve one item draft and one summary; everything else stays out of the release.
    sub_id = by[next(iter(by))]["submission_id"]
    detail = client.get(f"/api/grading/submissions/{sub_id}", headers=A).json()
    summary = next(f for f in detail["feedback"] if f["item_id"] is None)
    client.post(f"/api/grading/feedback/{summary['id']}", headers=A, json={"action": "approve"})
    unapproved = [f["text"] for d in (client.get(f"/api/grading/submissions/{r['submission_id']}", headers=A).json()
                                      for r in g["rows"]) for f in d["feedback"] if f["status"] != "approved"]

    rel = client.post(f"/api/grading/forms/{form_id}/sections/{sec}/release", headers=A)
    assert rel.status_code == 200, rel.text
    z = zipfile.ZipFile(io.BytesIO(rel.content))
    gc = z.read("grade_center.csv").decode()
    assert "Quiz 1 A [Total Pts: 100 Score]" in gc and "20231234" in gc and "Hashimi" in gc
    assert summary["text"] in gc
    assert not any(t and t in gc for t in unapproved if t != summary["text"])
    assert len([n for n in z.namelist() if n.startswith("feedback/")]) == 3
    assert "Letter" in z.read("marks_detail.csv").decode()

    # After release a confirmed mark changes only through an appeal, with history.
    assert client.post(f"/api/grading/scores/{llm_cell['id']}/confirm", headers=A,
                       json={"points": 25, "reason": "x"}).status_code == 409
    ap = client.post(f"/api/grading/submissions/{sub_id}/appeals", headers=A,
                     json={"item_id": int(mcq), "reason": "Student says option A was right."}).json()
    d = client.post(f"/api/grading/appeals/{ap['id']}/decide", headers=A,
                    json={"outcome": "Re-marked.", "points": {mcq: 25}}).json()
    assert d["status"] in {"changed", "upheld"}
    hist = client.get(f"/api/grading/submissions/{sub_id}", headers=A).json()
    assert hist["appeals"][0]["status"] == d["status"]
    cell = next(a["score"] for a in hist["answers"] if a["item_id"] == int(mcq))
    assert cell["confirmed"] == 25 and len(cell["history"]) >= 1
    assert client.get(f"/api/grading/forms/{form_id}/sections/{sec}/releases", headers=A).json()[0]["students"] == 3


def test_rubric_suggestions_carry_verified_evidence(env, on):
    client, _ = env
    _cv, sec, form_id, items = _setup(env)
    _rubric_fake(confidence=0.9, fake_quote=True)
    rows = [["20231234", "", "", "", "Extreme values pull the mean since it uses every value.", ""]]
    client.post(f"/api/grading/forms/{form_id}/sections/{sec}/submissions", headers=A,
                files={"file": ("answers.csv", _csv(rows), "text/csv")})
    sub = _grid(client, form_id, sec)["rows"][0]
    d = client.get(f"/api/grading/submissions/{sub['submission_id']}", headers=A).json()
    sa = next(a for a in d["answers"] if a["item_id"] == items[2])["score"]
    assert sa["method"] == "llm" and sa["suggested"] == 25 and sa["confidence"] == 0.9
    assert all(c["evidence"] and "never wrote" not in " ".join(c["evidence"]) for c in sa["criteria"])
    assert "dropped" in sa["note"]  # the invented quote was removed and noted
    fb = [f for f in d["feedback"] if f["item_id"] == items[2]]
    assert fb and fb[0]["status"] == "suggested" and fb[0]["source"] == "llm"

    _rubric_fake(confidence=0.3)
    client.post(f"/api/grading/forms/{form_id}/sections/{sec}/score", headers=A, json={"rescore": True})
    d = client.get(f"/api/grading/submissions/{sub['submission_id']}", headers=A).json()
    sa = next(a for a in d["answers"] if a["item_id"] == items[2])["score"]
    assert sa["needs_faculty"] is True  # low confidence -> "needs faculty"


def test_no_model_approved_means_no_suggestion(env, on, monkeypatch):
    client, _ = env
    monkeypatch.setattr(on, "grading_llm_approved", False)
    p = _rubric_fake()
    _cv, sec, form_id, items = _setup(env)
    client.post(f"/api/grading/forms/{form_id}/sections/{sec}/submissions", headers=A,
                files={"file": ("a.csv", _csv([["20231234", "", "A", "2", "It uses every value of the data", ""]]), "text/csv")})
    row = _grid(client, form_id, sec)["rows"][0]
    assert row["cells"][str(items[2])]["method"] == "manual" and not [c for c in p.calls if "<<<" in c[1]]
    assert row["cells"][str(items[0])]["suggested"] == 25  # key scoring needs no model


def test_file_intake_and_outliers(env, on):
    client, _ = env
    _cv, sec, form_id, items = _setup(env)
    _rubric_fake()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20231234_quiz.txt", "Q1: A\nQ2: t = 2\nQ3: It uses every value.\nQ4: def mean(xs): ...")
        z.writestr("B00123456.txt", "1. A\n2) 2\n3. It uses every value.\n")
        z.writestr("stranger_99.txt", "Q1: C")
    r = client.post(f"/api/grading/forms/{form_id}/sections/{sec}/submissions", headers=A,
                    files={"file": ("subs.zip", buf.getvalue(), "application/zip")}).json()
    assert r["submissions"] == 2 and r["unmatched_files"] == ["stranger_99.txt"]
    g = _grid(client, form_id, sec)
    assert all(row["cells"][str(items[0])]["suggested"] == 25 for row in g["rows"])
    # Same answer, different confirmed mark -> listed as an outlier (4.8).
    a, b = (row["cells"][str(items[2])]["id"] for row in g["rows"])
    client.post(f"/api/grading/scores/{a}/confirm", headers=A, json={"points": 25})
    client.post(f"/api/grading/scores/{b}/confirm", headers=A, json={"points": 5, "reason": "Too brief."})
    out = _grid(client, form_id, sec)["outliers"]
    assert any(o["item_id"] == items[2] and o["identical"] for o in out)


def test_calibration_harness(env, on):
    client, _ = env
    _cv, _sec, form_id, _items = _setup(env)
    _rubric_fake()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student ID", "Q1", "Q2", "Q3", "Q4", "M1", "M2", "M3", "M4"])
    w.writerow(["C001", "A", "2", "It uses every value of the sample.", "", 25, 25, 25, 0])
    w.writerow(["C002", "B", "7", "Extreme values pull it.", "", 0, 0, 12.5, 0])
    w.writerow(["C003", "A", "2.0", "It uses every value.", "", 25, 25, 25, 0])
    r = client.post(f"/api/grading/forms/{form_id}/calibration", headers=A,
                    files={"file": ("cal.csv", buf.getvalue().encode(), "text/csv")}, data={"description": "Fall 2027 pilot"})
    assert r.status_code == 202, r.text
    rep = client.get(f"/api/grading/forms/{form_id}/calibration", headers=A).json()[0]
    assert rep["report"]["key-scored"]["exact"] == 1.0  # 100% match with the key
    assert rep["report"]["all"]["n"] == 12
    assert rep["report"]["short_answer"]["suggested"] == 3
    # Calibration sets are never released.
    g = _grid(client, form_id, rep["section_id"])
    assert any("calibration" in b for b in g["blockers"])
    print(cal.table(rep["report"]))


def test_qwk_and_table():
    assert cal.qwk([0, 1, 2, 2], [0, 1, 2, 2]) == 1.0
    assert cal.qwk([0, 0, 2, 2], [2, 2, 0, 0]) < 0
    rows = cal.report([cal.Pair("mcq", "key", 1, 1, 1, 1, 3), cal.Pair("short_answer", "llm", 2, 1, 4, 1, 40)])
    assert rows["key-scored"]["exact"] == 1.0 and rows["short_answer"]["within_one"] == 1.0
    assert "within_one" in cal.table(rows)
