"""Mark suggestions for one answer (plan 4.5–4.7, 4.9).

* key (4.5): MCQ, numeric with tolerance, exact short answer. Deterministic,
  no model. Faculty may confirm these in bulk.
* code (4.7): the student's code runs against the item's hidden tests, only in
  the isolated Docker sandbox (no network, memory/CPU/pid limits). Without
  Docker the cell is left for the faculty member.
* llm (4.6): per rubric criterion the model picks a level, quotes evidence from
  the answer and gives a confidence. Quotes are checked against the answer:
  an unverifiable quote is dropped, and a criterion without evidence or a
  low confidence is flagged "needs faculty".
* manual: no suggestion; the faculty member marks it.

Every suggestion is only a suggestion: nothing here confirms a mark.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.config import get_settings
from app.drafts.sandbox import backend as sandbox_backend
from app.drafts.sandbox import run_tests
from app.llm.gateway import LLMError, LLMGateway, Prompt
from app.models import FormItem, Item

from . import identity

LABELS = "ABCDE"
LOW_CONFIDENCE = 0.6
HIGH_CONFIDENCE = 0.8

RUBRIC_PROMPT = Prompt(
    id="grading.rubric", version="1",
    system=("You help a university faculty member mark one student answer against a rubric. You only suggest; "
            "the faculty member decides every mark. Judge the answer against the question and the answer key, "
            "not its style. Quote the student's own words exactly as evidence. Reply with JSON only."),
    user=("QUESTION:\n{question}\n\nANSWER KEY:\n{key}\n\nRUBRIC (criterion: levels as label = points: descriptor):\n"
          "{rubric}\n\nSTUDENT ANSWER (anonymised; [NAME], [ID] etc. are redactions):\n<<<\n{answer}\n>>>\n\n"
          "For every criterion: pick exactly one level label; quote 1-3 short exact phrases from the student answer "
          "that justify it (none if the answer has nothing relevant); give your confidence from 0 to 1. Then write "
          "feedback to the student: 1-3 sentences, referring to the criteria, saying what was right and what to "
          "do next."),
)


class CriterionJudgement(BaseModel):
    criterion: str
    level: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class RubricJudgement(BaseModel):
    criteria: list[CriterionJudgement]
    feedback: str


@dataclass
class Suggestion:
    method: str  # key | code | llm | manual
    max_points: float
    points: float | None
    level_step: float
    confidence: float | None = None
    criteria: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    needs_faculty: bool = False
    note: str | None = None
    feedback: str | None = None
    feedback_source: str | None = None


# ---- helpers ------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.\-]", " ", (s or "").lower())).strip()


def question_text(it: Item) -> str:
    b = it.body_json
    parts = [b.get("stem") or b.get("question") or b.get("statement") or b.get("prompt") or b.get("scenario") or ""]
    if b.get("asks_for"):
        parts.append("Find: " + b["asks_for"])
    for i, q in enumerate(b.get("questions") or [], 1):
        parts.append(f"{i}. {q.get('question', '')}")
    for i, ex in enumerate(b.get("exercises") or [], 1):
        parts.append(f"{i}. {ex.get('prompt', '')}")
    return "\n".join(p for p in parts if p)


def shown_correct(it: Item, fi: FormItem) -> str | None:
    """The correct MCQ letter as printed on this form version (options are shuffled per version)."""
    key = (it.answer_key_json or {}).get("correct")
    order = fi.option_order or [o["label"] for o in it.body_json.get("options", [])]
    return LABELS[order.index(key)] if key in order else None


def _mcq_choice(answer: str, it: Item, fi: FormItem) -> str | None:
    a = answer.strip()
    m = re.fullmatch(r"\(?([A-Ea-e])\)?[.):]?(?:\s+.*)?", a, re.S)
    if m and (len(a) <= 3 or a[1:2] in {")", ".", ":", " "}):
        return m.group(1).upper()
    order = fi.option_order or [o["label"] for o in it.body_json.get("options", [])]
    texts = {o["label"]: _norm(o["text"]) for o in it.body_json.get("options", [])}
    for i, lbl in enumerate(order):
        if texts.get(lbl) and texts[lbl] == _norm(a):
            return LABELS[i]
    return None


_NUMBER = re.compile(r"[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?")


def numbers_in(text: str) -> list[float]:
    out = []
    for m in _NUMBER.finditer(text or ""):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    return out


def _close(a: float, b: float, tol: float) -> bool:
    return math.isclose(a, b, rel_tol=max(tol, 1e-9), abs_tol=1e-9 if b else max(tol, 1e-9))


# ---- rubric derived from the answer key (4.6) ---------------------------------
def rubric_for(it: Item, max_points: float) -> list[dict]:
    """Criteria with levels whose points add up to the item's points on this form."""
    key = it.answer_key_json or {}
    b = it.body_json

    def three(name: str, share: float, expect: str) -> dict:
        pts = round(max_points * share, 2)
        return {"criterion": name, "expect": expect, "levels": [
            {"label": "Full", "points": pts, "descriptor": "Fully correct and complete."},
            {"label": "Partial", "points": round(pts / 2, 2), "descriptor": "Partly correct or incomplete."},
            {"label": "None", "points": 0.0, "descriptor": "Missing or incorrect."}]}

    if it.type == "short_answer":
        pts = key.get("key_points") or [key.get("model_answer", "")]
        return [three(f"Key point {i}", 1 / len(pts), p) for i, p in enumerate(pts, 1)]
    if it.type == "problem":
        return [three("Method and working", 0.6, " / ".join(key.get("solution_steps", []))),
                three("Final answer", 0.4, key.get("final_answer_text", ""))]
    if it.type == "case_study":
        qs = b.get("questions") or []
        return [three(f"Question {i}", 1 / len(qs), q.get("model_answer", "")) for i, q in enumerate(qs, 1)] or \
            [three("Analysis", 1.0, key.get("teaching_notes", ""))]
    if it.type == "practice_set":
        exs = b.get("exercises") or []
        return [three(f"Exercise {i}", 1 / len(exs), e.get("answer", "")) for i, e in enumerate(exs, 1)]
    return [three("Answer", 1.0, str(key))]


def _step(criteria: list[dict]) -> float:
    gaps = [abs(a["points"] - b["points"]) for c in criteria for a, b in zip(c["levels"], c["levels"][1:], strict=False)]
    return max(gaps) if gaps else 0.0


def _found(quote: str, answer: str) -> bool:
    q = _norm(quote)
    return len(q) >= 3 and q in _norm(answer)


# ---- the three suggestion paths -------------------------------------------------
def by_key(it: Item, fi: FormItem, answer: str) -> Suggestion | None:
    """Deterministic score, or None if this item/answer needs another path."""
    mx = fi.points
    key = it.answer_key_json or {}
    if not answer.strip():
        return Suggestion("key", mx, 0.0, mx, 1.0, evidence=["No answer given."], note="No answer.")
    if it.type == "mcq":
        right = shown_correct(it, fi)
        got = _mcq_choice(answer, it, fi)
        if got is None or right is None:
            return Suggestion("manual", mx, None, mx, None, needs_faculty=True,
                              note="Couldn't read which option the student chose.", evidence=[answer[:200]])
        ok = got == right
        fb = None
        if not ok:
            order = fi.option_order or [o["label"] for o in it.body_json.get("options", [])]
            stored = order[LABELS.index(got)] if LABELS.index(got) < len(order) else None
            why = (key.get("why_others_wrong") or {}).get(stored or "", "")
            fb = f"You chose {got}; the answer is {right}. {why} {key.get('why_correct', '')}".strip()
        return Suggestion("key", mx, mx if ok else 0.0, mx, 1.0, evidence=[f"Chose {got}; key {right}."],
                          feedback=fb, feedback_source="key")
    if it.type == "problem" and key.get("numeric_answer") is not None:
        want, tol = float(key["numeric_answer"]), float(key.get("tolerance") or 0.01)
        nums = numbers_in(answer)
        if not nums:
            return Suggestion("key", mx, 0.0, mx, 0.9, evidence=["No number in the answer."],
                              feedback=f"The expected answer is {key.get('final_answer_text', want)}.", feedback_source="key")
        if _close(nums[-1], want, tol):
            return Suggestion("key", mx, mx, mx, 1.0, evidence=[f"Final number {nums[-1]:g} matches {want:g} (±{tol:.0%})."])
        if any(_close(n, want, tol) for n in nums):
            return Suggestion("key", mx, mx, mx, 0.5, needs_faculty=True, evidence=[f"{want:g} appears, but the last number is {nums[-1]:g}."],
                              note="The right value appears in the working but isn't the final answer.")
        hint = (it.feedback_prompts_json or {}).get("hint", "")
        return Suggestion("key", mx, 0.0, mx, 1.0, evidence=[f"Final number {nums[-1]:g}; key {want:g} (±{tol:.0%})."],
                          note="Wrong final value: consider method marks.",
                          feedback=f"Your final answer was {nums[-1]:g}; the expected answer is "
                                   f"{key.get('final_answer_text', want)}. {hint}".strip(), feedback_source="key")
    if it.type == "short_answer" and key.get("model_answer") and _norm(answer) == _norm(key["model_answer"]):
        return Suggestion("key", mx, mx, mx, 1.0, evidence=["Matches the model answer exactly."])
    return None


def by_code(it: Item, fi: FormItem, answer: str) -> Suggestion:
    mx = fi.points
    key = it.answer_key_json or {}
    if sandbox_backend() != "docker":
        return Suggestion("manual", mx, None, mx, None, needs_faculty=True,
                          note="Student code only runs in the isolated Docker sandbox, which isn't available here.")
    res = run_tests(answer, key.get("tests_code", ""))
    total = len(res.passed) + len(res.failed)
    if res.error or total == 0:
        return Suggestion("code", mx, 0.0, mx, 0.7, needs_faculty=True, evidence=[f"Didn't run: {res.error or 'no tests ran'}"],
                          note="The code didn't run; check whether it deserves partial credit.",
                          feedback=f"Your code didn't run against the tests: {res.error or 'no tests ran'}.", feedback_source="key")
    pts = round(mx * len(res.passed) / total, 2)
    ev = [f"passed {t}" for t in res.passed] + [f"failed {f.get('name')}: {f.get('error', '')}"[:200] for f in res.failed]
    fb = None
    if res.failed:
        fb = (f"{len(res.passed)} of {total} hidden tests passed. Check: "
              + "; ".join(str(f.get("name")) for f in res.failed[:5]) + ".")
    return Suggestion("code", mx, pts, round(mx / total, 2), 1.0, evidence=ev, feedback=fb, feedback_source="key",
                      note="Style and explanation, if marked, are for the faculty member.")


def by_rubric(it: Item, fi: FormItem, answer: str, llm: LLMGateway | None, macs: set[str]) -> Suggestion:
    mx = fi.points
    crit = rubric_for(it, mx)
    step = _step(crit)
    s = get_settings()
    why = None
    if not s.grading_llm_approved:
        why = "Suggestions are off: no model is approved for student work (GRADING_LLM_APPROVED)."
    elif it.type in s.grading_suggest_off:
        why = f"Suggestions are off for {it.type} items (missed the calibration gate)."
    elif llm is None or not llm.available:
        why = "No model is configured."
    if why:
        return Suggestion("manual", mx, None, step, None, criteria=crit, needs_faculty=True, note=why)

    rubric = "\n".join(f"- {c['criterion']} (expected: {c['expect'][:400]}): "
                       + "; ".join(f"{lv['label']} = {lv['points']:g}: {lv['descriptor']}" for lv in c["levels"])
                       for c in crit)
    variables = {"question": question_text(it), "key": str(it.answer_key_json or "")[:3000], "rubric": rubric,
                 "answer": answer[:6000]}
    found = identity.leaks(answer, macs, patterns=True) + identity.leaks(RUBRIC_PROMPT.render(**variables), macs)
    if found:  # 4.3: the second line of defence; never send, let the faculty member mark it
        return Suggestion("manual", mx, None, step, None, criteria=crit, needs_faculty=True,
                          note=f"Not sent to the model: the answer may still contain a {', '.join(sorted(set(found)))}.")
    assert llm is not None
    try:
        out = llm.json(RUBRIC_PROMPT, RubricJudgement, question=variables["question"], key=variables["key"],
                       rubric=variables["rubric"], answer=variables["answer"])
    except LLMError as e:
        return Suggestion("manual", mx, None, step, None, criteria=crit, needs_faculty=True,
                          note=f"The model didn't answer usably: {str(e)[:200]}")

    by_name = {j.criterion.strip().lower(): j for j in out.criteria}
    judged, total, conf, flags, evidence = [], 0.0, 1.0, [], []
    for i, c in enumerate(crit):
        j = by_name.get(c["criterion"].lower()) or (out.criteria[i] if i < len(out.criteria) else None)
        level = next((lv for lv in c["levels"] if j and lv["label"].lower() == j.level.strip().lower()), None)
        if j is None or level is None:
            judged.append({**c, "level": None, "points": None, "evidence": [], "confidence": 0.0})
            flags.append(f"{c['criterion']}: no usable level")
            conf = 0.0
            continue
        quotes = [q for q in j.evidence if _found(q, answer)]
        dropped = len(j.evidence) - len(quotes)
        cconf = j.confidence
        if level["points"] > 0 and not quotes:
            cconf = min(cconf, 0.4)
            flags.append(f"{c['criterion']}: no evidence quoted from the answer")
        if dropped:
            flags.append(f"{c['criterion']}: {dropped} quote(s) not found in the answer were dropped")
        judged.append({"criterion": c["criterion"], "levels": c["levels"], "level": level["label"],
                       "points": level["points"], "evidence": quotes, "confidence": round(cconf, 2)})
        evidence += quotes
        total += level["points"]
        conf = min(conf, cconf)
    complete = all(j["points"] is not None for j in judged)
    needs = conf < LOW_CONFIDENCE or not complete or any("no evidence" in f for f in flags)
    return Suggestion("llm", mx, round(total, 2) if complete else None, step, round(conf, 2), criteria=judged,
                      evidence=evidence, needs_faculty=needs, note="; ".join(flags) or None,
                      feedback=out.feedback.strip() or None, feedback_source="llm")


def suggest(it: Item, fi: FormItem, answer: str, llm: LLMGateway | None, macs: set[str]) -> Suggestion:
    k = by_key(it, fi, answer)
    if k is not None:
        return k
    if it.type == "code_exercise":
        return by_code(it, fi, answer)
    return by_rubric(it, fi, answer, llm, macs)
