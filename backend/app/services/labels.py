"""Plain-English labels and values for the edit log (plan 1.12).

Every faculty edit is stored as a JSON-Pointer op with the old and new values
(D5), which is the right shape for an audit trail and the wrong shape for a
person: ``/weekly/11/assessments/0/weight_pct`` and
``{"name": "Quiz #1", "due_date": null, ...}`` tell a faculty member nothing.

:func:`describe` turns one stored edit into a label ("Week 12 - Quiz #1 -
weight") and two value strings ("5%", "empty"), resolved against the current
record and falling back to the stored value when the item has since been
removed. The edit-log tab and the CSV export both use it, so the words a
faculty member reads on screen are the words in the audit file.
"""

from __future__ import annotations

from datetime import date
from typing import Any

_MAX = 180

OP_WORDS = {"replace": "Changed", "add": "Added", "remove": "Removed", "derive": "Changed (derived)"}

# Leaf field -> what to call it. Used for the last token of a pointer.
FIELD_WORDS = {
    "name": "name",
    "assessment": "name",
    "weight_pct": "weight",
    "due_date": "due date",
    "due_week": "due week",
    "due_text_raw": "due text (as read)",
    "clo_numbers": "CLOs",
    "clo_text_raw": "CLO text (as read)",
    "week_no": "week number",
    "topics": "topics",
    "readings": "readings",
    "number": "number",
    "text": "text",
    "strength": "strength",
    "abet_addressed": "outcomes marked addressed",
    "clo_plo": "CLO to PLO mapping",
    "plos": "programme outcomes",
    "letter": "letter",
    "min_pct": "minimum %",
    "max_pct": "maximum %",
    "points": "grade points",
}

# Whole top-level fields that have their own name in the UI.
TOP_WORDS = {
    "/course/code": "Course code",
    "/course/title": "Course title",
    "/course/credit_hours": "Credit hours",
    "/course/prerequisites": "Prerequisite course(s)",
    "/course/description": "Course description",
    "/course/additional_info": "Additional information",
    "/course/methods_of_instruction": "Method(s) of instruction",
    "/offering/term": "Term (normalised)",
    "/offering/term_raw": "Semester and academic year (as read)",
    "/offering/class_timing_raw": "Class timing(s)",
    "/offering/meetings": "Meeting days",
    "/offering/instructor_name": "Faculty name",
    "/offering/instructor_contact": "Contact and office hours",
    "/resources/textbooks": "Textbooks and materials",
    "/resources/other": "Other resources",
    "/resources/web": "Web resources",
    "/weights": "Weight table",
    "/clo_matrix": "CLO x assessment matrix",
    "/clos": "Course learning outcomes",
    "/weekly": "Weekly plan",
    "/grading_scale": "Grading scale",
    "/programs": "Appendix programmes",
}


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _tokens(path: str) -> list[str]:
    return [_unescape(t) for t in path.lstrip("/").split("/")] if path.strip("/") else []


def _at(doc: Any, tokens: list[str]) -> Any:
    cur = doc
    for t in tokens:
        if isinstance(cur, dict):
            if t not in cur:
                return None
            cur = cur[t]
        elif isinstance(cur, list):
            try:
                i = int(t)
            except ValueError:
                return None
            if not 0 <= i < len(cur):
                return None
            cur = cur[i]
        else:
            return None
    return cur


def _clip(s: str) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= _MAX else s[: _MAX - 1].rstrip() + "…"


def fmt_date(value: Any) -> str:
    if isinstance(value, date):
        return f"{value.day} {value:%b %Y}"
    try:
        d = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value)
    return f"{d.day} {d:%b %Y}"


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):g}%"
    except (TypeError, ValueError):
        return str(value)


def fmt_clos(nums: Any) -> str:
    try:
        xs = sorted(int(n) for n in nums)
    except (TypeError, ValueError):
        return str(nums)
    return "CLO " + ", ".join(str(n) for n in xs) if xs else "none"


def _fmt_days(meetings: Any) -> str:
    names = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
    out = []
    for m in meetings or []:
        days = "/".join(names.get(d, d) for d in (m.get("days") or []))
        out.append(" ".join(x for x in [days, m.get("time_text") or ""] if x).strip() or "unknown")
    return "; ".join(out) or "none"


def _fmt_assessment(v: dict) -> str:
    parts = [str(v.get("name") or "unnamed")]
    if v.get("weight_pct") is not None:
        parts.append(fmt_pct(v["weight_pct"]))
    if v.get("due_date"):
        parts.append(f"due {fmt_date(v['due_date'])}")
    elif v.get("due_week") is not None:
        parts.append(f"due week {v['due_week']}")
    return ", ".join(parts)


def value_text(path: str, value: Any) -> str:
    """One stored value in words. Never JSON."""
    tokens = _tokens(path)
    last = tokens[-1] if tokens else ""
    if value is None or value == "":
        return "empty"
    if isinstance(value, list) and not value:
        return "empty"
    if isinstance(value, bool):
        return "yes" if value else "no"

    if last in {"clo_numbers", "abet_addressed"} and isinstance(value, list):
        return fmt_clos(value) if last == "clo_numbers" else "outcome " + ", ".join(str(n) for n in value)
    if last == "weight_pct":
        return fmt_pct(value)
    if last == "due_date":
        return fmt_date(value)
    if last == "meetings" or (last.isdigit() and len(tokens) > 1 and tokens[-2] == "meetings"):
        return _fmt_days(value if isinstance(value, list) else [value])

    if isinstance(value, dict):
        keys = set(value)
        if {"name", "due_date"} <= keys or {"name", "due_week"} <= keys:
            return _fmt_assessment(value)
        if keys <= {"name", "weight_pct"} and "name" in keys:
            return ", ".join([str(value["name"])] + ([fmt_pct(value["weight_pct"])]
                                                     if value.get("weight_pct") is not None else []))
        if "assessment" in keys:
            return f"{value['assessment']} ({fmt_clos(value.get('clo_numbers') or [])})"
        if keys >= {"number", "text"}:
            return _clip(f"CLO {value['number']}: {value['text']}")
        if "week_no" in keys:
            bits = [f"Week {value['week_no']}"]
            if value.get("topics"):
                bits.append("; ".join(value["topics"]))
            if value.get("assessments"):
                bits.append(", ".join(_fmt_assessment(a) for a in value["assessments"]))
            if value.get("clo_numbers"):
                bits.append(fmt_clos(value["clo_numbers"]))
            return _clip(" - ".join(bits))
        if keys >= {"clo", "plo"}:
            return f"CLO {value['clo']} to PLO {value['plo']} ({value.get('strength', '?')})"
        if keys >= {"letter", "min_pct"}:
            pts = f", {value['points']:g} points" if value.get("points") is not None else ""
            return f"{value['letter']} {value['min_pct']:g}-{value['max_pct']:g}%{pts}"
        if "days" in keys:
            return _fmt_days([value])
        if "name" in keys:
            return _clip(str(value["name"]))
        return _clip("; ".join(f"{k}: {v}" for k, v in value.items()))

    if isinstance(value, list):
        if all(isinstance(x, (int, float)) for x in value):
            return ", ".join(f"{x:g}" if isinstance(x, float) else str(x) for x in value)
        if all(isinstance(x, str) for x in value):
            return _clip("; ".join(value))
        return _clip("; ".join(value_text(f"{path}/0", x) for x in value))

    if isinstance(value, float):
        return f"{value:g}"
    return _clip(str(value))


def _context(rec: dict, tokens: list[str], fallback: Any) -> str | None:
    """Name of the thing the pointer is inside: 'Week 12 - Quiz #1', 'Weight table - Midterm'."""
    if not tokens:
        return None
    head = tokens[0]
    fb = fallback if isinstance(fallback, dict) else {}

    def name_of(obj: Any, key: str) -> str | None:
        if isinstance(obj, dict) and obj.get(key):
            return str(obj[key])
        return str(fb[key]) if fb.get(key) else None

    if head == "weights" and len(tokens) >= 2:
        nm = name_of(_at(rec, tokens[:2]), "name") or f"row {int(tokens[1]) + 1}"
        return f"Weight table - {nm}"
    if head == "clo_matrix" and len(tokens) >= 2:
        nm = name_of(_at(rec, tokens[:2]), "assessment") or f"column {int(tokens[1]) + 1}"
        return f"Matrix - {nm}"
    if head == "clos" and len(tokens) >= 2:
        row = _at(rec, tokens[:2])
        num = (row or {}).get("number") if isinstance(row, dict) else None
        num = num if num is not None else fb.get("number")
        return f"CLO {num}" if num is not None else f"CLO row {int(tokens[1]) + 1}"
    if head == "grading_scale" and len(tokens) >= 2:
        row = _at(rec, tokens[:2])
        letter = (row or {}).get("letter") if isinstance(row, dict) else None
        return f"Grading scale - {letter or f'row {int(tokens[1]) + 1}'}"
    if head == "programs" and len(tokens) >= 2:
        nm = name_of(_at(rec, tokens[:2]), "name") or f"programme {int(tokens[1]) + 1}"
        base = f"Programme {nm}"
        if len(tokens) >= 4 and tokens[2] == "plos":
            plo = _at(rec, tokens[:4])
            n = (plo or {}).get("number") if isinstance(plo, dict) else None
            return f"{base} - PLO {n}" if n is not None else base
        return base
    if head == "weekly" and len(tokens) >= 2:
        week = _at(rec, tokens[:2])
        wk = (week or {}).get("week_no") if isinstance(week, dict) else None
        base = f"Week {wk}" if wk is not None else f"Week row {int(tokens[1]) + 1}"
        if len(tokens) >= 4 and tokens[2] == "assessments":
            item = _at(rec, tokens[:4])
            nm = name_of(item, "name") or "assessment"
            return f"{base} - {nm}"
        return base
    if head == "raw_sections" and len(tokens) >= 2:
        return f"Section text - {tokens[1]}"
    return None


def label_for(rec: dict, path: str, old: Any = None, new: Any = None) -> str:
    """Plain-English name for the field a stored edit changed."""
    if path in TOP_WORDS:
        return TOP_WORDS[path]
    tokens = _tokens(path)
    if not tokens:
        return "Whole record"
    ctx = _context(rec, tokens, new if new is not None else old)
    last = tokens[-1]
    leaf = FIELD_WORDS.get(last)
    if last.isdigit():  # a whole list element: the context already names it
        return ctx or TOP_WORDS.get("/" + "/".join(tokens[:-1]), path)
    if ctx and leaf:
        return f"{ctx} - {leaf}"
    if ctx:
        return f"{ctx} - {last.replace('_', ' ')}"
    if leaf:
        head = TOP_WORDS.get("/" + tokens[0])
        return f"{head} - {leaf}" if head else leaf
    return path


def describe(rec: dict, op: str, path: str, old: Any, new: Any) -> tuple[str, str, str, str]:
    """(operation word, label, old value in words, new value in words)."""
    return (OP_WORDS.get(op, op.capitalize()),
            label_for(rec, path, old, new),
            value_text(path, old),
            value_text(path, new))


__all__ = ["OP_WORDS", "describe", "label_for", "value_text"]
