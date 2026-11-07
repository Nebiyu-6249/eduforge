"""The ten questions and the thirty students of the grading demo.

Everything here is invented. The students do not exist, the emails are on
example.edu, and the answers were written to exercise the grading pipeline:
a roughly normal spread of ability, the tempting wrong option chosen more
often than the others, numeric answers that are right but rounded
differently, short answers from excellent to off-topic, two blanks, two
students who wrote the same sentence, and one answer that names the student
and gives a phone number, so the anonymisation step has something to remove.

Importing this module has no side effects; ``seed_demo.py`` writes the CSVs
and builds the demo, and ``fixtures/demo/`` holds the same CSVs for anyone who
wants to upload them by hand.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# The quiz: 6 multiple-choice, 2 numeric, 2 short answer, on STAT 100.
# --------------------------------------------------------------------------- #


@dataclass
class DemoQuestion:
    type: str  # mcq | problem | short_answer
    clo: int
    week: int
    points: float
    body: dict
    answer_key: dict
    feedback: dict = field(default_factory=dict)
    # How students answer it, for the synthetic submissions.
    correct: str = ""
    tempting: str = ""  # the wrong answer good students still fall for
    others: list[str] = field(default_factory=list)


def _mcq(stem: str, options: list[tuple[str, str]], correct: str, why: str, wrong: dict[str, str],
         clo: int, week: int, tempting: str) -> DemoQuestion:
    return DemoQuestion(
        type="mcq", clo=clo, week=week, points=2,
        body={"stem": stem, "options": [{"label": lb, "text": tx} for lb, tx in options]},
        answer_key={"correct": correct, "why_correct": why, "why_others_wrong": wrong},
        feedback={"hint": "Read the question again and name what is being asked for.",
                  "explanation": why},
        correct=correct, tempting=tempting,
        others=[lb for lb, _ in options if lb not in (correct, tempting)],
    )


MCQS = [
    _mcq("Which measure of center is most affected by one unusually large value?",
         [("A", "The median"), ("B", "The mean"), ("C", "The mode"), ("D", "The interquartile range")],
         "B", "The mean adds every value, so one very large value pulls it up. The median only depends on "
              "the middle position.",
         {"A": "The median is the middle value, so one extreme value barely moves it.",
          "C": "The mode is the most frequent value and ignores how large the others are.",
          "D": "The interquartile range measures spread, not center."},
         clo=1, week=3, tempting="A"),
    _mcq("A histogram of exam marks has a long tail to the right. What does that say about the marks?",
         [("A", "Most students scored high, with a few low scores"),
          ("B", "Most students scored low, with a few high scores"),
          ("C", "The marks are symmetric around the mean"),
          ("D", "The marks have no mode")],
         "B", "A tail to the right means the few unusual values are the large ones, so most of the marks "
              "sit on the left, at the lower end.",
         {"A": "That would give a tail to the left.",
          "C": "A symmetric shape has tails of the same length on both sides.",
          "D": "A skewed shape still has a most common value."},
         clo=1, week=2, tempting="A"),
    _mcq("Two events cannot both happen at the same time. What is the probability that either one happens?",
         [("A", "The product of their probabilities"),
          ("B", "The sum of their probabilities"),
          ("C", "The sum minus the product"),
          ("D", "Always 1")],
         "B", "For events that cannot overlap there is nothing counted twice, so the probabilities add.",
         {"A": "Multiplying gives the probability that both happen, and here they cannot.",
          "C": "Subtracting the overlap is for events that can happen together.",
          "D": "The two events need not cover every possible outcome."},
         clo=2, week=4, tempting="C"),
    _mcq("A fair coin is tossed 10 times. Which distribution describes the number of heads?",
         [("A", "Normal"), ("B", "Binomial"), ("C", "Uniform"), ("D", "Exponential")],
         "B", "A fixed number of independent tosses, each with the same chance of heads, is exactly the "
              "binomial setting.",
         {"A": "The normal distribution is continuous; the number of heads is a whole number.",
          "C": "A uniform distribution would make 0 heads as likely as 5, which it is not.",
          "D": "The exponential distribution describes waiting times, not counts."},
         clo=3, week=6, tempting="A"),
    _mcq("A 95% confidence interval for a mean is 12.4 to 15.6. Which statement is correct?",
         [("A", "95% of the data lies between 12.4 and 15.6"),
          ("B", "There is a 95% chance the sample mean is between 12.4 and 15.6"),
          ("C", "If the study were repeated many times, about 95% of such intervals would contain the true mean"),
          ("D", "The true mean is 14.0")],
         "C", "The confidence level describes the method over many repeats, not one interval and not the "
              "spread of the data.",
         {"A": "A confidence interval is about the mean, not about where individual values fall.",
          "B": "The sample mean is already known: it is the middle of the interval.",
          "D": "14.0 is the middle of the interval, not a value the interval proves."},
         clo=4, week=10, tempting="A"),
    _mcq("A test gives a p-value of 0.03 with a significance level of 0.05. What do you conclude?",
         [("A", "Reject the null hypothesis"),
          ("B", "Accept the null hypothesis"),
          ("C", "The null hypothesis is 3% likely to be true"),
          ("D", "The result has no practical importance")],
         "A", "The p-value is below the significance level, so the evidence against the null hypothesis is "
              "strong enough to reject it at that level.",
         {"B": "A test never proves the null hypothesis; it either rejects it or fails to.",
          "C": "The p-value is the chance of data this extreme if the null were true, not the chance the "
               "null is true.",
          "D": "Statistical significance says nothing on its own about how large the effect is."},
         clo=4, week=12, tempting="C"),
]

NUMERIC = [
    DemoQuestion(
        type="problem", clo=1, week=3, points=6,
        body={"statement": "A sample of five measurements is 4, 8, 9, 12 and 17. Compute the sample mean.",
              "given": [{"name": "total", "value": 50.0, "description": "the five values added"},
                        {"name": "n", "value": 5.0, "description": "how many values"}],
              "asks_for": "the sample mean"},
        answer_key={"solution_steps": ["Add the values: 4 + 8 + 9 + 12 + 17 = 50", "Divide by 5", "Mean = 10"],
                    "final_answer_text": "10", "numeric_answer": 10.0,
                    "answer_expression": "total / n", "tolerance": 0.05},
        feedback={"hint": "Add them all, then divide by how many there are.",
                  "explanation": "The sample mean is the total divided by the count."},
        correct="10"),
    DemoQuestion(
        type="problem", clo=4, week=10, points=6,
        body={"statement": "A sample of 36 has mean 52 and standard deviation 6. Compute the standard error "
                           "of the mean, to two decimal places.",
              "given": [{"name": "s", "value": 6.0, "unit": "marks"}, {"name": "n", "value": 36.0}],
              "asks_for": "the standard error of the mean"},
        answer_key={"solution_steps": ["Standard error = s divided by the square root of n",
                                       "The square root of 36 is 6", "6 / 6 = 1.00"],
                    "final_answer_text": "1.00", "numeric_answer": 1.0,
                    "answer_expression": "s / (n ** 0.5)", "tolerance": 0.05},
        feedback={"hint": "Divide the standard deviation by the square root of the sample size.",
                  "explanation": "The standard error shrinks as the sample grows."},
        correct="1.00"),
]

SHORT = [
    DemoQuestion(
        type="short_answer", clo=1, week=3, points=5,
        body={"question": "In two or three sentences, explain when the median describes a set of marks "
                          "better than the mean.",
              "expected_length": "2 to 3 sentences"},
        answer_key={"model_answer": "The median is better when the marks are skewed or contain a few very "
                                    "high or very low values. The mean is pulled towards those extremes, so "
                                    "it stops describing a typical student, while the median stays at the "
                                    "middle of the class.",
                    "key_points": ["mentions skew or outliers", "says the mean is pulled by extreme values",
                                   "says the median stays at the middle"]},
        feedback={"hint": "Think about what one very large value does to each one.",
                  "explanation": "Resistance to extreme values is the whole difference."}),
    DemoQuestion(
        type="short_answer", clo=4, week=12, points=5,
        body={"question": "A classmate says 'the p-value is the probability that the null hypothesis is "
                          "true'. In two or three sentences, say why that is wrong and what the p-value "
                          "actually is.",
              "expected_length": "2 to 3 sentences"},
        answer_key={"model_answer": "The p-value does not give the probability of a hypothesis. It is the "
                                    "probability of getting data at least as extreme as the data observed, "
                                    "assuming the null hypothesis is true. A small p-value therefore says "
                                    "the data would be surprising under the null hypothesis, not that the "
                                    "null hypothesis is unlikely.",
                    "key_points": ["says the p-value is not the probability of the hypothesis",
                                   "defines it as the chance of data this extreme",
                                   "says it assumes the null hypothesis is true"]},
        feedback={"hint": "What is held fixed when the p-value is computed?",
                  "explanation": "The p-value conditions on the null hypothesis, not the other way round."}),
]

QUESTIONS: list[DemoQuestion] = [*MCQS, NUMERIC[0], SHORT[0], NUMERIC[1], SHORT[1]]
TOTAL_POINTS = sum(q.points for q in QUESTIONS)

# --------------------------------------------------------------------------- #
# The class: 30 invented students.
# --------------------------------------------------------------------------- #

FIRST = ["Aisha", "Omar", "Fatima", "Yousef", "Mariam", "Khalid", "Noura", "Hamad", "Layla", "Saeed",
         "Hessa", "Rashid", "Amna", "Sultan", "Shamma", "Ali", "Maitha", "Abdulla", "Reem", "Zayed",
         "Priya", "Arjun", "Sara", "Daniel", "Nour", "Ibrahim", "Lina", "Tariq", "Hana", "Yara"]
LAST = ["Al Naqbi", "Al Shamsi", "Al Zaabi", "Al Mazrouei", "Al Blooshi", "Al Suwaidi", "Al Ali",
        "Al Hammadi", "Al Ketbi", "Al Dhaheri", "Haddad", "Khoury", "Nair", "Fernandes", "Rahman",
        "Siddiqui", "Osman", "Bakr", "Farah", "Mansour", "Iqbal", "Devi", "Costa", "Mustafa", "Habib",
        "Saleh", "Younis", "Aziz", "Rizvi", "Qasim"]


@dataclass
class DemoStudent:
    student_id: str
    name: str
    email: str
    ability: float  # 0..1, how likely they are to get a question right


def students(seed: int = 20261101) -> list[DemoStudent]:
    """Thirty invented students with a spread of ability around 68%."""
    rng = random.Random(seed)
    out = []
    for i in range(30):
        first, last = FIRST[i], LAST[i]
        ability = min(0.97, max(0.18, rng.gauss(0.68, 0.17)))
        handle = f"{first.lower()}.{last.lower().replace(' ', '')}"
        out.append(DemoStudent(student_id=f"2026{1000 + i}", name=f"{first} {last}",
                               email=f"{handle}@example.edu", ability=round(ability, 3)))
    return out


# Short answers of different quality, for the two written questions.
_SHORT_POOL = {
    0: {
        "strong": ("The median is better when the marks are skewed or a few students score far from the "
                   "rest. Those extreme marks drag the mean away from the middle, so it stops describing a "
                   "typical student, while the median stays where most of the class is."),
        "fair": ("The median is better when there are outliers, because the mean gets pulled by them. The "
                 "median is the middle value so it is not affected as much."),
        "weak": "The median is the middle number and the mean is the average. Sometimes the median is better.",
        "off": "The median and the mean are both measures of spread, like the standard deviation and range.",
    },
    1: {
        "strong": ("It is wrong because the p-value says nothing about the probability of a hypothesis. It is "
                   "the probability of seeing data at least as extreme as ours if the null hypothesis were "
                   "true, so a small p-value means the data would be surprising under the null hypothesis."),
        "fair": ("The p-value is the chance of getting results like ours assuming the null hypothesis is "
                 "true. It is not the chance the hypothesis is true."),
        "weak": "The p-value is not the probability of the hypothesis. It is about the data.",
        "off": "A p-value under 0.05 means the experiment worked and the result is important.",
    },
}

# Numeric answers: right, right but rounded differently, and wrong.
_NUMERIC_POOL = {
    0: {"strong": "10", "rounded": "10.0", "fair": "10.00", "weak": "9.8", "off": "50"},
    1: {"strong": "1.00", "rounded": "1", "fair": "0.9999", "weak": "1.2", "off": "6"},
}

# One answer that names the student and gives a phone number: the
# anonymisation step must strip both before anything reaches a model.
LEAKY_INDEX = 7
LEAKY_TEMPLATE = ("My name is {name} and my student number is {sid}, you can reach me on 050 412 7788. "
                  "The median is better when there are outliers because the mean is pulled towards them.")

# Two students write the same sentence, so the consistency check has something
# to find.
TWIN_A, TWIN_B = 12, 19
TWIN_TEXT = ("The median is better when the data has outliers because the mean is affected by extreme "
             "values and the median is not.")


def answers(seed: int = 20261101) -> list[tuple[DemoStudent, dict[int, str]]]:
    """(student, {question number -> answer}) for all 30 students."""
    rng = random.Random(seed + 1)
    rows = []
    for idx, st in enumerate(students(seed)):
        row: dict[int, str] = {}
        for n, q in enumerate(QUESTIONS, 1):
            row[n] = _answer_for(rng, st, idx, n, q)
        rows.append((st, row))
    return rows


def _answer_for(rng: random.Random, st: DemoStudent, idx: int, n: int, q: DemoQuestion) -> str:
    if q.type == "mcq":
        if rng.random() < st.ability:
            return q.correct
        # The tempting distractor takes most of the wrong answers.
        return q.tempting if rng.random() < 0.6 else rng.choice(q.others or [q.tempting])

    if q.type == "problem":
        pool = _NUMERIC_POOL[0 if n == 7 else 1]
        r = rng.random()
        if r < st.ability * 0.7:
            return pool["strong"]
        if r < st.ability:
            return pool["rounded"] if rng.random() < 0.5 else pool["fair"]
        return pool["weak"] if rng.random() < 0.7 else pool["off"]

    # short answer
    which = 0 if n == 8 else 1
    if which == 0 and idx == LEAKY_INDEX:
        return LEAKY_TEMPLATE.format(name=st.name, sid=st.student_id)
    if which == 0 and idx in (TWIN_A, TWIN_B):
        return TWIN_TEXT
    if idx in (24, 28) and which == 1:  # two blanks on the last question
        return ""
    r = rng.random()
    pool = _SHORT_POOL[which]
    if r < st.ability * 0.55:
        return pool["strong"]
    if r < st.ability:
        return pool["fair"]
    if r < st.ability + 0.25:
        return pool["weak"]
    return pool["off"]


def roster_csv(seed: int = 20261101) -> str:
    lines = ["Student ID,Name,Email"]
    lines += [f"{s.student_id},{s.name},{s.email}" for s in students(seed)]
    return "\n".join(lines) + "\n"


def answers_csv(seed: int = 20261101) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Student ID", *[f"Q{i}" for i in range(1, len(QUESTIONS) + 1)]])
    for st, row in answers(seed):
        w.writerow([st.student_id, *[row[i] for i in range(1, len(QUESTIONS) + 1)]])
    return buf.getvalue()


__all__ = ["QUESTIONS", "TOTAL_POINTS", "DemoQuestion", "DemoStudent", "answers", "answers_csv",
           "roster_csv", "students"]


# --------------------------------------------------------------------------- #
# "Try it with a sample class": answers that fit whatever paper is open.
# --------------------------------------------------------------------------- #

GENERIC_SHORT = {
    "strong": ("The key idea is that the method only works under the conditions we were given, so I checked "
               "each one before applying it and said what the result means for the question asked."),
    "fair": ("I used the method from the lecture and got a result that looks reasonable, though I am not "
             "certain about the last condition."),
    "weak": "I think it is about the formula we did in class.",
    "off": "This topic was not covered properly so I could not answer it.",
}


def sample_answers_for_form(questions: list[dict], seed: int = 20261101) -> list[tuple[DemoStudent, dict[int, str]]]:
    """Answers for an arbitrary paper, so the sample class works on any quiz.

    ``questions`` is one dict per question, in order, with ``type`` and — for
    multiple choice — ``options`` (the letters as the student sees them) and
    ``correct``; for numeric questions, ``numeric_answer``.
    """
    rng = random.Random(seed + 2)
    rows = []
    for idx, st in enumerate(students(seed)):
        row: dict[int, str] = {}
        for n, q in enumerate(questions, 1):
            row[n] = _generic_answer(rng, st, idx, n, q)
        rows.append((st, row))
    return rows


def _generic_answer(rng: random.Random, st: DemoStudent, idx: int, n: int, q: dict) -> str:
    kind = q.get("type")
    if kind == "mcq":
        labels = [str(x) for x in (q.get("options") or ["A", "B", "C", "D"])]
        correct = str(q.get("correct") or labels[0])
        wrong = [x for x in labels if x != correct] or [correct]
        if rng.random() < st.ability:
            return correct
        # The first wrong option takes more than its share: the tempting one.
        return wrong[0] if rng.random() < 0.55 else rng.choice(wrong)
    if kind in ("problem", "numeric"):
        value = q.get("numeric_answer")
        if value is None:
            return GENERIC_SHORT["fair"]
        r = rng.random()
        if r < st.ability * 0.7:
            return f"{value:g}"
        if r < st.ability:
            return f"{round(float(value), 1):g}"  # right, rounded differently
        return f"{float(value) * rng.choice([0.5, 1.5, 2]):g}"
    # Everything written: two blanks, two identical answers, one with an identity in it.
    if idx == LEAKY_INDEX and n == 1:
        return LEAKY_TEMPLATE.format(name=st.name, sid=st.student_id)
    if idx in (TWIN_A, TWIN_B):
        return TWIN_TEXT
    if idx in (24, 28):
        return ""
    r = rng.random()
    if r < st.ability * 0.55:
        return GENERIC_SHORT["strong"]
    if r < st.ability:
        return GENERIC_SHORT["fair"]
    if r < st.ability + 0.25:
        return GENERIC_SHORT["weak"]
    return GENERIC_SHORT["off"]


def sample_answers_csv(questions: list[dict], seed: int = 20261101) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Student ID", *[f"Q{i}" for i in range(1, len(questions) + 1)]])
    for st, row in sample_answers_for_form(questions, seed):
        w.writerow([st.student_id, *[row[i] for i in range(1, len(questions) + 1)]])
    return buf.getvalue()
