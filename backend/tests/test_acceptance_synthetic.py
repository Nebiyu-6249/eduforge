"""Acceptance seed (HANDOFF §9): the validator must raise every listed issue.

Runs on synthetic DOCX/PDF stand-ins for the five sample syllabi, end to end
(file bytes -> parser -> mapper -> validator). When the team supplies the real
files, ``test_acceptance_real.py`` runs the same expectations on them.
"""

from __future__ import annotations

import pytest

from app.extraction.pipeline import extract
from app.validation.rules import validate
from tests.synth.render import to_docx, to_pdf
from tests.synth.specs import ALLOWED_EXTRA, COURSES, EXPECTED, build


def _file(name: str) -> tuple[str, bytes]:
    course, fmt = COURSES[name]
    items = build(course)
    data = to_pdf(items) if fmt == "pdf" else to_docx(items)
    return f"{name}.{fmt}", data


@pytest.fixture(scope="module", params=sorted(COURSES))
def case(request):
    name = request.param
    fname, data = _file(name)
    rec = extract(fname, data)
    return name, rec, validate(rec)


def test_core_fields_extracted(case):
    name, rec, _ = case
    course, _ = COURSES[name]
    assert rec.course.code == course["code"]
    assert rec.course.title == course["title"]
    assert rec.offering.term == course["term"]
    assert len(rec.clos) == len(course["clos"])
    assert [c.text for c in rec.clos] == course["clos"]
    assert len(rec.weekly) == 16, [w.week_no for w in rec.weekly]
    assert [w.week_no for w in rec.weekly] == list(range(1, 17))
    assert len(rec.programs) == len(course["programs"])
    for got, want in zip(rec.programs, course["programs"]):
        assert got.name == want["name"]
        assert len(got.plos) == len(want["plos"])
        assert sorted(got.abet_addressed) == sorted(want["addressed"])
        want_links = {(c, p, s) for c, m in want["mapping"].items() for p, s in m.items()}
        got_links = {(link.clo, link.plo, link.strength[0].upper()) for link in got.clo_plo}
        assert got_links == want_links


def test_expected_issues_flagged(case):
    name, _, flags = case
    missing = []
    for rule, needle in EXPECTED[name]:
        if not any(f.rule_id == rule and needle.lower() in f.message.lower() for f in flags):
            missing.append((rule, needle))
    assert not missing, "Missing flags:\n" + "\n".join(map(str, missing)) + "\n\nGot:\n" + "\n".join(
        f"{f.rule_id} [{f.severity}] {f.message}" for f in flags)


def test_no_unexpected_blocking_flags(case):
    name, _, flags = case
    allowed = {r for r, _ in EXPECTED[name]} | ALLOWED_EXTRA[name]
    unexpected = [f for f in flags if f.severity != "info" and f.rule_id not in allowed]
    assert not unexpected, "\n".join(f"{f.rule_id} [{f.severity}] {f.message}" for f in unexpected)


def test_csci372_is_clean():
    _, data = _file("CSCI372")
    flags = validate(extract("CSCI372.pdf", data))
    assert [f for f in flags if f.severity != "info"] == []


def test_stat100_two_sections_and_continuation_rows():
    _, data = _file("STAT100")
    rec = extract("STAT100.pdf", data)
    assert len(rec.offering.meetings) == 2
    assert rec.course.prerequisites is None


def test_csci372_page_split_table_is_stitched():
    _, data = _file("CSCI372")
    rec = extract("CSCI372.pdf", data)
    w15 = next(w for w in rec.weekly if w.week_no == 15)
    assert w15.topics == ["Data-flow analysis", "Loop optimizations"]


def test_ceng401_week5_two_assessments_share_clos():
    _, data = _file("CENG401")
    rec = extract("CENG401.pdf", data)
    w5 = next(w for w in rec.weekly if w.week_no == 5)
    assert [a.name for a in w5.assessments] == ["Quiz #1", "AWS Lab 1"]
    assert w5.clo_numbers == [1, 2]
