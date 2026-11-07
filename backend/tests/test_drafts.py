"""Draft Studio, quality checks, Faculty Review (gate 2) and export."""

from __future__ import annotations

import io
import json

import pytest
from docx import Document
from sqlalchemy import select

from app import models
from app.drafts import bloom
from app.drafts.prompts import GEN_PROMPT_VERSION
from app.drafts.safe_eval import UnsafeExpression, evaluate
from app.llm.factory import set_provider_override
from app.llm.gateway import FakeProvider
from tests.synth.specs import CENG411, STAT100
from tests.test_api_workflow import A, B, upload

# --------------------------------------------------------------------------- #
# Fake model outputs
# --------------------------------------------------------------------------- #


def mcq(stem="Which measure of center is most affected by outliers?", correct="B", clo=1, week=3):
    return {
        "tags": {"clo_numbers": [clo], "week_no": week, "bloom_level": "understand", "difficulty": "easy"},
        "body": {"stem": stem, "options": [
            {"label": "A", "text": "The median"}, {"label": "B", "text": "The mean"},
            {"label": "C", "text": "The mode"}, {"label": "D", "text": "The interquartile range"}]},
        "answer_key": {"correct": correct, "why_correct": "The mean uses every value.",
                       "why_others_wrong": {"A": "Resistant.", "C": "Most frequent value.", "D": "A spread measure."}},
        "feedback": {"hint": "Think about which statistic uses every value.", "explanation": "Outliers pull the mean."},
    }


def problem(numeric=2.0, expr="(x_bar - mu) / (s / sqrt(n))"):
    return {
        "tags": {"clo_numbers": [4], "week_no": 12, "bloom_level": "apply", "difficulty": "medium"},
        "body": {"statement": "A sample of 25 has mean 52 and SD 5. Test H0: mu = 50.",
                 "given": [{"name": "x_bar", "value": 52}, {"name": "mu", "value": 50},
                           {"name": "s", "value": 5}, {"name": "n", "value": 25}],
                 "asks_for": "the t statistic"},
        "answer_key": {"solution_steps": ["SE = 5/5 = 1", "t = (52-50)/1 = 2"], "final_answer_text": "t = 2",
                       "numeric_answer": numeric, "answer_expression": expr, "tolerance": 0.01},
        "feedback": {"hint": "Standard error first.", "explanation": "t = (x̄ − μ)/(s/√n)."},
    }


def judge(score=5):
    return {"clo_alignment": score, "clo_alignment_reason": "Directly assesses the CLO.", "bloom_fit": score,
            "bloom_fit_reason": "Matches.", "observed_bloom_level": "understand"}


def fake(gen: dict[str, object], resolve="B", judge_score=5) -> FakeProvider:
    responses = {f"generate.{k}": v for k, v in gen.items()}
    responses["quality.judge"] = judge(judge_score)
    responses["quality.resolve_mcq"] = {"answer": resolve, "confident": True, "problem": None}
    p = FakeProvider(responses)
    set_provider_override(p)
    return p


def locked(client, spec, fmt="pdf"):
    v = upload(client, spec, fmt)
    for f in v["flags"]:
        if f["status"] == "open" and f["severity"] != "info":
            client.post(f"/api/course-versions/{v['id']}/flags/{f['id']}/resolve", headers=A,
                        json={"action": "accept", "note": "Checked."})
    r = client.post(f"/api/course-versions/{v['id']}/lock", headers=A)
    assert r.status_code == 200, r.text
    return v["id"]


class _Resp:
    """The generate endpoint returns a job; tests read its outcome like a response."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code, self._body = status_code, body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


def drafts_post(client, cv, body):
    r = client.post(f"/api/course-versions/{cv}/drafts", headers=A, json=body)
    if r.status_code != 202:
        return r  # refused before queueing
    job = r.json()
    if job["status"] == "failed":
        return _Resp(job["error_status"], {"detail": job["error"]})
    items = [client.get(f"/api/drafts/{i}", headers=A).json() for i in job["result"]["item_ids"]]
    return _Resp(201, {"request_id": job["result"]["request_id"], "items": items})


def gen(client, cv, **kw):
    return drafts_post(client, cv, {"item_type": "mcq", "clo_numbers": [1], "count": 1, **kw})


def scores(item):
    return {s["check"]: s for s in item["scores"]}


# --------------------------------------------------------------------------- #

def test_generation_requires_locked_version(env):
    client, _ = env
    fake({"mcq": {"items": [mcq()]}})
    v = upload(client, STAT100, "pdf")
    r = gen(client, v["id"])
    assert r.status_code == 409 and "locked" in r.text


def test_no_llm_configured_gives_503_and_keeps_failed_request(env):
    client, Session = env
    cv = locked(client, STAT100)
    set_provider_override(None)
    r = gen(client, cv)
    assert r.status_code == 503
    with Session() as db:
        req = db.scalars(select(models.GenerationRequest)).one()
        assert req.status == "failed"


def test_mcq_generation_tags_checks_and_logging(env):
    client, Session = env
    cv = locked(client, STAT100)
    p = fake({"mcq": {"items": [mcq(), mcq(stem="Which plot shows the five-number summary?", correct="B")]}})
    r = gen(client, cv, count=2, weeks=[3])
    assert r.status_code == 201, r.text
    items = r.json()["items"]
    assert len(items) == 2
    it = items[0]
    assert it["status"] == "suggested" and it["grounded"] is False
    assert it["model"] == "fake:fake-1" and it["prompt_version"] == f"generate.mcq@{GEN_PROMPT_VERSION}"
    s = scores(it)
    assert s["schema"]["outcome"] == "pass" and s["clo_exists"]["outcome"] == "pass"
    assert s["answer_key"]["outcome"] == "pass" and s["clo_alignment"]["outcome"] == "pass"
    assert it["can_approve"] is True
    # The prompt carried the locked syllabus context and the target week.
    _, user = p.calls[0]
    assert "CLO 1: Organize, summarize and display data" in user and "* Week 3:" in user
    assert "ungrounded" in user
    with Session() as db:
        ids = {c.prompt_id for c in db.scalars(select(models.LLMCall)).all()}
        assert {"generate.mcq", "quality.judge", "quality.resolve_mcq"} <= ids


def test_mcq_key_disagreeing_with_resolve_blocks_approval(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq(correct="A")]}}, resolve="B")
    it = gen(client, cv).json()["items"][0]
    assert scores(it)["answer_key"]["outcome"] == "fail"
    assert it["can_approve"] is False
    r = client.post(f"/api/drafts/{it['id']}/action", headers=A, json={"action": "approve"})
    assert r.status_code == 409


def test_unknown_clo_fails_rule_check(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq(clo=9)]}})
    it = gen(client, cv).json()["items"][0]
    assert scores(it)["clo_exists"]["outcome"] == "fail"


def test_numeric_key_recomputed_and_fixed_by_edit(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"problem": {"items": [problem(numeric=2.5)]}})
    it = drafts_post(client, cv, {"item_type": "problem", "clo_numbers": [4], "count": 1}).json()["items"][0]
    s = scores(it)["answer_key"]
    assert s["outcome"] == "fail" and "= 2" in s["detail"] and "2.5" in s["detail"]

    key = dict(it["answer_key"], numeric_answer=2.0)
    r = client.patch(f"/api/drafts/{it['id']}", headers=A, json={"answer_key": key, "notes": "Fixed the key."})
    assert r.status_code == 200, r.text
    it = r.json()
    assert it["status"] == "under_review" and scores(it)["answer_key"]["outcome"] == "pass"
    assert it["revision_count"] == 2
    r = client.post(f"/api/drafts/{it['id']}/action", headers=A, json={"action": "approve"})
    assert r.status_code == 200 and r.json()["item"]["status"] == "approved"
    assert r.json()["item"]["approved_by"] == "Dr A"


def test_edit_returns_approved_item_to_review(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq()]}})
    it = gen(client, cv).json()["items"][0]
    client.post(f"/api/drafts/{it['id']}/action", headers=A, json={"action": "approve"})
    body = dict(it["body"], stem="Which summary statistic is most sensitive to outliers?")
    it = client.patch(f"/api/drafts/{it['id']}", headers=A, json={"body": body}).json()
    assert it["status"] == "under_review" and it["approved_by"] is None


def test_invalid_edit_rejected(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq()]}})
    it = gen(client, cv).json()["items"][0]
    r = client.patch(f"/api/drafts/{it['id']}", headers=A, json={"body": {"stem": "x", "options": []}})
    assert r.status_code == 422


def test_skills_clo_gets_no_mcq(env):
    client, _ = env
    cv = locked(client, CENG411, "docx")
    fake({"mcq": {"items": [mcq(clo=5)]}})
    r = gen(client, cv, clo_numbers=[5])
    assert r.status_code == 422 and "skills outcome" in r.text


def test_reject_and_regenerate_with_notes(env):
    client, _ = env
    cv = locked(client, STAT100)
    p = fake({"mcq": {"items": [mcq()]}})
    it = gen(client, cv).json()["items"][0]
    r = client.post(f"/api/drafts/{it['id']}/action", headers=A, json={"action": "regenerate"})
    assert r.status_code == 422  # notes required
    r = client.post(f"/api/drafts/{it['id']}/action", headers=A,
                    json={"action": "regenerate", "notes": "Use a real dataset context, not a generic one."})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["item"]["status"] == "rejected"
    job = out["job"]
    assert job["kind"] == "regenerate" and job["status"] == "done", job
    new = client.get(f"/api/drafts/{job['result']['item_ids'][0]}", headers=A).json()
    assert new["parent_item_id"] == it["id"] and new["status"] == "suggested"
    gen_calls = [u for _, u in p.calls if "REQUEST" in u]
    assert "Use a real dataset context" in gen_calls[-1] and "Rejected draft" in gen_calls[-1]


def test_duplicates_are_flagged(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq(), mcq()]}})
    items = gen(client, cv, count=2).json()["items"]
    assert scores(items[1])["duplicate"]["outcome"] == "warn"


def test_other_faculty_cannot_touch_items(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq()]}})
    it = gen(client, cv).json()["items"][0]
    assert client.get(f"/api/drafts/{it['id']}", headers=B).status_code == 404
    assert client.post(f"/api/drafts/{it['id']}/action", headers=B, json={"action": "approve"}).status_code == 404


def test_export_only_approved(env):
    client, Session = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq(), mcq(stem="Which display best shows the shape of a distribution?")]},
          "problem": {"items": [problem()]}})
    a, b = gen(client, cv, count=2).json()["items"]
    pr = drafts_post(client, cv, {"item_type": "problem", "clo_numbers": [4], "count": 1}).json()["items"][0]

    r = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "docx"})
    assert r.status_code == 409  # nothing approved yet
    for x in (a, pr):
        assert client.post(f"/api/drafts/{x['id']}/action", headers=A, json={"action": "approve"}).status_code == 200

    r = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "docx", "item_ids": [a["id"], b["id"]]})
    assert r.status_code == 409 and str(b["id"]) in r.text

    r = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "docx"})
    assert r.status_code == 200
    text = "\n".join(p.text for p in Document(io.BytesIO(r.content)).paragraphs)
    assert a["body"]["stem"] in text and b["body"]["stem"] not in text
    assert 'filename="STAT100_Fall2026_question_paper.docx"' in r.headers["content-disposition"]

    r = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "pdf", "part": "key"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert 'filename="STAT100_Fall2026_answer_key.pdf"' in r.headers["content-disposition"]
    with Session() as db:
        assert len(db.scalars(select(models.Export)).all()) == 2


def test_question_paper_and_answer_key_are_separate_files(env):
    """The paper carries no answers and no CLO/week/Bloom tags; the key carries
    the correct option, the explanation, the per-option rationale and the tags."""
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq()]}, "problem": {"items": [problem()]}})
    item = gen(client, cv).json()["items"][0]
    pr = drafts_post(client, cv, {"item_type": "problem", "clo_numbers": [4], "count": 1}).json()["items"][0]
    for x in (item, pr):
        assert client.post(f"/api/drafts/{x['id']}/action", headers=A, json={"action": "approve"}).status_code == 200

    def paragraphs(part: str) -> list[str]:
        r = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "docx", "part": part})
        assert r.status_code == 200, r.text
        return [p.text for p in Document(io.BytesIO(r.content)).paragraphs]

    paper = paragraphs("paper")
    joined = "\n".join(paper)
    assert "STAT 100 Introduction to Probability and Statistics" in joined
    assert "Fall 2026" in joined
    assert "Name: " in joined and "Student ID: " in joined
    assert item["body"]["stem"] in joined
    # MCQ options are a lettered list, not bullets.
    assert "A.\tThe median" in paper and "B.\tThe mean" in paper
    # Nothing from the answer key or the faculty tags reaches the paper.
    assert "The mean uses every value." not in joined
    assert "Correct answer" not in joined
    assert "t = 2" not in joined
    assert "Outcome 1" not in joined and "Understand" not in joined
    assert "Answer key" not in joined
    assert "approved by" not in joined

    key = "\n".join(paragraphs("key"))
    assert "Answer key" in key
    assert "Correct answer: B" in key
    assert "The mean uses every value." in key  # the explanation
    assert "Resistant." in key and "A.\tResistant." in paragraphs("key")  # per-option rationale
    assert "Outcome 1 · Week 3 · Understand · easy" in key  # the tags, in the tool's own words
    assert "t = 2" in key
    assert "approved by Dr A" in key


def test_export_rejects_an_unknown_part(env):
    client, _ = env
    cv = locked(client, STAT100)
    r = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "docx", "part": "both"})
    assert r.status_code == 422


@pytest.mark.parametrize("item_type,payload", [
    ("practice_set", {"tags": {"clo_numbers": [2], "week_no": 4, "bloom_level": "apply", "difficulty": "easy"},
                      "body": {"title": "Probability rules", "instructions": "Show your work.",
                               "exercises": [{"prompt": "P(A or B)?", "answer": "0.7", "hint": ""},
                                             {"prompt": "P(A and B)?", "answer": "0.1", "hint": ""}]},
                      "feedback": {"hint": "Addition rule.", "explanation": "Subtract the overlap."}}),
    ("lesson_plan", {"tags": {"clo_numbers": [3], "week_no": 6, "bloom_level": "apply", "difficulty": "medium"},
                     "body": {"title": "The binomial distribution", "session_minutes": 75,
                              "objectives": ["Compute binomial probabilities"],
                              "activities": [{"name": "Warm-up", "minutes": 10, "description": "Coin flips",
                                              "clo_numbers": [3]},
                                             {"name": "Worked examples", "minutes": 70, "description": "…",
                                              "clo_numbers": [3]}],
                              "check_for_understanding": "Exit ticket"}}),
    ("rubric", {"tags": {"clo_numbers": [5], "week_no": None, "bloom_level": "evaluate", "difficulty": "medium"},
                "body": {"title": "Regression report", "task": "Write a short report.",
                         "criteria": [{"criterion": "Model fit", "clo_numbers": [5],
                                       "levels": [{"label": "Excellent", "points": 4, "descriptor": "…"},
                                                  {"label": "Weak", "points": 1, "descriptor": "…"}]}]}}),
])
def test_other_types_generate_and_check(env, item_type, payload):
    client, _ = env
    cv = locked(client, STAT100)
    fake({item_type: {"items": [payload]}})
    r = drafts_post(client, cv, {"item_type": item_type, "clo_numbers": payload["tags"]["clo_numbers"], "count": 1})
    assert r.status_code == 201, r.text
    s = scores(r.json()["items"][0])
    assert s["schema"]["outcome"] == "pass"
    if item_type == "lesson_plan":
        assert s["structure"]["outcome"] == "fail" and "80 min" in s["structure"]["detail"]


def test_bad_model_output_is_retried_then_fails(env):
    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": "not json at all"})
    r = gen(client, cv)
    assert r.status_code == 502


# --------------------------------------------------------------------------- #

def test_safe_eval():
    assert evaluate("(x_bar - mu) / (s / sqrt(n))", {"x_bar": 52, "mu": 50, "s": 5, "n": 25}) == 2.0
    assert evaluate("comb(5, 2) * 0.5**5", {}) == pytest.approx(0.3125)
    assert evaluate("2^3", {}) == 8
    for bad in ["__import__('os')", "x.__class__", "open('f')", "[1,2]", "2**100000", "lambda: 1", "y + 1"]:
        with pytest.raises(UnsafeExpression):
            evaluate(bad, {"x": 1})


def test_bloom_and_skills():
    assert bloom.clo_level("Construct confidence intervals and perform hypothesis tests") == "apply"
    assert bloom.clo_level("Design software architectures and model systems using UML diagrams") == "create"
    assert bloom.clo_level("Explain software process models") == "understand"
    assert bloom.is_skills_clo(CENG411["clos"][4])
    assert not bloom.is_skills_clo(STAT100["clos"][0])
    assert json.dumps(bloom.LEVELS)


def test_team_metrics(env, monkeypatch):
    from app.config import get_settings

    client, _ = env
    cv = locked(client, STAT100)
    fake({"mcq": {"items": [mcq(), mcq(stem="Which display best shows the shape of a distribution?")]}})
    a, b = gen(client, cv, count=2).json()["items"]
    # a: approved untouched; b: edited then approved
    client.post(f"/api/drafts/{a['id']}/action", headers=A, json={"action": "approve"})
    body = dict(b["body"], stem="Which graph best shows the overall shape of a distribution of exam scores?")
    client.patch(f"/api/drafts/{b['id']}", headers=A, json={"body": body})
    client.post(f"/api/drafts/{b['id']}/action", headers=A, json={"action": "approve"})

    assert client.get("/api/team/metrics", headers=A).status_code == 403  # faculty don't see it
    monkeypatch.setattr(get_settings(), "team_emails", [A["X-Dev-User"]])
    assert client.get("/api/me", headers=A).json()["is_team"] is True
    m = client.get("/api/team/metrics", headers=A).json()
    o = m["overall"]
    assert o["drafts"] == 2 and o["approved"] == 2 and o["approval_rate"] == 1.0
    g = m["by_group"][0]
    assert g["type"] == "mcq" and g["course"] == "STAT 100" and g["prompt_version"] == f"generate.mcq@{GEN_PROMPT_VERSION}"
    assert 0 < o["median_edit_size"] < 0.2 and o["light_edit_rate"] == 1.0


def test_mcq_bloom_is_capped_at_analyze(env):
    """An MCQ cannot evidence 'evaluate' or 'create' (the first export of this
    tool had eight MCQs all tagged 'create'). A CLO above the cap is aimed one
    level down; asking for a higher level outright is refused with the reason."""
    client, _ = env
    cv = locked(client, STAT100)
    types = {t["type"]: t for t in client.get("/api/draft-types", headers=A).json()}
    assert types["mcq"]["max_bloom"] == "analyze"
    assert types["case_study"]["max_bloom"] is None

    r = client.post(f"/api/course-versions/{cv}/drafts", headers=A,
                    json={"item_type": "mcq", "clo_numbers": [1], "count": 1, "bloom_level": "create"})
    assert r.status_code == 422 and "analyze" in r.text

    # A rubric for the same CLO is not capped.
    fake({"rubric": {"items": [rubric()]}})
    r = client.post(f"/api/course-versions/{cv}/drafts", headers=A,
                    json={"item_type": "rubric", "clo_numbers": [1], "count": 1, "bloom_level": "create"})
    assert r.status_code == 202, r.text


def rubric():
    return {
        "tags": {"clo_numbers": [1], "week_no": 2, "bloom_level": "create", "difficulty": "medium"},
        "body": {"title": "Data summary report", "task": "Summarise a dataset for a non-specialist.",
                 "criteria": [{"criterion": "Choice of statistics",
                               "levels": [{"label": "Strong", "points": 4, "descriptor": "Fits the data type."},
                                          {"label": "Adequate", "points": 2, "descriptor": "Mostly fits."},
                                          {"label": "Weak", "points": 0, "descriptor": "Does not fit."}]}]},
    }


def test_derived_mcq_bloom_drops_to_the_cap(env):
    """CLO 5 of STAT 100 leads with 'Apply', so force a higher CLO level through
    the request form instead: no explicit level, a 'create'-level CLO."""
    from app.drafts import bloom
    from app.drafts import service as draft_svc
    from app.models import CourseVersion

    client, Session = env
    cv = locked(client, STAT100)
    with Session() as db:
        cvo = db.get(CourseVersion, cv)
        rec = dict(cvo.record)
        clos = [dict(c) for c in rec["clos"]]
        clos[0]["text"] = "Design a sampling plan for a small survey."  # 'design' -> create
        rec["clos"] = clos
        cvo.record = rec
        db.commit()
        assert bloom.clo_level(clos[0]["text"]) == "create"
        me = db.get(models.Faculty, cvo.faculty_id)
        _clos, level, _diff = draft_svc.check_request(db.get(CourseVersion, cv), me, "mcq", [1], [], 1, None, None)
        assert level == "analyze"
        _clos, level, _diff = draft_svc.check_request(db.get(CourseVersion, cv), me, "case_study", [1], [], 1,
                                                      None, None)
        assert level == "create"
