"""The assessment reconciliation view and the one-save fix behind it.

The view puts the three places an assessment lives (weight table, CLO matrix,
weekly schedule) on one row, with the open flags that touch that row, so one
dialog can settle V2-V6 and V9 in a single logged save.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.extraction.pipeline import extract
from app.validation.overview import overview
from app.validation.rules import validate
from tests.synth.render import to_docx, to_pdf
from tests.synth.specs import CENG411, CSAI351, STAT100, build

A = {"X-Dev-User": "a.faculty@example.edu", "X-Dev-Name": "Dr A"}


@dataclass
class _StoredFlag:
    """A validator flag as the database stores it (id, status, evidence_refs)."""

    id: int
    rule_id: str
    severity: str
    message: str
    evidence_refs: list[str]
    status: str = "open"


def _view(spec: dict, fmt: str = "pdf"):
    data = to_pdf(build(spec)) if fmt == "pdf" else to_docx(build(spec))
    rec = extract(f"x.{fmt}", data)
    flags = [_StoredFlag(i, f.rule_id, f.severity, f.message, list(f.evidence))
             for i, f in enumerate(validate(rec), 1)]
    return rec, flags, overview(rec, flags)


def _row(ov, name: str):
    return next(r for r in ov.rows if r.name == name)


# --------------------------------------------------------------------------- #
# STAT 100: the matrix and the schedule disagree on all six assessments (V5),
# and three in-class assessments fall off the Tue/Thu meeting days (V9).
# --------------------------------------------------------------------------- #

def test_stat100_rows_hold_all_three_sides():
    _rec, _flags, ov = _view(STAT100)
    assert [r.name for r in ov.rows] == ["Quiz 1", "Quiz 2", "Midterm", "HW1", "HW2", "Final"]
    assert ov.meeting_days == ["tue", "thu"]
    assert ov.meeting_days_label == "Tue/Thu"
    assert ov.weight_total == 100
    assert ov.clo_numbers == [1, 2, 3, 4, 5]
    assert [w.week_no for w in ov.weeks] == list(range(1, 17))

    q1 = _row(ov, "Quiz 1")
    assert q1.weight is not None and q1.weight.weight_pct == 5
    assert q1.matrix is not None and q1.matrix.clo_numbers == [1]
    assert len(q1.schedule) == 1
    cell = q1.schedule[0]
    assert cell.week_no == 5 and cell.weight_pct == 5
    assert cell.due_date is not None and cell.due_date.isoformat() == "2026-09-23"
    assert cell.clo_numbers == [1, 2]  # the schedule's own CLO column
    assert q1.schedule_clo_numbers == [1, 2]
    assert q1.schedule_weight_total == 5
    assert q1.pointers == ["/weights/0", "/clo_matrix/0", "/weekly/4/assessments/0", "/weekly/4/clo_numbers"]


def test_stat100_rows_carry_their_own_flags():
    _rec, _flags, ov = _view(STAT100)
    for name in ("Quiz 1", "Quiz 2", "Midterm", "HW1", "HW2", "Final"):
        row = _row(ov, name)
        assert any(f.rule_id == "V5" for f in row.flags), (name, row.flags)
        assert row.status == "error"
    # V9: Quiz 1 (Wed), Midterm (Mon) and Quiz 2 (Mon) are not on Tue/Thu.
    assert any(f.rule_id == "V9" for f in _row(ov, "Quiz 1").flags)
    assert _row(ov, "Quiz 1").schedule[0].due_on_meeting_day is False
    assert any(f.rule_id == "V9" for f in _row(ov, "Midterm").flags)
    # The final sits in the exam period, so V9 leaves it alone and it has a date-free cell.
    assert _row(ov, "Final").schedule[0].due_date is None
    # Every assessment flag the validator raised is on some row.
    assert ov.unrowed_flags == []


# --------------------------------------------------------------------------- #
# CENG 411: a category row claiming nothing, and schedule items with no
# weight-table entry (HW1-HW4), which must still get a row.
# --------------------------------------------------------------------------- #

def test_ceng411_weight_only_and_schedule_only_rows():
    _rec, _flags, ov = _view(CENG411, "docx")
    names = [r.name for r in ov.rows]
    assert names[:5] == ["Midterm", "Final", "Project", "IBM Certification", "Other Activities"]

    # In the weight table, missing from the schedule (V3): a row with no schedule cells.
    ibm = _row(ov, "IBM Certification")
    assert ibm.schedule == [] and ibm.weight is not None and ibm.weight.weight_pct == 10
    assert any(f.rule_id == "V3" for f in ibm.flags)

    # In the schedule, missing from the weight table (V3): HW1-HW4 as one row.
    hw = next(r for r in ov.rows if r.key == "homework")
    assert hw.weight is None
    assert [c.name for c in hw.schedule] == ["HW1", "HW2", "HW3", "HW4"]
    assert hw.schedule_weight_total == 20
    assert any(f.rule_id == "V3" for f in hw.flags)

    # V2: the weight table says 25% for the midterm, the schedule says 20%.
    mid = _row(ov, "Midterm")
    assert mid.weight is not None and mid.weight.weight_pct == 25
    assert mid.schedule_weight_total == 20
    assert any(f.rule_id == "V2" for f in mid.flags)


def test_csai351_category_rows_claim_their_instances():
    _rec, _flags, ov = _view(CSAI351, "docx")
    quizzes = _row(ov, "Quizzes")
    assert quizzes.by_category is True
    assert [c.week_no for c in quizzes.schedule] == [5, 12]
    assert quizzes.schedule_weight_total == 15  # 10% + 5%
    # V4: both scheduled quizzes are called "Quiz #1".
    assert any(f.rule_id == "V4" for f in quizzes.flags)


# --------------------------------------------------------------------------- #
# Through the API, including the single multi-op save the dialog makes.
# --------------------------------------------------------------------------- #

def _upload(client, spec, fmt):
    data = to_pdf(build(spec)) if fmt == "pdf" else to_docx(build(spec))
    mime = "application/pdf" if fmt == "pdf" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    r = client.post("/api/syllabi", headers=A, files={"file": (f"x.{fmt}", data, mime)})
    assert r.status_code == 202, r.text
    return r.json()["result"]["course_version_id"]


def test_overview_endpoint_and_one_save_clears_a_flag(env):
    client, _ = env
    cv = _upload(client, STAT100, "pdf")

    r = client.get(f"/api/course-versions/{cv}/assessment-overview", headers=A)
    assert r.status_code == 200, r.text
    ov = r.json()
    q1 = next(x for x in ov["rows"] if x["name"] == "Quiz 1")
    assert q1["status"] == "error"
    assert {f["rule_id"] for f in q1["flags"]} >= {"V5", "V9"}
    assert q1["matrix"]["clo_numbers"] == [1]
    assert q1["schedule"][0]["clo_numbers"] == [1, 2]

    before = {f["id"] for f in client.get(f"/api/course-versions/{cv}", headers=A).json()["flags"]
              if f["status"] == "open"}

    # What the dialog sends: the matrix CLOs, the schedule CLOs and a meeting-day
    # due date, all in one PATCH, so one save produces one coherent set of log entries.
    ops = [
        {"op": "replace", "path": "/clo_matrix/0/clo_numbers", "value": [1, 2]},
        {"op": "replace", "path": "/weekly/4/clo_numbers", "value": [1, 2]},
        {"op": "replace", "path": "/weekly/4/assessments/0/due_date", "value": "2026-09-24"},
    ]
    r = client.patch(f"/api/course-versions/{cv}/record", headers=A, json={"ops": ops})
    assert r.status_code == 200, r.text
    v = r.json()
    after = {f["id"] for f in v["flags"] if f["status"] == "open"}
    assert len(after) < len(before)

    ov = client.get(f"/api/course-versions/{cv}/assessment-overview", headers=A).json()
    q1 = next(x for x in ov["rows"] if x["name"] == "Quiz 1")
    assert q1["flags"] == [] and q1["status"] == "ok"
    assert q1["schedule"][0]["due_on_meeting_day"] is True

    # The three ops are one save in the log.
    edits = client.get(f"/api/course-versions/{cv}/edits", headers=A).json()
    assert len({e["group"] for e in edits}) == 1
    assert len(edits) == 3


def test_add_a_whole_assessment_in_one_save(env):
    """The "Add assessment" dialog creates the weight row, the matrix column and
    the schedule entry together, with real values and no placeholder stub."""
    client, _ = env
    cv = _upload(client, STAT100, "pdf")
    ops = [
        {"op": "add", "path": "/weights/-", "value": {"name": "Lab report", "weight_pct": 0}},
        {"op": "add", "path": "/clo_matrix/-", "value": {"assessment": "Lab report", "clo_numbers": [1]}},
        {"op": "add", "path": "/weekly/2/assessments/-",
         "value": {"name": "Lab report", "weight_pct": 0, "due_text_raw": None,
                   "due_date": "2026-09-10", "due_week": 3}},
    ]
    r = client.patch(f"/api/course-versions/{cv}/record", headers=A, json={"ops": ops})
    assert r.status_code == 200, r.text
    ov = client.get(f"/api/course-versions/{cv}/assessment-overview", headers=A).json()
    row = next(x for x in ov["rows"] if x["name"] == "Lab report")
    assert row["weight"]["weight_pct"] == 0
    assert row["matrix"]["clo_numbers"] == [1]
    assert [c["week_no"] for c in row["schedule"]] == [3]
    assert row["schedule"][0]["due_date"] == "2026-09-10"


def test_overview_is_owner_only(env):
    client, _ = env
    cv = _upload(client, STAT100, "pdf")
    other = {"X-Dev-User": "b.faculty@example.edu", "X-Dev-Name": "Dr B"}
    assert client.get(f"/api/course-versions/{cv}/assessment-overview", headers=other).status_code == 404


# --------------------------------------------------------------------------- #
# Edit log in plain English (no JSON on screen, readable CSV columns).
# --------------------------------------------------------------------------- #

def test_edit_log_reads_as_english(env):
    client, _ = env
    cv = _upload(client, STAT100, "pdf")
    ops = [
        {"op": "replace", "path": "/weekly/4/assessments/0/weight_pct", "value": 7},
        {"op": "replace", "path": "/weights/2/weight_pct", "value": 23},
        {"op": "replace", "path": "/clo_matrix/1/clo_numbers", "value": [1, 4]},
        {"op": "replace", "path": "/clos/2/text", "value": "Use distributions."},
        {"op": "replace", "path": "/weekly/4/assessments/0/due_date", "value": None},
    ]
    assert client.patch(f"/api/course-versions/{cv}/record", headers=A,
                        json={"ops": ops}).status_code == 200
    edits = {e["field_path"]: e for e in client.get(f"/api/course-versions/{cv}/edits", headers=A).json()}

    e = edits["/weekly/4/assessments/0/weight_pct"]
    assert e["label"] == "Week 5 - Quiz 1 - weight"
    assert e["old_text"] == "5%" and e["new_text"] == "7%" and e["op_label"] == "Changed"
    assert edits["/weights/2/weight_pct"]["label"] == "Weight table - Midterm - weight"
    assert edits["/clo_matrix/1/clo_numbers"]["label"] == "Assessment table - Quiz 2 - outcomes"
    assert edits["/clo_matrix/1/clo_numbers"]["new_text"] == "outcomes 1, 4"
    assert edits["/clos/2/text"]["label"] == "Outcome 3 - text"
    assert edits["/weekly/4/assessments/0/due_date"]["old_text"] == "23 Sep 2026"
    assert edits["/weekly/4/assessments/0/due_date"]["new_text"] == "empty"

    csv_text = client.get(f"/api/course-versions/{cv}/edits.csv", headers=A).text
    header = csv_text.splitlines()[0]
    assert header.startswith("when_utc,who,save,change,field,before,after,note")
    assert "raw_path" in header  # the audit columns are still there
    assert "Week 5 - Quiz 1 - weight" in csv_text


def test_removed_items_still_get_a_label(env):
    client, _ = env
    cv = _upload(client, STAT100, "pdf")
    r = client.patch(f"/api/course-versions/{cv}/record", headers=A,
                     json={"ops": [{"op": "remove", "path": "/weekly/4/assessments/0"}]})
    assert r.status_code == 200, r.text
    e = client.get(f"/api/course-versions/{cv}/edits", headers=A).json()[-1]
    assert e["op_label"] == "Removed"
    # The item is gone from the record, so its name comes from the stored old value.
    assert e["label"] == "Week 5 - Quiz 1"
    assert e["old_text"] == "Quiz 1, 5%, due 23 Sep 2026"
    assert e["new_text"] == "empty"


def test_add_and_derived_edits_read_as_english(env):
    client, _ = env
    cv = _upload(client, STAT100, "pdf")
    r = client.patch(f"/api/course-versions/{cv}/record", headers=A, json={"ops": [
        {"op": "add", "path": "/weights/-", "value": {"name": "Lab report", "weight_pct": 5}},
        {"op": "replace", "path": "/offering/class_timing_raw", "value": "Mon/Wed 9:00 - 10:15 AM"},
    ]})
    assert r.status_code == 200, r.text
    edits = client.get(f"/api/course-versions/{cv}/edits", headers=A).json()
    add = next(e for e in edits if e["op"] == "add")
    assert add["op_label"] == "Added" and add["new_text"] == "Lab report, 5%"
    derived = next(e for e in edits if e["op"] == "derive")
    assert derived["label"] == "Meeting days"
    assert derived["new_text"] == "Mon/Wed 9:00 - 10:15 AM"
    assert derived["op_label"] == "Changed (derived)"
