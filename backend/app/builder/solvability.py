"""AI-solvability check (plan 3.9): can a strong model solve this item unaided?

The model gets only what a student gets (no key, no hints) and answers. Then:
code exercises run its code against the hidden tests; numeric problems compare
numbers; everything else is graded against the answer key by a second call.
Verdict: solved trivially / partly / not. It is a report, never a block.

Items are exam material: this runs only with a model allowed to see them
(local Ollama or a no-retention provider, plan 14.10).
"""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field

from app.drafts.quality import Draft, item_text
from app.drafts.sandbox import run_tests
from app.llm.gateway import LLMError, LLMGateway, Prompt
from app.models import Item

SOLVE = Prompt(id="solvability.solve", version="1",
               system="You are a capable student. Answer the assignment as well as you can. Reply with JSON only.",
               user="{task}\n\nGive your complete answer.{code_hint}")
GRADE = Prompt(id="solvability.grade", version="1",
               system="You compare a student's answer with the official answer key. Reply with JSON only.",
               user="TASK:\n{task}\n\nANSWER KEY:\n{key}\n\nSTUDENT ANSWER:\n{answer}\n\n"
                    "How much of the task did the answer get right? full, partial or none.")

SUGGESTIONS = [
    "Personalise it: use data each student collects, or values derived from their ID.",
    "Add a short oral follow-up where the student explains one step.",
    "Ask for process evidence: drafts, commits, intermediate results, a reflection on choices.",
    "Tie it to something done in class (a specific lab result, a local case) that a model hasn't seen.",
]


class Solved(BaseModel):
    answer: str
    code: str | None = Field(default=None, description="Python code, for programming tasks")
    numeric_answer: float | None = None


class Grade(BaseModel):
    correctness: str = Field(description="full | partial | none")
    reason: str


def check(item: Item, llm: LLMGateway) -> dict:
    task = item_text(Draft(item.type, {}, item.body_json, None, None))
    key = item.answer_key_json or {}
    try:
        s = llm.json(SOLVE, Solved, task=task,
                     code_hint=" Put the full Python code in 'code'." if item.type == "code_exercise" else "")
    except LLMError as e:
        return {"verdict": "unknown", "detail": f"The model call failed: {e}"}
    if item.type == "code_exercise" and s.code:
        r = run_tests(s.code, key.get("tests_code", ""))
        n = len(r.passed) + len(r.failed)
        if r.ok:
            return {"verdict": "trivial", "detail": f"The model's code passed all {n} hidden tests."}
        if r.passed:
            return {"verdict": "partly", "detail": f"The model's code passed {len(r.passed)} of {n} hidden tests."}
        return {"verdict": "not", "detail": f"The model's code failed the hidden tests ({r.error or 'all failed'})."}
    if item.type == "problem" and key.get("numeric_answer") is not None:
        got = s.numeric_answer
        if got is None:
            m = re.search(r"-?\d+(?:\.\d+)?", s.answer or "")
            got = float(m.group()) if m else None
        if got is not None and math.isclose(got, float(key["numeric_answer"]), rel_tol=float(key.get("tolerance") or 0.01)):
            return {"verdict": "trivial", "detail": f"The model got the numeric answer ({got:g})."}
    try:
        g = llm.json(GRADE, Grade, task=task, key=str(key)[:3000], answer=(s.answer or "")[:3000])
    except LLMError as e:
        return {"verdict": "unknown", "detail": f"Grading call failed: {e}"}
    verdict = {"full": "trivial", "partial": "partly"}.get(g.correctness.strip().lower(), "not")
    return {"verdict": verdict, "detail": g.reason}
