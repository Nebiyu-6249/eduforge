"""Quality checks run on every draft before faculty see it (HANDOFF §10).

* rule checks: schema, CLOs exist in the locked version, week valid, per-type
  structure (one correct MCQ option, distinct options, timed activities …)
* skills fit: skills-type CLOs should get rubrics/activities, not MCQs
* answer key: numeric answers recomputed in code; MCQs re-solved
  independently by the model without seeing the key
* LLM judge: CLO alignment and Bloom fit, scored 1-5 with a rubric
* duplicates: similarity against the course version's other drafts

Outcomes: pass | warn | fail | skipped. A 'fail' on a HARD check blocks
approval until the faculty edits the item; judge scores only advise.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from pydantic import ValidationError

from app.llm.gateway import LLMError, LLMGateway

from . import bloom
from .prompts import JUDGE, RESOLVE_MCQ, JudgeVerdict, ResolveVerdict
from .safe_eval import UnsafeExpression, evaluate
from .schemas import QUESTION_TYPES, TYPE_LABELS, validate_parts

HARD_CHECKS = {"schema", "clo_exists", "week_valid", "structure", "answer_key", "figure", "code_tests"}
CHECK_LABELS = {
    "schema": "Schema",
    "clo_exists": "CLOs exist in the locked version",
    "week_valid": "Week is in the schedule",
    "structure": "Item structure",
    "skills_fit": "Item type suits the CLO",
    "answer_key": "Answer key re-checked",
    "clo_alignment": "CLO alignment (LLM judge)",
    "bloom_fit": "Bloom fit (LLM judge)",
    "duplicate": "Not a duplicate",
    "math": "Math (LaTeX) renders",
    "figure": "Figure compiles / renders",
    "code_tests": "Reference solution passes its tests",
}


@dataclass
class Check:
    check: str
    outcome: str  # pass | warn | fail | skipped
    detail: str
    score: float | None = None


@dataclass
class CourseContext:
    clos: dict[int, str]  # number -> text
    weeks: set[int]


@dataclass
class Draft:
    type: str
    tags: dict
    body: dict
    answer_key: dict | None
    feedback: dict | None


# --------------------------------------------------------------------------- #

def item_text(d: Draft) -> str:
    """Flatten an item to plain text (for the judge and duplicate check)."""
    out: list[str] = []

    def walk(v) -> None:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in {"label", "kind"}:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(d.body)
    return "\n".join(out)


def _render_for_judge(d: Draft) -> str:
    parts = [item_text(d)]
    if d.answer_key:
        parts.append("ANSWER KEY: " + "; ".join(f"{k}: {v}" for k, v in d.answer_key.items() if isinstance(v, (str, int, float))))
    return "\n".join(parts)


def _nested_clos(d: Draft) -> set[int]:
    nums = set(d.tags.get("clo_numbers", []))
    for a in d.body.get("activities", []) or []:
        nums.update(a.get("clo_numbers", []))
    for c in d.body.get("criteria", []) or []:
        nums.update(c.get("clo_numbers", []))
    return nums


# ---- rule checks ------------------------------------------------------------

def check_schema(d: Draft) -> Check:
    try:
        validate_parts(d.type, d.tags, d.body, d.answer_key, d.feedback)
    except ValidationError as e:
        errs = "; ".join(f"{'/'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5])
        return Check("schema", "fail", f"Doesn't match the {TYPE_LABELS[d.type]} schema: {errs}")
    return Check("schema", "pass", "Matches the schema.")


def check_clos(d: Draft, ctx: CourseContext) -> Check:
    used = _nested_clos(d)
    unknown = sorted(used - set(ctx.clos))
    if not used:
        return Check("clo_exists", "fail", "Not tagged to any CLO.")
    if unknown:
        return Check("clo_exists", "fail", f"Tagged to CLO {', '.join(map(str, unknown))}, which the locked version "
                                           f"doesn't have (it has {', '.join(map(str, sorted(ctx.clos)))}).")
    return Check("clo_exists", "pass", f"CLO {', '.join(map(str, sorted(used)))} exist.")


def check_week(d: Draft, ctx: CourseContext) -> Check:
    wk = d.tags.get("week_no")
    if wk is None:
        return Check("week_valid", "pass", "Not tied to a week.")
    if ctx.weeks and wk not in ctx.weeks:
        return Check("week_valid", "fail", f"Week {wk} isn't in the schedule (weeks {min(ctx.weeks)}–{max(ctx.weeks)}).")
    return Check("week_valid", "pass", f"Week {wk} is in the schedule.")


def check_structure(d: Draft) -> Check:
    b, k = d.body, d.answer_key or {}
    problems: list[str] = []
    warns: list[str] = []
    if d.type == "mcq":
        labels = [o.get("label") for o in b.get("options", [])]
        texts = [re.sub(r"\W+", " ", (o.get("text") or "").lower()).strip() for o in b.get("options", [])]
        if len(set(labels)) != len(labels):
            problems.append("option labels repeat")
        if len(set(texts)) != len(texts):
            problems.append("two options have the same text")
        if k.get("correct") not in labels:
            problems.append(f"the key '{k.get('correct')}' isn't one of the options")
        if any(re.search(r"\b(all|none) of the above\b", t) for t in texts):
            warns.append("uses 'all/none of the above'")
        missing = [lbl for lbl in labels if lbl != k.get("correct") and lbl not in (k.get("why_others_wrong") or {})]
        if missing:
            warns.append(f"no explanation for distractor(s) {', '.join(missing)}")
    elif d.type == "lesson_plan":
        total = sum(a.get("minutes", 0) for a in b.get("activities", []))
        sess = b.get("session_minutes") or 0
        if sess and total > sess:
            problems.append(f"activities take {total} min but the session is {sess} min")
        elif sess and total < 0.8 * sess:
            warns.append(f"activities fill only {total} of {sess} min")
    elif d.type == "rubric":
        for c in b.get("criteria", []):
            pts = [lv.get("points") for lv in c.get("levels", [])]
            if len(set(pts)) != len(pts):
                problems.append(f"criterion '{c.get('criterion')}' has levels with equal points")
    elif d.type == "problem":
        names = [g.get("name") for g in b.get("given", [])]
        if len(set(names)) != len(names):
            problems.append("two given values share a name")
    if problems:
        return Check("structure", "fail", "; ".join(problems).capitalize() + ".")
    if warns:
        return Check("structure", "warn", "; ".join(warns).capitalize() + ".")
    return Check("structure", "pass", "Structure is sound.")


def check_skills_fit(d: Draft, ctx: CourseContext) -> Check:
    clos = [n for n in d.tags.get("clo_numbers", []) if n in ctx.clos]
    skills = [n for n in clos if bloom.is_skills_clo(ctx.clos[n])]
    if d.type in QUESTION_TYPES and clos and len(skills) == len(clos):
        return Check("skills_fit", "warn",
                     f"CLO {', '.join(map(str, skills))} is a skills outcome; a rubric, case study or activity "
                     f"usually evidences it better than a {TYPE_LABELS[d.type].lower()}.")
    return Check("skills_fit", "pass", "Item type suits the CLO(s).")


# ---- answer key -------------------------------------------------------------

def check_answer_key(d: Draft, llm: LLMGateway | None) -> Check:
    k = d.answer_key or {}
    if d.type == "problem":
        expr, stated = k.get("answer_expression"), k.get("numeric_answer")
        if stated is None:
            return Check("answer_key", "skipped", "Not a single numeric answer; check the worked solution by hand.")
        if not expr:
            return Check("answer_key", "warn", "A numeric answer is given without an expression, so it can't be "
                                               "recomputed. Check it by hand.")
        names = {g["name"]: g["value"] for g in d.body.get("given", []) if "name" in g and "value" in g}
        names.update(_dataset_names(d))  # e.g. slope, mean_x from a generated dataset (plan 2.20)
        try:
            got = evaluate(expr, names)
        except UnsafeExpression as e:
            return Check("answer_key", "warn", f"Couldn't recompute '{expr}': {e}")
        tol = max(float(k.get("tolerance") or 0.01), 1e-9)
        if math.isclose(got, float(stated), rel_tol=tol, abs_tol=1e-9):
            return Check("answer_key", "pass", f"Recomputed {expr} = {got:.6g}, matching the key ({stated:g}).", 1.0)
        return Check("answer_key", "fail", f"Recomputed {expr} = {got:.6g}, but the key says {stated:g}.", 0.0)
    if d.type == "mcq":
        if llm is None or not llm.available:
            return Check("answer_key", "skipped", "No LLM configured to re-solve the question independently.")
        opts = "\n".join(f"{o['label']}. {o['text']}" for o in d.body.get("options", []))
        try:
            v = llm.json(RESOLVE_MCQ, ResolveVerdict, stem=d.body.get("stem", ""), options=opts)
        except LLMError as e:
            return Check("answer_key", "skipped", f"Re-solve failed: {e}")
        key = k.get("correct")
        if v.problem:
            return Check("answer_key", "warn", f"Independent re-solve chose {v.answer} and noted: {v.problem}")
        if v.answer.strip().upper()[:1] != key:
            return Check("answer_key", "fail", f"Independent re-solve chose {v.answer}, but the key says {key}.", 0.0)
        return Check("answer_key", "pass" if v.confident else "warn",
                     f"Independent re-solve also chose {key}{'' if v.confident else ' (not confident)'}.",
                     1.0 if v.confident else 0.5)
    return Check("answer_key", "skipped", "No automatic key check for this type.")


# ---- LLM judge --------------------------------------------------------------

def _score_outcome(s: int) -> str:
    return "pass" if s >= 4 else "warn" if s == 3 else "fail"


def check_judge(d: Draft, ctx: CourseContext, llm: LLMGateway | None) -> list[Check]:
    if llm is None or not llm.available:
        return [Check("clo_alignment", "skipped", "No LLM configured."),
                Check("bloom_fit", "skipped", "No LLM configured.")]
    clos = "\n".join(f"CLO {n}: {ctx.clos[n]}" for n in d.tags.get("clo_numbers", []) if n in ctx.clos)
    try:
        v = llm.json(JUDGE, JudgeVerdict, clos=clos or "(none)", bloom=d.tags.get("bloom_level", "?"),
                     type_label=TYPE_LABELS[d.type], item=_render_for_judge(d))
    except LLMError as e:
        return [Check("clo_alignment", "skipped", f"Judge failed: {e}"), Check("bloom_fit", "skipped", f"Judge failed: {e}")]
    return [
        Check("clo_alignment", _score_outcome(v.clo_alignment), f"{v.clo_alignment}/5 — {v.clo_alignment_reason}",
              float(v.clo_alignment)),
        Check("bloom_fit", _score_outcome(v.bloom_fit),
              f"{v.bloom_fit}/5 — claims {d.tags.get('bloom_level')}, reads as {v.observed_bloom_level}. "
              f"{v.bloom_fit_reason}", float(v.bloom_fit)),
    ]


# ---- duplicates -------------------------------------------------------------

def _vec(text: str) -> Counter:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return Counter(words + [f"{a} {b}" for a, b in zip(words, words[1:])])


def similarity(a: str, b: str) -> float:
    va, vb = _vec(a), _vec(b)
    dot = sum(va[t] * vb[t] for t in va.keys() & vb.keys())
    na, nb = math.sqrt(sum(x * x for x in va.values())), math.sqrt(sum(x * x for x in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def check_duplicate(d: Draft, others: list[tuple[int, Draft]]) -> Check:
    """Embedding cosine similarity against the course's other items (plan 2.8).

    Items are exam material, so a hosted embedding model is used only where real
    exam items may go (local Ollama or a no-retention provider); otherwise the
    built-in local embedder. Thresholds differ by embedder: semantic models score
    paraphrases high, the local bag-of-words one needs more shared wording.
    """
    from app.llm.embeddings import LocalHashEmbedder, cosine, get_embedder
    from app.materials.service import sensitive_ok

    same = [(oid, o) for oid, o in others if o.type == d.type]
    if not same:
        return Check("duplicate", "pass", "No similar items.", 0.0)
    embedder = get_embedder() if sensitive_ok() else LocalHashEmbedder()
    threshold = 0.85 if isinstance(embedder, LocalHashEmbedder) else 0.92
    try:
        vecs = embedder.embed([item_text(d)] + [item_text(o) for _, o in same])
    except Exception:  # noqa: BLE001 - a remote embedder failing must not block the check
        embedder, threshold = LocalHashEmbedder(), 0.85
        vecs = embedder.embed([item_text(d)] + [item_text(o) for _, o in same])
    best_id, best = None, 0.0
    for (oid, _), v in zip(same, vecs[1:]):
        s = cosine(vecs[0], v)
        if s > best:
            best_id, best = oid, s
    how = f"embedding similarity, {embedder.name}"
    if best >= threshold:
        return Check("duplicate", "warn", f"Very similar to item #{best_id} ({best:.0%} {how}).", best)
    return Check("duplicate", "pass", f"Most similar existing item: #{best_id} ({best:.0%} {how}).", best)


# --------------------------------------------------------------------------- #

def run_all(d: Draft, ctx: CourseContext, others: list[tuple[int, Draft]], llm: LLMGateway | None) -> list[Check]:
    schema = check_schema(d)
    checks = [schema, check_clos(d, ctx), check_week(d, ctx)]
    if schema.outcome == "fail":
        return checks  # the remaining checks need a well-formed item
    checks += [check_math(d), *check_figure(d), *check_code(d)]
    checks += [check_structure(d), check_skills_fit(d, ctx), check_answer_key(d, llm), *check_judge(d, ctx, llm),
               check_duplicate(d, others)]
    return checks


def blocking(checks) -> list:
    return [c for c in checks if c.check in HARD_CHECKS and c.outcome == "fail"]


# ---- math, figures, code (plan 2.17–2.20) ----------------------------------

def _all_text(d: Draft) -> str:
    parts = [item_text(d)]
    for part in (d.answer_key, d.feedback):
        if part:
            parts.append(item_text(Draft(d.type, {}, part, None, None)))
    return "\n".join(parts)


def check_math(d: Draft) -> Check:
    from .rich import math_segments, render_math

    segs = math_segments(_all_text(d))
    if not segs:
        return Check("math", "skipped", "No math in this item.")
    bad = []
    for s in segs:
        try:
            render_math(s)
        except ValueError as e:
            bad.append(f"${s}$ ({e})")
    if bad:
        return Check("math", "warn", "Doesn't render: " + "; ".join(bad[:3]) + ". Fix the LaTeX before export.")
    return Check("math", "pass", f"{len(segs)} expression(s) render.")


def _figure(d: Draft) -> dict | None:
    return (d.body or {}).get("figure")


def _dataset_names(d: Draft) -> dict[str, float]:
    from .rich import DatasetError, generate

    fig = _figure(d)
    if not fig or not fig.get("dataset"):
        return {}
    try:
        return {k: v for k, v in generate(fig["dataset"])["summary"].items() if isinstance(v, (int, float))}
    except DatasetError:
        return {}


def check_figure(d: Draft) -> list[Check]:
    from .rich import DatasetError, generate, render_chart, render_diagram

    fig = _figure(d)
    if not fig:
        return []
    if fig.get("diagram"):
        dg = fig["diagram"]
        r = render_diagram(dg["kind"], dg["source"])
        if not r.available:
            return [Check("figure", "skipped", f"{r.error} The diagram source is kept; install the renderer to check it.")]
        if r.error:
            return [Check("figure", "fail", f"The {dg['kind']} source doesn't compile: {r.error}")]
        return [Check("figure", "pass", f"The {dg['kind']} diagram compiles.")]
    if fig.get("dataset"):
        try:
            data = generate(fig["dataset"])
            if fig.get("chart"):
                render_chart(fig["chart"], data)
        except DatasetError as e:
            return [Check("figure", "fail", f"Dataset: {e}")]
        s = data["summary"]
        shown = ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in list(s.items())[:6])
        return [Check("figure", "pass", f"Dataset generated from seed {fig['dataset'].get('seed', 1)} ({shown})"
                                         + (" and chart drawn from it." if fig.get("chart") else "."))]
    if fig.get("chart"):
        return [Check("figure", "fail", "A chart needs a dataset to be drawn from (the model never draws data).")]
    return []


def check_code(d: Draft) -> list[Check]:
    from .sandbox import run_tests

    if d.type != "code_exercise":
        return []
    k = d.answer_key or {}
    sol, tests = k.get("solution_code", ""), k.get("tests_code", "")
    r = run_tests(sol, tests)
    where = "in an isolated container" if r.isolated else f"in the {r.backend} sandbox (not isolated: dev only)"
    if r.backend == "off":
        return [Check("code_tests", "skipped", r.error or "Code execution is off.")]
    if r.error:
        return [Check("code_tests", "fail", f"Ran {where}: {r.error}")]
    if r.failed:
        names = "; ".join(f"{f['name']}: {f['error']}" for f in r.failed[:3])
        return [Check("code_tests", "fail", f"Reference solution fails {len(r.failed)} test(s) {where}: {names}",
                      len(r.passed) / (len(r.passed) + len(r.failed)))]
    if not r.passed:
        return [Check("code_tests", "fail", "No test functions (named test_*) were found.")]
    msg = f"Reference solution passes all {len(r.passed)} test(s) {where}."
    starter = (d.body or {}).get("starter_code", "")
    if starter.strip() and run_tests(starter, tests).ok:
        return [Check("code_tests", "warn", msg + " But the starter code passes them too, so the tests don't tell "
                                                  "a finished answer from an unfinished one.", 0.5)]
    return [Check("code_tests", "pass", msg, 1.0)]
