"""Rosters and submission intake (plan 4.1, 4.2).

Rosters: CSV with a student ID column and optional name / first+last name /
email columns.

Submissions for an approved form:

* CSV of typed answers: the student ID column (and optional name/email), then
  one column per question: "Q1", "Question 1" or just "1", numbered as on the
  form. Calibration sets add the faculty member's marks as "M1"/"Marks 1".
* one file per student (PDF/DOCX/TXT), or a ZIP of them: the student ID must
  be in the file name ("20231234_essay.pdf"). Answers are split on question
  markers ("Q1", "Question 1", "1." at the start of a line); a one-question
  form takes the whole text.

Every answer is anonymised before it is stored (4.3); original files are not kept.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field

from app.services.course_versions import WorkflowError

from .identity import Person

_ID_COLS = ("student id", "student_id", "studentid", "id", "username", "user name", "university id", "student number")
_NAME_COLS = ("name", "full name", "student name", "student")
_Q_COL = re.compile(r"^(?:q|question|answer|ans)?\s*[#_]?\s*(\d{1,3})$", re.I)
_M_COL = re.compile(r"^(?:m|marks?|points?|score)\s*[#_]?\s*(?:q\s*)?(\d{1,3})$", re.I)
_MARKER = re.compile(r"(?im)^[ \t]*(?:q(?:uestion)?[ \t]*\.?[ \t]*(\d{1,3})|(\d{1,3})[.)])[ \t]*[:.)\-]?[ \t]*")


@dataclass
class Row:
    person: Person
    answers: dict[int, str] = field(default_factory=dict)  # position -> text
    marks: dict[int, float] = field(default_factory=dict)  # calibration only


def _read_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    rd = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [r for r in rd if any((v or "").strip() for v in r.values())]
    return [h.strip() for h in (rd.fieldnames or [])], rows


def _col(headers: list[str], names: tuple[str, ...]) -> str | None:
    low = {h.lower().strip(): h for h in headers}
    return next((low[n] for n in names if n in low), None)


def _person(r: dict[str, str], headers: list[str]) -> Person | None:
    idc = _col(headers, _ID_COLS)
    if idc is None:
        raise WorkflowError("The CSV needs a student ID column (e.g. 'Student ID').", 422)
    sid = (r.get(idc) or "").strip()
    if not sid:
        return None
    name_c = _col(headers, _NAME_COLS)
    first, last = _col(headers, ("first name", "firstname", "given name")), _col(headers, ("last name", "lastname", "surname", "family name"))
    name = (r.get(name_c) or "").strip() if name_c else " ".join(x for x in ((r.get(first) or "").strip() if first else "",
                                                                             (r.get(last) or "").strip() if last else "") if x)
    email_c = _col(headers, ("email", "e-mail", "email address"))
    return Person(external_id=sid, name=name or None, email=((r.get(email_c) or "").strip() or None) if email_c else None)


def parse_roster(data: bytes) -> list[Person]:
    headers, rows = _read_csv(data)
    out = [p for r in rows if (p := _person(r, headers))]
    if not out:
        raise WorkflowError("No students found in the roster file.", 422)
    return out


def parse_answers_csv(data: bytes, n_items: int, with_marks: bool = False) -> list[Row]:
    headers, rows = _read_csv(data)
    qcols = {int(m.group(1)): h for h in headers if (m := _Q_COL.match(h.strip())) and not _col([h], _ID_COLS)}
    mcols = {int(m.group(1)): h for h in headers if (m := _M_COL.match(h.strip()))}
    qcols = {k: v for k, v in qcols.items() if v not in mcols.values()}
    if not qcols:
        raise WorkflowError("No answer columns found: name them Q1, Q2, … as numbered on the form.", 422)
    extra = sorted(k for k in qcols if not 1 <= k <= n_items)
    if extra:
        raise WorkflowError(f"The form has {n_items} questions; the CSV has answers for question(s) {extra}.", 422)
    if with_marks and not mcols:
        raise WorkflowError("A calibration set needs the faculty marks too: columns M1, M2, … next to Q1, Q2, ….", 422)
    out = []
    for r in rows:
        p = _person(r, headers)
        if p is None:
            continue
        row = Row(p, {k: (r.get(h) or "").strip() for k, h in qcols.items()})
        for k, h in mcols.items():
            v = (r.get(h) or "").strip()
            if v:
                try:
                    row.marks[k] = float(v)
                except ValueError as e:
                    raise WorkflowError(f"Mark '{v}' for {p.external_id}, question {k} isn't a number.", 422) from e
        out.append(row)
    if not out:
        raise WorkflowError("No student rows found in the CSV.", 422)
    return out


def split_answers(text: str, n_items: int) -> dict[int, str]:
    """Answer text per question from one student's document."""
    if n_items == 1:
        return {1: text.strip()}
    marks = [(int(m.group(1) or m.group(2)), m.start(), m.end()) for m in _MARKER.finditer(text)]
    marks = [m for m in marks if 1 <= m[0] <= n_items]
    out: dict[int, str] = {}
    for i, (q, _s, e) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out[q] = (out.get(q, "") + "\n" + text[e:end]).strip()
    return out


def files_from_upload(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    if filename.lower().endswith(".zip"):
        from app.upload_guard import RejectedUpload, check_office_zip

        try:
            check_office_zip(data, office=False)
        except RejectedUpload as e:
            raise WorkflowError(str(e), 415) from e
        z = zipfile.ZipFile(io.BytesIO(data))
        return [(n.rsplit("/", 1)[-1], z.read(n)) for n in z.namelist()
                if not n.endswith("/") and not n.rsplit("/", 1)[-1].startswith((".", "__"))]
    return [(filename, data)]


def file_text(filename: str, data: bytes) -> str:
    from app.materials.extract import UnsupportedMaterial, units_from_file

    try:
        return "\n".join(u.text for u in units_from_file(filename, data))
    except UnsupportedMaterial as e:
        raise WorkflowError(f"{filename}: submissions can be PDF, DOCX or TXT.", 415) from e


def id_tokens(filename: str) -> list[str]:
    stem = filename.rsplit(".", 1)[0]
    return [t for t in re.split(r"[\s_\-.()]+", stem) if t]
