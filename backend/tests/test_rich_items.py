"""Math, diagrams, datasets/charts and code exercises (plan 2.17–2.20)."""

from __future__ import annotations

import io

from docx import Document

from app.drafts import rich
from tests.synth.specs import STAT100
from tests.test_api_workflow import A
from tests.test_drafts import drafts_post, fake, locked, problem, scores

DATASET = {"kind": "linear", "n": 30, "seed": 11, "params": {"slope": 2.0, "intercept": 5, "noise_sd": 1.0}}


def _slope() -> float:
    return rich.generate(DATASET)["summary"]["slope"]


def regression_problem(numeric, expr="slope", chart="scatter", latex=r"$\hat{y} = b_0 + b_1 x$"):
    p = problem(numeric=numeric, expr=expr)
    p["tags"]["clo_numbers"] = [5]
    p["tags"]["week_no"] = 14
    p["body"]["statement"] = f"Fit the least squares line {latex} to the data in the figure."
    p["body"]["given"] = []
    p["body"]["asks_for"] = "the slope b1"
    p["body"]["figure"] = {"caption": "Study hours vs exam score", "dataset": DATASET,
                           "chart": {"type": chart, "title": "", "x_label": "hours", "y_label": "score"}
                           if chart else None, "diagram": None}
    return p


def code_item(solution: str, starter: str = "def mean(xs):\n    return 0\n"):
    return {
        "tags": {"clo_numbers": [1], "week_no": 3, "bloom_level": "apply", "difficulty": "easy"},
        "body": {"language": "python", "prompt": "Write mean(xs) returning the arithmetic mean.",
                 "starter_code": starter, "figure": None},
        "answer_key": {"solution_code": solution,
                       "tests_code": "def test_simple():\n    assert mean([1, 2, 3]) == 2\n\n"
                                     "def test_one():\n    assert mean([5]) == 5\n",
                       "explanation": "Sum divided by count."},
        "feedback": {"hint": "Use sum and len.", "explanation": "mean = sum/len"},
    }


def gen_one(client, cv, item_type, clo, payload):
    fake({item_type: {"items": [payload]}})
    r = drafts_post(client, cv, {"item_type": item_type, "clo_numbers": [clo], "count": 1})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]


def test_dataset_answer_key_recomputed_from_generated_data(env):
    client, _ = env
    cv = locked(client, STAT100)
    good = gen_one(client, cv, "problem", 5, regression_problem(numeric=round(_slope(), 4)))
    s = scores(good)
    assert s["answer_key"]["outcome"] == "pass" and "slope" in s["answer_key"]["detail"]
    assert s["figure"]["outcome"] == "pass" and "seed 11" in s["figure"]["detail"]
    assert s["math"]["outcome"] == "pass"
    png = client.get(f"/api/drafts/{good['id']}/figure.png", headers=A)
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    csv = client.get(f"/api/drafts/{good['id']}/dataset.csv", headers=A).text
    assert csv.splitlines()[0] == "x,y" and len(csv.splitlines()) == 31

    wrong = gen_one(client, cv, "problem", 5, regression_problem(numeric=2.0))  # the population slope, not the fitted one
    assert scores(wrong)["answer_key"]["outcome"] == "fail" or abs(_slope() - 2.0) < 0.02


def test_chart_without_dataset_fails_and_bad_latex_warns(env):
    client, _ = env
    cv = locked(client, STAT100)
    p = regression_problem(numeric=1.0, expr=None, latex=r"$\frac{1}{$")
    p["body"]["figure"] = {"caption": "", "dataset": None, "diagram": None,
                           "chart": {"type": "bar", "title": "", "x_label": "", "y_label": ""}}
    it = gen_one(client, cv, "problem", 5, p)
    s = scores(it)
    assert s["figure"]["outcome"] == "fail" and it["can_approve"] is False
    assert s["math"]["outcome"] == "warn"


def test_diagram_check_is_skipped_without_a_renderer(env, monkeypatch):
    client, _ = env
    cv = locked(client, STAT100)
    monkeypatch.setattr(rich, "diagram_renderer", lambda kind: None)
    p = regression_problem(numeric=1.0, expr=None, chart=None)
    p["body"]["figure"] = {"caption": "Parse tree", "dataset": None, "chart": None,
                           "diagram": {"kind": "graphviz", "source": "digraph { E -> T; T -> F }"}}
    it = gen_one(client, cv, "problem", 5, p)
    s = scores(it)
    assert s["figure"]["outcome"] == "skipped" and "renderer" in s["figure"]["detail"]
    assert it["can_approve"] is True  # skipped is not a failure; faculty see why


def test_code_exercise_solution_must_pass_tests(env):
    client, _ = env
    cv = locked(client, STAT100)
    ok = gen_one(client, cv, "code_exercise", 1, code_item("def mean(xs):\n    return sum(xs) / len(xs)\n"))
    s = scores(ok)
    assert s["code_tests"]["outcome"] == "pass" and "2 test(s)" in s["code_tests"]["detail"]
    assert ok["can_approve"] is True

    bad = gen_one(client, cv, "code_exercise", 1, code_item("def mean(xs):\n    return sum(xs)\n"))
    s = scores(bad)
    assert s["code_tests"]["outcome"] == "fail" and "test_simple" in s["code_tests"]["detail"]
    assert bad["can_approve"] is False

    weak = gen_one(client, cv, "code_exercise", 1,
                   code_item("def mean(xs):\n    return sum(xs) / len(xs)\n",
                             starter="def mean(xs):\n    return sum(xs) / len(xs)\n"))
    assert scores(weak)["code_tests"]["outcome"] == "warn" and weak["can_approve"] is True


def test_export_renders_math_figures_and_code(env):
    client, _ = env
    cv = locked(client, STAT100)
    it = gen_one(client, cv, "problem", 5, regression_problem(numeric=round(_slope(), 4)))
    code = gen_one(client, cv, "code_exercise", 1, code_item("def mean(xs):\n    return sum(xs) / len(xs)\n"))
    for x in (it, code):
        assert client.post(f"/api/drafts/{x['id']}/action", headers=A, json={"action": "approve"}).status_code == 200
    r = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "docx"})
    assert r.status_code == 200
    doc = Document(io.BytesIO(r.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert len(doc.inline_shapes) >= 2  # the chart plus at least one math image
    assert "Fit the least squares line" in text and "$" not in text.split("Fit the least squares line")[1][:30]
    assert "def mean(xs):" in text and "def test_simple" in text and "Dataset facts (computed): n = 30" in text
    pdf = client.post(f"/api/course-versions/{cv}/export", headers=A, json={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"


def test_docx_images_have_alt_text(env):
    client, _ = env
    cv = locked(client, STAT100)
    it = gen_one(client, cv, "problem", 5, regression_problem(numeric=round(_slope(), 4)))
    client.post(f"/api/drafts/{it['id']}/action", headers=A, json={"action": "approve"})
    doc = Document(io.BytesIO(client.post(f"/api/course-versions/{cv}/export", headers=A,
                                          json={"format": "docx"}).content))
    alts = [s._inline.docPr.get("descr") for s in doc.inline_shapes]
    assert "Study hours vs exam score" in alts and any("hat{y}" in (a or "") for a in alts)
