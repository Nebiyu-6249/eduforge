from datetime import date

import pytest

from app.extraction.normalize import (
    canonical_name,
    is_category_name,
    normalise_term,
    parse_assessment_cell,
    parse_clo_list,
    parse_due,
    parse_meetings,
)


@pytest.mark.parametrize("text,expected", [
    ("10 February 2026", (date(2026, 2, 10), None)),
    ("12-October", (date(2026, 10, 12), None)),
    ("16-Nov", (date(2026, 11, 16), None)),
    ("23-09-2026", (date(2026, 9, 23), None)),  # DD-MM-YYYY
    ("W4", (None, 4)),
    ("Due Week 10", (None, 10)),
    ("TBA", (None, None)),
    ("Wed 23 Sep", (date(2026, 9, 23), None)),
    ("Nov 9th, 2026", (date(2026, 11, 9), None)),
])
def test_parse_due_formats_from_samples(text, expected):
    assert parse_due(text, 2026) == expected


@pytest.mark.parametrize("raw,term", [
    ("Fall 2026", "Fall 2026"),
    ("Spring 2026", "Spring 2026"),
    ("Fall Semester 2026 / Academic Year 2026-2027", "Fall 2026"),
    ("Spring Semester, AY 2025-2026", "Spring 2026"),
    ("Fall, 2026-27", "Fall 2026"),
    ("Autumn 2026", "Fall 2026"),
    ("TBA", None),
])
def test_normalise_term(raw, term):
    assert normalise_term(raw) == term


def test_meetings_two_sections():
    m = parse_meetings("Section 1: Tue/Thu 3:00 - 4:15 PM; Section 2: Tue/Thu 4:30 - 5:45 PM")
    assert [x.days for x in m] == [["tue", "thu"], ["tue", "thu"]]
    assert m[1].time_text.startswith("4:30")


@pytest.mark.parametrize("text,days", [
    ("Monday & Wednesday 10:00-11:15", ["mon", "wed"]),
    ("MW 10:00 - 11:15", ["mon", "wed"]),
    ("TR 9:30", ["tue", "thu"]),
    ("TTh 9:30 AM", ["tue", "thu"]),
    ("Sunday, Tuesday, Thursday 8:00", ["tue", "thu", "sun"]),
])
def test_meeting_day_formats(text, days):
    assert parse_meetings(text)[0].days == days


@pytest.mark.parametrize("text,nums", [
    ("CLO 1, 2", [1, 2]),
    ("CLO1, CLO3", [1, 3]),
    ("1,2,4", [1, 2, 4]),
    ("CLOs 1-3", [1, 2, 3]),
    ("", []),
    ("-", []),
])
def test_clo_list(text, nums):
    assert parse_clo_list(text) == nums


def test_canonical_names_match_across_tables():
    assert canonical_name("Quiz #1") == canonical_name("Quiz 1") == "quiz 1"
    assert canonical_name("HW1") == canonical_name("Homework 1") == "homework 1"
    assert canonical_name("Midterm Exam") == canonical_name("Mid-term") == "midterm"
    assert canonical_name("Quizzes (2)") == "quiz"
    assert canonical_name("IBM Certification") == "certification"
    assert canonical_name("Other Activities") == "other activities"


def test_category_names():
    assert is_category_name("Quizzes")
    assert is_category_name("Homework Assignments")
    assert is_category_name("AWS Labs")
    assert is_category_name("Labs (4)")
    assert not is_category_name("Quiz 1")
    assert not is_category_name("Other Activities")


def test_assessment_cell_two_items_and_formats():
    items = parse_assessment_cell("Quiz #1 (5%) – 1-Oct\nAWS Lab 1 (5%) Due: 2-Oct", 2026)
    assert [(a.name, a.weight_pct, a.due_date) for a in items] == [
        ("Quiz #1", 5.0, date(2026, 10, 1)),
        ("AWS Lab 1", 5.0, date(2026, 10, 2)),
    ]
    one = parse_assessment_cell("HW2 (10%) Due Week 7", 2026)[0]
    assert (one.name, one.weight_pct, one.due_week) == ("HW2", 10.0, 7)
    assert parse_assessment_cell("-", 2026) == []
    assert parse_assessment_cell("Final Exam (25%) – TBA", 2026)[0].due_date is None
