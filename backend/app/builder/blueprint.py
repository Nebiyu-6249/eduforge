"""Blueprints from the locked syllabus (plan 3.1).

For an assessment row (e.g. "Midterm 25%, weeks 1–7, CLO 1–2") derive coverage
targets: weeks, CLO shares, item types and counts, Bloom and difficulty mix,
time and total points. Faculty can edit every value before building.
"""

from __future__ import annotations

from app.drafts import bloom
from app.extraction.normalize import canonical_name, category_of
from app.extraction.schema import ExtractedSyllabus
from app.validation.matching import match_all

# Defaults per assessment category: item counts by type and time (minutes; 0 = take-home).
_DEFAULTS: dict[str, tuple[dict[str, int], int]] = {
    "quiz": ({"mcq": 7, "short_answer": 3}, 20),
    "test": ({"mcq": 12, "short_answer": 5, "problem": 3}, 60),
    "midterm": ({"mcq": 12, "short_answer": 5, "problem": 3}, 75),
    "final": ({"mcq": 15, "short_answer": 8, "problem": 7}, 120),
    "homework": ({"problem": 4, "short_answer": 2}, 0),
    "lab": ({"code_exercise": 2, "problem": 2}, 0),
    "project": ({"case_study": 1}, 0),
}
MINUTES_PER_ITEM = {"mcq": 1.5, "short_answer": 4, "problem": 8, "code_exercise": 15, "practice_set": 10,
                    "case_study": 25, "rubric": 0, "lesson_plan": 0, "learning_resource": 0}
POINT_WEIGHT = {"mcq": 1, "short_answer": 3, "problem": 6, "code_exercise": 8, "practice_set": 5, "case_study": 10}


def assessment_rows(rec: ExtractedSyllabus) -> list[dict]:
    """The syllabus's assessments, merged from the weight table and the schedule."""
    m = match_all(rec)
    rows: list[dict] = []
    seen: set[str] = set()
    for wi, ai, a in rec.scheduled_assessments():
        key = f"{canonical_name(a.name)}@{rec.weekly[wi].week_no}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({"name": a.name, "category": category_of(a.name), "week": a.due_week or rec.weekly[wi].week_no,
                     "weight_pct": a.weight_pct, "clos": sorted(set(rec.weekly[wi].clo_numbers))})
    matrix = {canonical_name(me.assessment): me.clo_numbers for me in rec.clo_matrix}
    for i, w in enumerate(rec.weights):
        if not m.weight_to_sched[i].sched:  # weight-table rows with no schedule entry
            rows.append({"name": w.name, "category": category_of(w.name), "week": None, "weight_pct": w.weight_pct,
                         "clos": sorted(matrix.get(canonical_name(w.name), []))})
    for r in rows:
        r["clos"] = sorted(set(r["clos"]) | set(matrix.get(canonical_name(r["name"]), [])))
    return rows


def derive(rec: ExtractedSyllabus, name: str, week: int | None = None) -> dict:
    rows = assessment_rows(rec)
    row = next((r for r in rows if r["name"] == name and (week is None or r["week"] == week)), None)
    if row is None:
        row = next((r for r in rows if canonical_name(r["name"]) == canonical_name(name)), None)
    if row is None:
        raise ValueError(f"'{name}' isn't an assessment in the locked syllabus.")
    cat = row["category"] or "quiz"
    types, minutes = _DEFAULTS.get(cat, _DEFAULTS["quiz"])
    all_weeks = sorted(w.week_no for w in rec.weekly)
    # Weeks covered: since the previous assessment of the same category, up to the
    # week before this one (the exam week itself is usually review).
    due = row["week"] or (all_weeks[-1] if all_weeks else 1)
    earlier = [r["week"] for r in rows if r["category"] == cat and r["week"] and r["week"] < due]
    start = (max(earlier) if earlier and cat in {"quiz", "homework", "lab"} else 0) + 1
    if cat == "final":
        start = 1
    end = due - 1 if due > start else due
    weeks = [w for w in all_weeks if start <= w <= end] or [due]
    clos = row["clos"] or [c.number for c in rec.clos]
    texts = {c.number: c.text for c in rec.clos}
    levels = [lv for c in clos if (lv := bloom.clo_level(texts.get(c, "")))]
    bloom_mix = {lv: round(levels.count(lv) / len(levels), 2) for lv in sorted(set(levels), key=bloom.LEVELS.index)}
    return {
        "assessment": row["name"],
        "category": cat,
        "weight_pct": row["weight_pct"],
        "weeks": weeks,
        "clo_shares": {str(c): round(1 / len(clos), 3) for c in clos},
        "types": dict(types),
        "minutes": minutes,
        "total_points": 100,
        "bloom_mix": bloom_mix or {"apply": 1.0},
        "difficulty_mix": {"easy": 0.3, "medium": 0.5, "hard": 0.2},
        "avoid_used_in_last_terms": 2,
    }
