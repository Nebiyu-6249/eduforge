"""Versioned prompts for Draft Studio. Bump a prompt's version on ANY wording
change: the version is stored with every item it produces."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm.gateway import Prompt

_SYSTEM = (
    "You draft teaching and assessment materials for a university instructor to review. Everything you write is "
    "a draft the instructor will edit, approve or reject. Write in clear academic English (the only classroom "
    "language). Stay strictly within the course context given: its CLOs, weekly topics and readings. Do not cite "
    "sources that are not in the course resources. Tag every item with the CLO numbers it serves, using only CLO "
    "numbers from the context. Write mathematics as LaTeX between $...$ (inline) or $$...$$ (display). "
    "Where a picture helps, add a 'figure': either a 'diagram' (Graphviz dot, Mermaid or PlantUML source, e.g. "
    "automata, parse trees, UML, network topologies) or a 'dataset' spec (kind, n, seed, params) that the "
    "system generates in code, optionally with a 'chart' drawn from it. Never write out data values or draw "
    "charts yourself; numbers about a generated dataset are computed by the system (names such as slope, "
    "intercept, r, mean_x, mean_y, mean, sd may be used in answer_expression). "
    "Reply with JSON only, matching the requested schema exactly."
)

_CONTEXT = (
    "COURSE: {code} {title}\n"
    "TERM: {term}\n"
    "DESCRIPTION: {description}\n\n"
    "COURSE LEARNING OUTCOMES (use these numbers):\n{clos}\n\n"
    "WEEKLY TOPICS:\n{weeks}\n\n"
    "COURSE RESOURCES:\n{resources}\n\n"
    "{grounding}"
)

_REQUEST = (
    "REQUEST\n"
    "- Produce exactly {count} item(s) of type: {type_label}.\n"
    "- Target CLO(s): {target_clos}\n"
    "- Target week(s): {target_weeks}\n"
    "- Difficulty: {difficulty}\n"
    "- Bloom level: {bloom}\n"
    "{type_rules}"
    "{avoid}"
    "{notes}"
)

_TYPE_RULES = {
    "mcq": (
        "- Each item: a stem, 4 options labelled A-D, exactly one correct option, why the key is correct, why "
        "each distractor is wrong, a hint and an explanation.\n"
        "- DISTRACTORS: every wrong option must be a mistake a competent student could actually make here - a "
        "common misconception, a rule applied in the wrong place, a swapped or inverted relationship, a unit or "
        "sign error, or a plausible-sounding but incorrect definition. Never write an option that is absurd, "
        "unrelated to the topic, or obviously wrong at a glance. Keep all four options the same kind of thing, "
        "similar in length and in level of detail, so length does not give the key away.\n"
        "- A multiple-choice question cannot evidence 'evaluate' or 'create': the highest level to aim for is "
        "'analyze'. If the CLO is higher, test the knowledge the CLO depends on instead.\n"
        "- Each item in this batch must test a DIFFERENT sub-topic or skill within the target CLO(s). Do not "
        "produce variations of one question with reworded stems; name a different concept in each.\n"
        "- Avoid 'all of the above' / 'none of the above'. Vary the position of the correct option.\n"
        "- Work the answer out BEFORE writing the item and set 'correct' to the option that matches it. "
        "'why_correct' gives the finished reasoning only: never show your working, never write 'wait', "
        "'let us check' or 'let us set correct to ...', and never change your mind inside the text. If you "
        "cannot settle on one option, write a different question instead.\n"
    ),
    "short_answer": (
        "- Each item: a question answerable in a few sentences, the expected length, a model answer and the key "
        "points a grader should look for, a hint and an explanation.\n"
        "- Each item in this batch must test a DIFFERENT sub-topic or skill within the target CLO(s).\n"
    ),
    "problem": (
        "- Each item: a problem statement with all needed values listed in 'given' (short identifier names), what "
        "it asks for, step-by-step solution, the final answer, and — when the answer is a single number — "
        "numeric_answer plus answer_expression that computes it from the given names so it can be checked in "
        "code.\n"
        "- Each item in this batch must test a DIFFERENT sub-topic or skill within the target CLO(s).\n"
    ),
    "practice_set": "- Each item: a titled set of 4-6 exercises with answers and short hints, building in difficulty.\n",
    "lesson_plan": (
        "- Each item: a plan for one class session of the target week: objectives tied to CLOs, timed activities "
        "that add up to the session length, materials, a check for understanding, and after-class work.\n"
    ),
    "case_study": (
        "- Each item: a realistic scenario (fictional organisations and people only) relevant to the target "
        "week's topics, 3-5 discussion questions with model answers, and teaching notes for the instructor.\n"
    ),
    "learning_resource": (
        "- Each item: a student-facing resource (summary, reading guide, glossary, worked example or study guide) "
        "in Markdown. 'further_reading' may list only resources from COURSE RESOURCES.\n"
    ),
    "code_exercise": (
        "- Each item: a Python programming exercise: a prompt, starter_code with function stubs (signatures and "
        "docstrings, bodies that are not yet correct), a complete solution_code, and tests_code with 4-8 functions "
        "named test_* using plain assert against the functions (they run after 'from solution import *'; no "
        "pytest, no network, no files, only the standard library). Include edge cases. The solution must pass "
        "every test and the starter code must fail at least one.\n"
    ),
    "rubric": (
        "- Each item: an analytic rubric for a task that evidences the target CLO(s), with 3-5 criteria, each with "
        "3-4 performance levels, points and observable descriptors.\n"
    ),
}

GEN_PROMPT_VERSION = "5"  # 2: grounding; 3: LaTeX, figures, code_exercise; 4: MCQ Bloom cap,
                          #    distractors and one sub-topic per item; 5: no visible working
                          #    in the answer key


def generation_prompt(item_type: str) -> Prompt:
    return Prompt(
        id=f"generate.{item_type}",
        version=GEN_PROMPT_VERSION,
        system=_SYSTEM,
        user=_CONTEXT + _REQUEST.replace("{type_rules}", _TYPE_RULES[item_type]),
    )


# ---- quality: LLM judge -----------------------------------------------------
JUDGE = Prompt(
    id="quality.judge",
    # 2: the reasons are shown to the teacher word for word, so they have to be
    #    in the words the rest of the tool uses: "outcome 3", never "CLO 3".
    version="2",
    system=(
        "You review draft assessment items for a university instructor. Score strictly with the rubric. "
        "Your reasons are shown to the teacher word for word: write 'outcome 3', never 'CLO 3', and do not "
        "mention rule ids, prompt versions or model names. Reply with JSON only."
    ),
    user=(
        "Learning outcome(s) the item claims to serve:\n{clos}\n\n"
        "Claimed Bloom level: {bloom}\n\n"
        "ITEM ({type_label}):\n{item}\n\n"
        "Score 1-5:\n"
        "- clo_alignment: 5 = the item directly requires the knowledge/skill in the outcome; 3 = related but "
        "partial; 1 = unrelated.\n"
        "- bloom_fit: 5 = the cognitive demand matches the claimed level; 3 = one level off; 1 = two or more off.\n"
        "Also give the Bloom level you think the item actually targets, and one sentence of reasoning for each "
        "score."
    ),
)


class JudgeVerdict(BaseModel):
    clo_alignment: int = Field(ge=1, le=5)
    clo_alignment_reason: str
    bloom_fit: int = Field(ge=1, le=5)
    bloom_fit_reason: str
    observed_bloom_level: str


# ---- quality: independent re-solve of an MCQ --------------------------------
RESOLVE_MCQ = Prompt(
    id="quality.resolve_mcq",
    version="1",
    system="You are a careful expert answering a multiple-choice question. Reply with JSON only.",
    user="{stem}\n\n{options}\n\nChoose the single best option. If two options are equally correct or none is, say so.",
)


class ResolveVerdict(BaseModel):
    answer: str = Field(description="option label")
    confident: bool
    problem: str | None = Field(default=None, description="e.g. 'B and D are both correct'")
