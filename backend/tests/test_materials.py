"""Course materials library: upload, licence guard, chunking, retrieval, grounding (plan 2.1–2.4, 2.7)."""

from __future__ import annotations

import io

from pptx import Presentation
from pptx.util import Inches
from sqlalchemy import select

from app.drafts.prompts import GEN_PROMPT_VERSION
from app.llm.factory import set_provider_override
from app.llm.gateway import FakeProvider
from app.materials.extract import chunk_units, units_from_file
from app.materials.service import retrieve
from app.models import Chunk, CourseVersion, Item
from tests.synth.specs import STAT100
from tests.test_api_workflow import A
from tests.test_drafts import locked, mcq

# One short page of "lecture notes" per STAT 100 week: what a faculty member uploads.
NOTES = {
    2: "Descriptive statistics. Frequency tables, histograms, bar charts and stem-and-leaf plots summarise data.",
    3: "Measures of center and spread: mean, median, mode, range, variance, standard deviation, quartiles, IQR.",
    4: "Probability basics: sample spaces, events, the addition rule and the multiplication rule for probability.",
    5: "Counting techniques: permutations and combinations. Conditional probability and independence of events.",
    6: "Discrete random variables and the binomial distribution: n trials, success probability p, mean np.",
    7: "Continuous random variables. The normal distribution, z-scores and the standard normal table.",
    9: "Sampling distributions and the central limit theorem: the sample mean is approximately normal.",
    10: "Confidence intervals for a population mean using the t distribution and margin of error.",
    11: "Confidence intervals for a population proportion: p-hat, standard error, critical z value.",
    12: "Hypothesis testing: null and alternative hypotheses, test statistic, p-value, type I and type II errors.",
    13: "Hypothesis tests for proportions: one-sample z test for a proportion and its conditions.",
    14: "Correlation and simple linear regression: scatterplots, the correlation coefficient r, least squares line.",
    15: "Regression inference and prediction: residuals, coefficient of determination r squared, prediction intervals.",
}
# 20 topic queries -> the week whose notes should come back (plan 2.3 retrieval test set).
QUERIES = [
    ("histogram and frequency table", 2), ("stem-and-leaf plot", 2), ("median and mode", 3),
    ("standard deviation and variance", 3), ("interquartile range quartiles", 3), ("addition rule probability", 4),
    ("multiplication rule sample space", 4), ("permutations combinations", 5), ("conditional probability independence", 5),
    ("binomial distribution success probability", 6), ("normal distribution z-score", 7),
    ("central limit theorem sampling distribution", 9), ("t distribution margin of error mean", 10),
    ("confidence interval proportion p-hat", 11), ("null hypothesis p-value", 12), ("type I error type II error", 12),
    ("z test for a proportion", 13), ("correlation coefficient scatterplot", 14),
    ("least squares regression line", 14), ("residuals r squared prediction interval", 15),
]


def _upload(client, cv, name, data, **form):
    r = client.post(f"/api/course-versions/{cv}/materials", headers=A,
                    files={"file": (name, data, "application/octet-stream")},
                    data={k: str(v) for k, v in form.items()})
    assert r.status_code == 202, r.text
    return r.json()


def _course_id(Session, cv):
    with Session() as db:
        return db.get(CourseVersion, cv).course_id


def test_materials_need_a_locked_course(env):
    client, _ = env
    from tests.test_api_workflow import upload

    v = upload(client, STAT100, "pdf")
    r = client.post(f"/api/course-versions/{v['id']}/materials", headers=A,
                    files={"file": ("n.txt", b"notes", "text/plain")}, data={"kind": "notes"})
    assert r.status_code == 409


def test_licence_guard_blocks_unlicensed_textbooks(env):
    client, _ = env
    cv = locked(client, STAT100)
    job = _upload(client, cv, "book.txt", b"Chapter 1. Statistics is the science of data." * 20, kind="textbook")
    assert job["result"]["status"] == "blocked" and "licence" in job["result"]["error"]
    mats = client.get(f"/api/course-versions/{cv}/materials", headers=A).json()
    m = mats[0]
    assert m["status"] == "blocked" and m["chunk_count"] == 0
    job = client.patch(f"/api/materials/{m['id']}", headers=A, json={"licensed": True}).json()
    assert job["result"]["status"] == "indexed" and job["result"]["chunks"] >= 1


def test_pptx_slides_and_notes_become_located_chunks():
    prs = Presentation()
    for i in range(1, 4):
        s = prs.slides.add_slide(prs.slide_layouts[5])
        s.shapes.title.text = f"Slide {i}: regression"
        s.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1)).text_frame.text = "Least squares line " * 5
        s.notes_slide.notes_text_frame.text = f"Speaker note {i}"
    buf = io.BytesIO()
    prs.save(buf)
    units = units_from_file("deck.pptx", buf.getvalue())
    assert [u.label for u in units] == ["slide 1", "slide 2", "slide 3"]
    assert "Speaker note 2" in units[1].text
    chunks = chunk_units(units)
    assert len(chunks) == 1 and chunks[0].location == "slides 1–3"


def test_retrieval_test_set_top5(env):
    """Plan 2.3: for 20 topic queries, the right material appears in the top 5."""
    client, Session = env
    cv = locked(client, STAT100)
    for week, text in NOTES.items():
        _upload(client, cv, f"week{week}.txt", text.encode(), kind="notes", week_no=week, title=f"Week {week} notes")
    course_id = _course_id(Session, cv)
    found = 0
    with Session() as db:
        for q, week in QUERIES:
            hits = retrieve(db, course_id, q, k=5)
            found += any(h.material.week_no == week for h in hits)
    assert found == len(QUERIES), f"{found}/{len(QUERIES)} queries found their week in the top 5"


def test_week_filter_and_past_exam_hygiene(env, monkeypatch):
    from app.config import get_settings
    from app.models import Material

    client, Session = env
    cv = locked(client, STAT100)
    # A hosted provider is configured (no call is made here: embeddings stay local).
    monkeypatch.setattr(get_settings(), "llm_provider", "gemini")
    _upload(client, cv, "w14.txt", NOTES[14].encode(), kind="notes", week_no=14)
    _upload(client, cv, "exam.txt", b"Midterm 2025 Q3: compute the least squares regression line.", kind="past_exam")
    course_id = _course_id(Session, cv)
    with Session() as db:
        # A week-3 request doesn't pull week-14 material (and the untagged exam is withheld).
        assert retrieve(db, course_id, "least squares regression", weeks=[3]) == []
        hits = retrieve(db, course_id, "least squares regression", weeks=[14])
        # Real exam items never go to a hosted model unless the provider is no-retention.
        assert {h.material.kind for h in hits} == {"notes"}
        assert {h.material.kind for h in retrieve(db, course_id, "least squares regression",
                                                  include_exams=True)} == {"notes", "past_exam"}
        exam_chunk = db.scalars(select(Chunk).join(Material, Chunk.material_id == Material.id)
                                .where(Material.kind == "past_exam")).first()
        assert exam_chunk is not None and exam_chunk.embed_model.startswith("local-hash")
    monkeypatch.setattr(get_settings(), "llm_no_retention", True)
    with Session() as db:
        assert "past_exam" in {h.material.kind for h in retrieve(db, course_id, "least squares regression")}


def test_generation_is_grounded_and_records_chunks(env):
    client, Session = env
    cv = locked(client, STAT100)
    _upload(client, cv, "w14.txt", NOTES[14].encode(), kind="notes", week_no=14, title="Regression notes")
    p = FakeProvider({"generate.mcq": {"items": [mcq(clo=5, week=14)]},
                      "quality.judge": {"clo_alignment": 5, "clo_alignment_reason": "ok", "bloom_fit": 5,
                                        "bloom_fit_reason": "ok", "observed_bloom_level": "apply"},
                      "quality.resolve_mcq": {"answer": "B", "confident": True, "problem": None}})
    set_provider_override(p)
    job = client.post(f"/api/course-versions/{cv}/drafts", headers=A,
                      json={"item_type": "mcq", "clo_numbers": [5], "weeks": [14], "count": 1}).json()
    assert job["status"] == "done", job
    user = next(u for _, u in p.calls if "REQUEST" in u)
    assert "GROUNDING MATERIAL" in user and "Regression notes" in user and "least squares line" in user
    with Session() as db:
        item = db.get(Item, job["result"]["item_ids"][0])
        assert item.grounded is True and item.source_chunk_ids
        assert item.prompt_version == f"generate.mcq@{GEN_PROMPT_VERSION}"


# --------------------------------------------------------------------------- #
# The reported bug: a whole-course chapter was indexed, and drafts still came
# out UNGROUNDED. With the offline bag-of-words embedder (the default) two
# passages about the same topic in different words score near zero, so the
# 0.05 relevance floor dropped the only material the course had.
# --------------------------------------------------------------------------- #

INTRO_CHAPTER = (
    "Chapter 1 - Introduction. Statistics is the science of collecting, organising and interpreting data. "
    "This chapter sets out populations and samples, parameters and statistics, and the difference between "
    "an observational study and a designed experiment. It closes with levels of measurement."
)


def test_whole_course_material_grounds_a_draft(env):
    """What the faculty member did: upload one chapter for the whole course
    (no week), then generate. The draft must come out grounded, and must name
    the material it used."""
    client, Session = env
    cv = locked(client, STAT100)
    job = _upload(client, cv, "Chapter 1 - Introduction.txt", INTRO_CHAPTER.encode(), kind="slides",
                  title="Chapter 1 - Introduction")
    assert job["result"]["status"] == "indexed", job
    course_id = _course_id(Session, cv)

    from app.materials.service import retrieve_explained

    with Session() as db:
        # A week-5 request: the chapter carries no week tag, so the week filter
        # keeps it, and it is offered as context whatever it scores.
        found = retrieve_explained(db, course_id, "Counting techniques; Conditional probability", weeks=[5])
        assert found.hits, "whole-course material must still be offered as context"
        assert found.indexed == 1 and found.considered == 1
        # Wording with nothing in common still gets the chapter, flagged as weak.
        far = retrieve_explained(db, course_id, "pushdown automata and context-free grammars", weeks=[5])
        assert [h.chunk.id for h in far.hits] == [h.chunk.id for h in found.hits]
        assert far.weak is True and "No close match" in far.reason

    p = FakeProvider({"generate.mcq": {"items": [mcq(clo=1, week=5)]},
                      "quality.judge": {"clo_alignment": 5, "clo_alignment_reason": "ok", "bloom_fit": 5,
                                        "bloom_fit_reason": "ok", "observed_bloom_level": "apply"},
                      "quality.resolve_mcq": {"answer": "B", "confident": True, "problem": None}})
    set_provider_override(p)
    job = client.post(f"/api/course-versions/{cv}/drafts", headers=A,
                      json={"item_type": "mcq", "clo_numbers": [1], "weeks": [5], "count": 1}).json()
    assert job["status"] == "done", job
    item_id = job["result"]["item_ids"][0]
    item = client.get(f"/api/drafts/{item_id}", headers=A).json()
    assert item["grounded"] is True

    g = client.get(f"/api/drafts/{item_id}/grounding", headers=A).json()
    assert g["grounded"] is True
    assert [s["material_title"] for s in g["sources"]] == ["Chapter 1 - Introduction"]
    assert "Statistics is the science" in g["sources"][0]["excerpt"]
    assert g["sources"][0]["week_no"] is None
    assert "Chapter 1 - Introduction" in g["note"]


def test_ungrounded_draft_says_why(env):
    client, _ = env
    cv = locked(client, STAT100)
    p = FakeProvider({"generate.mcq": {"items": [mcq(clo=1, week=5)]},
                      "quality.judge": {"clo_alignment": 5, "clo_alignment_reason": "ok", "bloom_fit": 5,
                                        "bloom_fit_reason": "ok", "observed_bloom_level": "apply"},
                      "quality.resolve_mcq": {"answer": "B", "confident": True, "problem": None}})
    set_provider_override(p)
    job = client.post(f"/api/course-versions/{cv}/drafts", headers=A,
                      json={"item_type": "mcq", "clo_numbers": [1], "weeks": [5], "count": 1}).json()
    item_id = job["result"]["item_ids"][0]
    g = client.get(f"/api/drafts/{item_id}/grounding", headers=A).json()
    assert g["grounded"] is False and g["sources"] == []
    assert "No course material has been added yet" in g["note"]


def test_week_tagged_material_outside_the_asked_weeks_says_so(env):
    client, _ = env
    cv = locked(client, STAT100)
    _upload(client, cv, "w14.txt", NOTES[14].encode(), kind="notes", week_no=14, title="Regression notes")
    p = FakeProvider({"generate.mcq": {"items": [mcq(clo=1, week=2)]},
                      "quality.judge": {"clo_alignment": 5, "clo_alignment_reason": "ok", "bloom_fit": 5,
                                        "bloom_fit_reason": "ok", "observed_bloom_level": "apply"},
                      "quality.resolve_mcq": {"answer": "B", "confident": True, "problem": None}})
    set_provider_override(p)
    job = client.post(f"/api/course-versions/{cv}/drafts", headers=A,
                      json={"item_type": "mcq", "clo_numbers": [1], "weeks": [2], "count": 1}).json()
    g = client.get(f"/api/drafts/{job['result']['item_ids'][0]}/grounding", headers=A).json()
    assert g["grounded"] is False
    assert "none is tagged for week(s) 2" in g["note"]
