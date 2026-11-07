"""Acceptance on the REAL sample syllabi in fixtures/syllabi/ (HANDOFF §9).

Each test skips if its file isn't present (the files hold faculty names and
emails and are git-ignored). File names are matched by course code anywhere
in the name, e.g. 'CSCI 372 Course Syllabus - X.pdf' or 'stat100.pdf'.

Expectations come from the §9 table, phrased the way the real files name
things ('HW #1', 'Mid-term Exam', 'AWS LAB 2'), which differs from the
synthetic stand-ins.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.extraction.pipeline import extract
from app.validation.rules import validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "syllabi"

# code -> (term, CLO count, PLO count per program in appendix order)
FACTS = {
    "CSCI372": ("Spring 2026", 4, [6]),
    "CSAI351": ("Fall 2026", 3, [7]),
    "CENG411": ("Fall 2026", 5, [7, 6, 7]),
    "CENG401": ("Fall 2026", 4, [7, 6]),
    "STAT100": ("Fall 2026", 5, [4]),
}

# §9 issues as (rule, substring of the flag message).
EXPECTED = {
    "CSCI372": [],
    "CSAI351": [
        ("V4", "share the name 'quiz 1'"),
        ("V7", "outcome 6 is marked 'addressed', but no CLO maps to PLO 6"),
    ],
    "CENG411": [
        ("V2", "'Mid-term Exam' 25%, but the schedule gives 'Midterm' (week 8) 20%"),
        ("V3", "'HW #1' (week 3) 5%"),
        ("V3", "'IBM Certification' (10%) is in the weight table but not in the weekly schedule"),
        ("V3", "'Other Activities"),
        ("EX", "fused"),
        ("V7", "CLO 5→PLO 4 is Medium for Computer Engineering but High for Computer Science"),
        ("V7", "CLO 5→PLO 4 is Medium for Computer Engineering but High for Artificial Intelligence and Data Science"),
    ],
    "CENG401": [
        ("V11", "Additional Information"),
        ("V6", "'Quiz #2' (week 13) has no CLO"),
        ("V6", "'AWS LAB 2' (week 6) has no CLO"),
        ("V6", "'AWS LAB 4' (week 14) has no CLO"),
        ("V6", "Week 12 maps CLOs {2, 4} but lists no assessment"),
        ("V5", "'Quizzes (2)'"),
        ("V10", "See Syllabus Guide"),
    ],
    "STAT100": [
        ("V5", "Quiz 1"),
        ("V8", "CLO 5"),
        ("V9", "Quiz 1"),
        ("V9", "Midterm"),
        ("V9", "Quiz 2"),
        ("V12", "Prerequisite"),
    ],
}

# Extra rules that may fire on a real file without failing the test. V8 is a
# best-effort keyword check; on these files its findings are defensible (an
# assessment mapped to a CLO whose topic is taught later) but not in §9.
ALLOWED_EXTRA = {"CSCI372": set(), "CSAI351": {"V8"}, "CENG411": set(), "CENG401": {"V8"}, "STAT100": {"V8"}}


def _find(code: str) -> Path | None:
    if not FIXTURES.exists():
        return None
    pat = re.compile(re.sub(r"(\D+)(\d+)", r"\1[\\s_-]*\2", code), re.I)
    for p in sorted(FIXTURES.iterdir()):
        if p.suffix.lower() in {".pdf", ".docx"} and pat.search(p.stem):
            return p
    return None


@pytest.fixture(scope="module", params=sorted(FACTS))
def real(request):
    code = request.param
    path = _find(code)
    if path is None:
        pytest.skip(f"real {code} syllabus not in fixtures/syllabi/")
    rec = extract(path.name, path.read_bytes())
    return code, rec, validate(rec)


def _dump(flags) -> str:
    return "\n".join(f"  {f.rule_id} [{f.severity}] {f.message}" for f in flags)


def test_core_facts(real):
    code, rec, _ = real
    term, n_clos, plo_counts = FACTS[code]
    assert rec.course.code and rec.course.code.replace(" ", "") == code
    assert rec.course.title
    assert rec.offering.term == term
    assert rec.offering.meetings and rec.offering.meetings[0].days
    assert len(rec.clos) == n_clos
    assert [len(p.plos) for p in rec.programs] == plo_counts, [p.name for p in rec.programs]
    assert all(p.clo_plo for p in rec.programs), "every program should have a CLO→PLO mapping"
    assert round(sum(w.weight_pct or 0 for w in rec.weights)) == 100
    assert [w.week_no for w in rec.weekly] == list(range(1, 17))


def test_section9_issues_flagged(real):
    code, _, flags = real
    missing = [(r, s) for r, s in EXPECTED[code]
               if not any(f.rule_id == r and s.lower() in f.message.lower() for f in flags)]
    assert not missing, f"{code}: missing {missing}\nGot:\n{_dump(flags)}"


def test_nothing_unexpected_blocks_locking(real):
    code, _, flags = real
    allowed = {r for r, _ in EXPECTED[code]} | ALLOWED_EXTRA[code]
    extra = [f for f in flags if f.severity != "info" and f.rule_id not in allowed]
    assert not extra, f"{code}: unexpected flags\n{_dump(extra)}"
