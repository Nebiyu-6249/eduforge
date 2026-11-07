"""Strict JSON shapes for every draft item type (HANDOFF §7 item types, §10).

The model fills ``body``; the answer key, rubric and feedback prompts are
separate parts so an export can include or leave out the key. Each type has
one generation prompt (app/drafts/prompts.py) whose output is a batch of these.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

ItemType = Literal["mcq", "short_answer", "problem", "practice_set", "code_exercise", "lesson_plan", "case_study",
                   "learning_resource", "rubric"]
ITEM_TYPES: tuple[str, ...] = ("mcq", "short_answer", "problem", "practice_set", "code_exercise", "lesson_plan",
                               "case_study", "learning_resource", "rubric")
TYPE_LABELS = {
    "mcq": "Multiple-choice question",
    "short_answer": "Short-answer question",
    "problem": "Worked problem",
    "practice_set": "Practice exercise set",
    "code_exercise": "Code exercise",
    "lesson_plan": "Lesson plan",
    "case_study": "Case study",
    "learning_resource": "Learning resource",
    "rubric": "Rubric",
}
# Question types are the "question bank"; skills-type CLOs get rubrics/activities instead (§10).
QUESTION_TYPES = {"mcq", "short_answer", "problem"}

BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
Difficulty = Literal["easy", "medium", "hard"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- figures: diagrams and generated datasets (plan 2.18, 2.20) -------------
class Diagram(_M):
    """Diagram source, rendered to an image; it must compile or the item fails its check."""

    kind: Literal["graphviz", "mermaid", "plantuml"]
    source: str


class DatasetSpec(_M):
    """A synthetic dataset generated in code from a seed, so its properties are known
    exactly (e.g. a regression with a set slope). The model never writes the data."""

    kind: Literal["linear", "normal", "binomial", "categorical"]
    n: int = Field(ge=3, le=1000)
    seed: int = 1
    params: dict[str, float | int | str | list[str] | list[float]] = Field(
        default_factory=dict,
        description="linear: slope, intercept, noise_sd, x_min, x_max | normal: mean, sd | "
                    "binomial: trials, p | categorical: categories (list), probs (list)")


class ChartSpec(_M):
    type: Literal["scatter", "histogram", "bar", "line", "box"]
    title: str = ""
    x_label: str = ""
    y_label: str = ""


class Figure(_M):
    caption: str = ""
    diagram: Diagram | None = None
    dataset: DatasetSpec | None = None
    chart: ChartSpec | None = Field(default=None, description="Chart drawn from the dataset (requires dataset)")


# ---- common tags the model returns with every item -------------------------
class Tags(_M):
    clo_numbers: list[int] = Field(min_length=1, description="CLO numbers this item assesses or supports")
    week_no: int | None = Field(default=None, description="Week whose topic this item draws on")
    bloom_level: BloomLevel
    difficulty: Difficulty


class FeedbackPrompts(_M):
    """Generic hints/explanations drafted with the item (no student work)."""

    hint: str
    explanation: str


# ---- question bank ----------------------------------------------------------
class MCQOption(_M):
    label: Literal["A", "B", "C", "D", "E"]
    text: str


class MCQBody(_M):
    stem: str
    options: list[MCQOption] = Field(min_length=3, max_length=5)

    figure: Figure | None = Field(default=None, description="Optional diagram or generated dataset/chart")

class MCQKey(_M):
    correct: Literal["A", "B", "C", "D", "E"]
    why_correct: str
    why_others_wrong: dict[str, str] = Field(default_factory=dict, description="option label -> why it's wrong")


class MCQItem(_M):
    tags: Tags
    body: MCQBody
    answer_key: MCQKey
    feedback: FeedbackPrompts


class ShortAnswerBody(_M):
    question: str
    expected_length: str = Field(description="e.g. '2-3 sentences'")

    figure: Figure | None = Field(default=None, description="Optional diagram or generated dataset/chart")

class ShortAnswerKey(_M):
    model_answer: str
    key_points: list[str] = Field(min_length=1)


class ShortAnswerItem(_M):
    tags: Tags
    body: ShortAnswerBody
    answer_key: ShortAnswerKey
    feedback: FeedbackPrompts


class GivenValue(_M):
    name: str = Field(description="identifier usable in answer_expression, e.g. n or p_hat")
    value: float
    unit: str = ""
    description: str = ""


class ProblemBody(_M):
    statement: str
    given: list[GivenValue] = Field(default_factory=list)
    asks_for: str

    figure: Figure | None = Field(default=None, description="Optional diagram or generated dataset/chart")

class ProblemKey(_M):
    solution_steps: list[str] = Field(min_length=1)
    final_answer_text: str
    numeric_answer: float | None = Field(default=None, description="null if the answer isn't a single number")
    answer_expression: str | None = Field(
        default=None,
        description="Arithmetic expression over the 'given' names that computes numeric_answer, e.g. "
                    "'(x_bar - mu) / (s / sqrt(n))'. Allowed: + - * / ** ( ), sqrt, log, exp, abs, min, max, "
                    "round, factorial, comb, perm, pi, e.")
    tolerance: float = Field(default=0.01, description="relative tolerance for the numeric check")


class ProblemItem(_M):
    tags: Tags
    body: ProblemBody
    answer_key: ProblemKey
    feedback: FeedbackPrompts


# ---- practice exercises -----------------------------------------------------
class Exercise(_M):
    prompt: str
    answer: str
    hint: str = ""


class PracticeSetBody(_M):
    title: str
    instructions: str
    exercises: list[Exercise] = Field(min_length=2)

    figure: Figure | None = Field(default=None, description="Optional diagram or generated dataset/chart")

class PracticeSetItem(_M):
    tags: Tags
    body: PracticeSetBody
    feedback: FeedbackPrompts


# ---- lesson plan (per week) -------------------------------------------------
class Activity(_M):
    name: str
    minutes: int = Field(ge=1)
    description: str
    clo_numbers: list[int] = Field(default_factory=list)


class LessonPlanBody(_M):
    title: str
    session_minutes: int = Field(ge=10)
    objectives: list[str] = Field(min_length=1)
    prior_knowledge: str = ""
    activities: list[Activity] = Field(min_length=1)
    materials: list[str] = Field(default_factory=list)
    check_for_understanding: str
    after_class: str = ""


class LessonPlanItem(_M):
    tags: Tags
    body: LessonPlanBody


# ---- case study -------------------------------------------------------------
class CaseQuestion(_M):
    question: str
    model_answer: str


class CaseStudyBody(_M):
    title: str
    scenario: str
    questions: list[CaseQuestion] = Field(min_length=1)

    figure: Figure | None = Field(default=None, description="Optional diagram or generated dataset/chart")

class CaseStudyKey(_M):
    teaching_notes: str


class CaseStudyItem(_M):
    tags: Tags
    body: CaseStudyBody
    answer_key: CaseStudyKey


# ---- learning resource ------------------------------------------------------
class LearningResourceBody(_M):
    title: str
    kind: Literal["summary", "reading_guide", "glossary", "worked_example", "study_guide"]
    content: str = Field(description="Markdown")
    further_reading: list[str] = Field(default_factory=list,
                                       description="Only resources already listed in the syllabus")

    figure: Figure | None = Field(default=None, description="Optional diagram or generated dataset/chart")

class LearningResourceItem(_M):
    tags: Tags
    body: LearningResourceBody


# ---- rubric -----------------------------------------------------------------
class RubricLevel(_M):
    label: str
    points: float
    descriptor: str


class RubricCriterion(_M):
    criterion: str
    clo_numbers: list[int] = Field(default_factory=list)
    levels: list[RubricLevel] = Field(min_length=2)


class RubricBody(_M):
    title: str
    task: str
    criteria: list[RubricCriterion] = Field(min_length=1)


class RubricItem(_M):
    tags: Tags
    body: RubricBody


# ---- code exercise (plan 2.19) ----------------------------------------------
class CodeExerciseBody(_M):
    language: Literal["python"] = "python"
    prompt: str
    starter_code: str = Field(description="Code the student starts from (function stubs)")
    figure: Figure | None = None


class CodeExerciseKey(_M):
    solution_code: str = Field(description="Reference solution; must pass tests_code")
    tests_code: str = Field(description="Hidden tests: functions named test_* using plain assert, after "
                                         "'from solution import *'")
    explanation: str


class CodeExerciseItem(_M):
    tags: Tags
    body: CodeExerciseBody
    answer_key: CodeExerciseKey
    feedback: FeedbackPrompts


ITEM_MODELS: dict[str, type[_M]] = {
    "mcq": MCQItem,
    "short_answer": ShortAnswerItem,
    "problem": ProblemItem,
    "practice_set": PracticeSetItem,
    "code_exercise": CodeExerciseItem,
    "lesson_plan": LessonPlanItem,
    "case_study": CaseStudyItem,
    "learning_resource": LearningResourceItem,
    "rubric": RubricItem,
}


def batch_model(item_type: str) -> type[BaseModel]:
    """{'items': [<item>, ...]} for one generation call."""
    inner = ITEM_MODELS[item_type]
    return create_model(f"{inner.__name__}Batch", __base__=_M, items=(list[inner], Field(min_length=1)))  # type: ignore[valid-type]


def split_item(item_type: str, item: BaseModel) -> dict:
    """Model output -> the stored parts of an Item row."""
    d = item.model_dump(mode="json")
    return {
        "tags": d["tags"],
        "body": d["body"],
        "answer_key": d.get("answer_key"),
        "feedback": d.get("feedback"),
    }


def validate_parts(item_type: str, tags: dict, body: dict, answer_key: dict | None, feedback: dict | None) -> BaseModel:
    """Re-validate stored/edited parts against the type's schema (raises ValidationError)."""
    payload: dict = {"tags": tags, "body": body}
    fields = ITEM_MODELS[item_type].model_fields
    if "answer_key" in fields:
        payload["answer_key"] = answer_key
    if "feedback" in fields:
        payload["feedback"] = feedback
    return ITEM_MODELS[item_type].model_validate(payload)
