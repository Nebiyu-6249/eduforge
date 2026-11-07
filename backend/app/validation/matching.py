"""Match the same assessment across the weight table, the weekly schedule and
the CLO × assessment matrix.

The tables name things differently ('Quiz #1' vs 'Quiz 1', 'Homework' as a
category vs 'HW1'..'HW4' as instances), so matching goes:

1. exact canonical key ('quiz 1' == 'quiz 1');
2. a category-level weight entry ('Quizzes', 'Homework', 'Midterm') claims
   every *unclaimed* scheduled item of that category.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.extraction.normalize import canonical_name, category_of, is_category_name
from app.extraction.schema import ExtractedSyllabus, ScheduledAssessment

SchedRef = tuple[int, int]  # (week index, assessment index)


@dataclass
class Match:
    sched: list[SchedRef] = field(default_factory=list)
    by_category: bool = False


@dataclass
class Matching:
    weight_to_sched: dict[int, Match]
    matrix_to_sched: dict[int, Match]
    unmatched_sched: list[SchedRef]  # scheduled items with no weight-table entry
    weight_to_matrix: dict[int, int | None]


def _match(names: list[str], sched: list[tuple[SchedRef, ScheduledAssessment]]) -> tuple[dict[int, Match], set[SchedRef]]:
    claimed: set[SchedRef] = set()
    result: dict[int, Match] = {i: Match() for i in range(len(names))}
    keys = [canonical_name(n) for n in names]
    # Pass 1: exact canonical key.
    for i, k in enumerate(keys):
        for ref, a in sched:
            if canonical_name(a.name) == k:
                result[i].sched.append(ref)
                claimed.add(ref)
    # Pass 2: category-level entries take the remaining items of their category.
    for i, n in enumerate(names):
        if result[i].sched or not is_category_name(n):
            continue
        cat = category_of(n)
        for ref, a in sched:
            if ref not in claimed and category_of(a.name) == cat:
                result[i].sched.append(ref)
                result[i].by_category = True
        claimed.update(result[i].sched)
    return result, claimed


def match_all(rec: ExtractedSyllabus) -> Matching:
    sched = [((wi, ai), a) for wi, ai, a in rec.scheduled_assessments()]
    w_names = [w.name for w in rec.weights]
    m_names = [m.assessment for m in rec.clo_matrix]

    w_match, claimed = _match(w_names, sched)
    m_match, _ = _match(m_names, sched)

    m_keys = [canonical_name(n) for n in m_names]
    w_to_m: dict[int, int | None] = {}
    for i, n in enumerate(w_names):
        k = canonical_name(n)
        w_to_m[i] = m_keys.index(k) if k in m_keys else None

    unmatched = [ref for ref, _ in sched if ref not in claimed]
    return Matching(weight_to_sched=w_match, matrix_to_sched=m_match, unmatched_sched=unmatched,
                    weight_to_matrix=w_to_m)
