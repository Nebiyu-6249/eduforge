"""AURAK-template mapper: blocks -> ExtractedSyllabus (HANDOFF §8.1-8.3).

Deterministic. It anchors on the template's section headings, reads the
header key/value fields, and parses the CLO, assessment, weekly and appendix
tables. Anything it cannot place becomes an ``ExtractionNote`` (surfaced to
faculty as an EX flag) rather than being guessed.

The heuristics here were written from the template description in the
handoff, not from the real files. Tune them against fixtures/syllabi/ once
the team supplies the five sample syllabi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .docmodel import Block, Para, Table
from .normalize import (
    clean,
    is_mark,
    label_key,
    normalise_term,
    parse_assessment_cell,
    parse_clo_list,
    parse_float,
    parse_int,
    parse_meetings,
    parse_pct,
    parse_strength,
    split_lines,
    term_year,
)
from .schema import (
    CLOItem,
    CLOPLOLink,
    ExtractedSyllabus,
    ExtractionNote,
    MatrixEntry,
    PLOItem,
    ProgramBlock,
    SourceRef,
    WeekRow,
    WeightEntry,
)

# --------------------------------------------------------------------------- #
# Template vocabulary
# --------------------------------------------------------------------------- #

# (section key, heading prefixes as label_key()) — first match wins.
_SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("description", ("coursedescription",)),
    ("additional_info", ("additionalinformation",)),
    ("textbooks", ("coursetextbooks", "textbooksandmaterials", "textbook", "requiredtextbook")),
    ("other_resources", ("otherresources",)),
    ("web_resources", ("webresources",)),
    ("clos", ("courselearningoutcomes",)),
    ("assessments", ("assessmentactivities", "assessmentmethods", "assessmentandgrading", "courseassessment")),
    ("grading", ("gradingscale", "gradingsystem")),
    ("weekly", ("weeklycourseinformation", "weeklyschedule", "courseschedule", "weeklycourseschedule",
                "tentativeschedule")),
    ("policies", ("policies", "coursepolicies", "attendance", "academicintegrity", "accommodation",
                  "studentswithdisabilities", "honorcode", "classroompolicies", "latesubmission")),
    ("appendix", ("appendix",)),
]

# KV labels -> dotted target path.
_LABELS: list[tuple[str, str]] = [
    ("coursetitle", "course.title"),
    ("coursename", "course.title"),
    ("coursecode", "course.code"),
    ("coursenumber", "course.code"),
    ("credithours", "course.credit_hours"),
    ("credits", "course.credit_hours"),
    ("semesterandacademicyear", "offering.term_raw"),
    ("semester", "offering.term_raw"),
    ("term", "offering.term_raw"),
    ("classtimings", "offering.class_timing_raw"),
    ("classtiming", "offering.class_timing_raw"),
    ("classtimes", "offering.class_timing_raw"),
    ("classtime", "offering.class_timing_raw"),
    ("methodsofinstruction", "course.methods_of_instruction"),
    ("methodofinstruction", "course.methods_of_instruction"),
    ("prerequisitecourses", "course.prerequisites"),
    ("prerequisitecourse", "course.prerequisites"),
    ("prerequisites", "course.prerequisites"),
    ("prerequisite", "course.prerequisites"),
    ("facultyname", "offering.instructor_name"),
    ("instructorname", "offering.instructor_name"),
    ("instructor", "offering.instructor_name"),
    ("contactinformationandofficehours", "offering.instructor_contact"),
    ("contactinformation", "offering.instructor_contact"),
    ("officehours", "offering.instructor_contact"),
    ("coursedescription", "course.description"),
    ("additionalinformationaboutthecourse", "course.additional_info"),
]

# Human-form labels for header paragraphs, which in the AURAK template may
# hold several fields at once: "Course & Instructor Information Course Title:
# Data Science Course Code: CSAI 351". Long labels such as "Prerequisite
# course(s) and/or co-requisite courses, if applicable:" are allowed.
_INLINE_LABELS: list[tuple[str, str]] = [
    (r"Course\s+Title|Course\s+Name", "course.title"),
    (r"Course\s+Code|Course\s+Number", "course.code"),
    (r"Credit\s+Hours?|Credits", "course.credit_hours"),
    (r"Semester\s+and\s+Academic\s+Year|Semester|Term", "offering.term_raw"),
    (r"Class\s+Timing(?:\(s\)|s)?|Class\s+Times?", "offering.class_timing_raw"),
    (r"Method(?:\(s\)|s)?\s+of\s+Instruction", "course.methods_of_instruction"),
    ((r"Pre-?requisite(?:\s+course(?:\(s\)|s)?|s)?(?:\s+and/or\s+co-?requisite(?:\s+course(?:\(s\)|s)?)?)?"
      r"(?:,?\s*if\s+applicable)?"), "course.prerequisites"),
    (r"Faculty\s+Name|Instructor(?:\s+Name)?", "offering.instructor_name"),
    (r"Contact\s+Information(?:\s+and\s+Office\s+Hours)?|Office\s+Hours", "offering.instructor_contact"),
    (r"E-?mail(?:\s+Address)?", "offering.instructor_contact"),
]
_INLINE_RE = re.compile(r"\b(" + "|".join(p for p, _ in _INLINE_LABELS) + r")\s*:", re.I)
# Fields that collect several values instead of keeping the first.
_APPEND_FIELDS = {"offering.instructor_contact"}


def _inline_kvs(text: str) -> list[tuple[str, str]]:
    """All 'Label: value' pairs in one paragraph, in order. [] if the
    paragraph doesn't start (within its first 60 characters) with a label."""
    matches = list(_INLINE_RE.finditer(text))
    if not matches or matches[0].start() > 60:
        return []
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        label = m.group(1)
        target = next(t for p, t in _INLINE_LABELS if re.fullmatch(p, label, re.I))
        out.append((target, text[m.end():end].strip()))
    return out


_FREE_TEXT = {"description", "additional_info", "textbooks", "other_resources", "web_resources"}
_FREE_PTR = {"description": "/course/description", "additional_info": "/course/additional_info",
             "textbooks": "/resources/textbooks", "other_resources": "/resources/other",
             "web_resources": "/resources/web"}


def _strip_numbering(text: str) -> str:
    return re.sub(r"^\s*(?:section\s+)?(?:[ivx]+|\d+|[a-h])[.)]\s+", "", text, flags=re.I)


def match_section(text: str) -> str | None:
    t = clean(text)
    if not t or len(t) > 90:
        return None
    key = label_key(_strip_numbering(t))
    for sec, prefixes in _SECTIONS:
        for p in prefixes:
            if key.startswith(p) and len(key) <= len(p) + 25:
                return sec
    return None


def match_label(text: str) -> str | None:
    key = label_key(text)
    if not key or len(key) > 45:
        return None
    for lab, target in _LABELS:
        if key == lab or (key.startswith(lab) and len(key) - len(lab) <= 6):
            return target
    return None


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #

@dataclass
class _Heading:
    section: str
    text: str


@dataclass
class _KV:
    target: str
    value: str


@dataclass
class _Text:
    text: str


@dataclass
class _Rows:
    rows: list[list[str]]
    notes: list[str] = field(default_factory=list)


def _events(blocks: list[Block]):
    """Yield template events. Each carries its origin (plan 0.6): .page, .table
    (1-based table number, None for paragraphs) and .orig_rows (the table's rows,
    so a value can be traced to its row)."""
    pending_label: str | None = None
    table_no = 0

    def tag(ev):
        ev.page = b.page
        ev.table = table_no if isinstance(b, Table) else None
        ev.orig_rows = b.rows if isinstance(b, Table) else None
        ev.row_pages = b.row_pages if isinstance(b, Table) else None
        return ev

    for b in blocks:
        if isinstance(b, Table):
            table_no += 1
        if isinstance(b, Para):
            t = clean(b.text)
            if pending_label:
                waiting, pending_label = pending_label, None
                if not match_section(t) and not match_label(t.split(":")[0]) and not _inline_kvs(t):
                    yield tag(_KV(waiting, b.text.strip()))
                    continue
            sec = match_section(t)
            if sec and (b.is_heading or len(t) < 70):
                yield tag(_Heading(sec, t))
                continue
            pairs = _inline_kvs(t)
            if pairs:
                for target, val in pairs:
                    if val:
                        yield tag(_KV(target, val))
                # A trailing label with no value takes the next paragraph.
                pending_label = pairs[-1][0] if not pairs[-1][1] else None
                continue
            if ":" in t:
                head, _, val = t.partition(":")
                lab = match_label(head)
                if lab:
                    if clean(val):
                        yield tag(_KV(lab, val.strip()))
                    else:
                        pending_label = lab
                    continue
            lab = match_label(t)
            if lab and len(t) < 50:
                pending_label = lab
                continue
            yield tag(_Text(b.text))
        else:
            buf: list[list[str]] = []
            width = max((len(r) for r in b.rows), default=0)
            for raw in b.rows:
                # No adjacent-duplicate collapsing: '10%', '10%' or 'X', 'X' are real columns.
                # Merged DOCX cells are already deduplicated by the reader.
                cells = [c.strip() for c in raw]
                nonempty = [c for c in cells if clean(c)]
                if not nonempty:
                    continue
                if len(set(nonempty)) == 1:
                    sec = match_section(nonempty[0])
                    if sec:
                        if buf:
                            yield tag(_Rows(buf))
                            buf = []
                        yield tag(_Heading(sec, clean(nonempty[0])))
                        continue
                if width >= 2 and _is_caption(cells):
                    # Merged title row ("Schedule of Course Topics …"): text, not data.
                    if buf:
                        yield tag(_Rows(buf))
                        buf = []
                    yield tag(_Text(nonempty[0]))
                    continue
                kvs = _row_kvs(cells)
                if kvs:
                    if buf:
                        yield tag(_Rows(buf))
                        buf = []
                    yield from (tag(k) for k in kvs)
                    continue
                buf.append(cells)
            if buf:
                yield tag(_Rows(buf, list(b.notes)))


def _unwrap(name: str) -> str:
    """'(Other Activities, e.g., Class Participation)' -> 'Other Activities, e.g., Class Participation'."""
    if name.startswith("(") and name.endswith(")") and name.count("(") == 1:
        return name[1:-1].strip()
    return name


def _is_caption(cells: list[str]) -> bool:
    """A table row that is really a title: one merged cell (DOCX), or text only
    in the first column that isn't a number, CLO or short label (PDF merges
    leave the other cells empty)."""
    nonempty = [i for i, c in enumerate(cells) if clean(c)]
    if len(cells) == 1:
        return True
    if nonempty != [0]:
        return False
    first = clean(cells[0])
    return len(first) > 25 and parse_int(first[:4]) is None and not re.match(r"^\s*clo\b", first, re.I)


def _row_kvs(cells: list[str]) -> list[_KV]:
    """['Course Title', 'X', 'Course Code', 'Y'] -> KV events; [] if not a KV row."""
    if len(cells) > 6 or not cells or not match_label(cells[0]):
        return []
    out: list[_KV] = []
    i = 0
    while i < len(cells):
        lab = match_label(cells[i])
        if lab and i + 1 < len(cells) and not match_label(cells[i + 1]):
            out.append(_KV(lab, cells[i + 1]))
            i += 2
        elif lab and i + 1 >= len(cells):
            i += 1
        else:
            i += 1
    return out


# --------------------------------------------------------------------------- #
# Mapper
# --------------------------------------------------------------------------- #

_CLO_CELL = re.compile(r"^\s*clo\s*#?\s*(\d{1,2})\b", re.I)
_OUTCOME_NUM = re.compile(r"^\s*(?:plo|so|slo|abet|outcome|student\s+outcome|po|o)?\s*[#(]?\s*(\d{1,2})\s*\)?\s*[.:)]?\s*$",
                          re.I)
_OUTCOME_LEAD = re.compile(r"^\s*(?:plo|so|slo|po|outcome)?\s*[#(]?\s*(\d{1,2})\s*\)?\s*[.:)\-–]?\s*", re.I)
_PROGRAM_PATTERNS = [
    re.compile(r"\b(?:B\.?\s?Sc?\.?|Bachelor(?:\s+of\s+Science)?)\s+(?:degree\s+)?(?:in|of)\s+"
               r"([A-Z][A-Za-z&,\-\s]+?)(?=\s*(?:\(|program|PLO|:|–|-\s|$))", re.I),
    re.compile(r"\b(General\s+Education)\b", re.I),
    # 'for the Computer Science program' — case-sensitive Title Case only, so prose
    # like '…Outcomes At the completion of the program' doesn't become a program.
    re.compile(r"\bfor\s+the\s+((?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:and\s+|&\s+|of\s+|in\s+)?(?:[A-Z][a-z]+|[A-Z]{2,}))*)"
               r"\s+[Pp]rogram\b"),
]
_GENERIC_PROGRAM_WORDS = {"the", "this", "program", "learning", "outcomes", "mapping", "of", "clos", "to", "plos"}


# 'Computer Engineering Program Learning Outcomes', 'Mapping Course to Computer
# Science Program Learning Outcomes: (CAC)', 'Mapping Course to Artificial
# Intelligence and Data Science Learning Outcomes:' (seen in CENG 411).
_PROGRAM_BEFORE_PLO = re.compile(
    r"^(?:Mapping\s+(?:of\s+)?(?:the\s+)?Course\s+to\s+(?:the\s+)?)?(.+?)\s+(?:Program\s+)?Learning\s+Outcomes\b", re.I)
_NOT_PROGRAM_WORDS = {"course", "program", "programme", "mapping", "plo", "plos", "clo", "clos", "abet", "the",
                      "standards", "outcomes", "learning"}


def _title_case_name(name: str) -> bool:
    words = name.split()
    if not 1 <= len(words) <= 7:
        return False
    if any(w.lower().strip("():,") in _NOT_PROGRAM_WORDS for w in words):
        return False
    return all(w[0].isupper() or w.lower() in {"and", "&", "of", "in"} for w in words)


def program_name(text: str) -> str | None:
    t = clean(text)
    if len(t) > 160:
        return None
    m = _PROGRAM_BEFORE_PLO.match(t)
    if m and _title_case_name(clean(m.group(1))):
        return clean(m.group(1))
    for pat in _PROGRAM_PATTERNS:
        m = pat.search(t)
        if m:
            name = clean(m.group(1)).strip(" ,-–")
            words = {w.lower() for w in name.split()}
            if name and not words <= _GENERIC_PROGRAM_WORDS:
                return name
    return None


def _clo_no(cell: str) -> int | None:
    m = _CLO_CELL.match(cell or "")
    return int(m.group(1)) if m else None


def _header_outcome_cols(header: list[str]) -> dict[int, int]:
    """Column index -> outcome number for headers like ['CLO', 'PLO 1', 'PLO 2', ...]."""
    cols: dict[int, int] = {}
    for i, c in enumerate(header):
        if i == 0:
            continue
        m = _OUTCOME_NUM.match(clean(c))
        if m:
            cols[i] = int(m.group(1))
    return cols if len(cols) >= 2 else {}


class _Mapper:
    def __init__(self) -> None:
        self.rec = ExtractedSyllabus()
        self.section = "header"
        self.section_title = "Header"
        self.raw: dict[str, list[str]] = {}
        self.free: dict[str, list[str]] = {k: [] for k in _FREE_TEXT}
        self.weekly_tables: list[tuple[list[list[str]], Any]] = []  # (rows, event for sources)
        self.program: ProgramBlock | None = None
        self.weights_seen: dict[str, WeightEntry] = {}
        self.cur: Any = None  # event being processed (for source locations)
        self.clo_src: dict[int, SourceRef] = {}  # CLO number -> source; CLOs are re-sorted at the end

    # -- helpers -----------------------------------------------------------
    def note(self, where: str, msg: str) -> None:
        self.rec.notes.append(ExtractionNote(where=where, message=msg))

    def _raw(self, text: str) -> None:
        self.raw.setdefault(self.section_title, []).append(text)

    def _set(self, target: str, value: str) -> None:
        obj_name, attr = target.split(".")
        obj = getattr(self.rec, obj_name)
        v = value.strip()
        current = getattr(obj, attr)
        if current not in (None, ""):
            if target in _APPEND_FIELDS and v and v not in current:
                setattr(obj, attr, f"{current}; {v}")
            return  # otherwise the first occurrence wins
        if attr == "credit_hours":
            setattr(obj, attr, parse_float(v))
        else:
            setattr(obj, attr, v or None)
        ptr = f"/{obj_name}/{attr}"
        self._src(ptr, raw=v, match=v)
        derived = {"/offering/term_raw": "/offering/term", "/offering/class_timing_raw": "/offering/meetings"}
        if ptr in derived:
            self._src(derived[ptr], raw=v, match=v)

    # -- source locations (plan 0.6) -----------------------------------------
    def _src(self, ptr: str, raw: str | None = None, match: str | None = None,
             overwrite: bool = False) -> SourceRef | None:
        """Record where `ptr` was read from, using the current event's origin.
        `match` (a cell's text) finds the row inside the current table."""
        ev = self.cur
        if ev is None or (ptr in self.rec.sources and not overwrite):
            return self.rec.sources.get(ptr)
        row = None
        orig = getattr(ev, "orig_rows", None)
        if orig and match:
            key = clean(match).lower()
            for i, r in enumerate(orig, 1):
                cells = [clean(c).lower() for c in r]
                if key in cells or any(c.startswith(key) for c in cells if c):
                    row = i
                    break
        page = getattr(ev, "page", None)
        row_pages = getattr(ev, "row_pages", None)
        if row and row_pages and row <= len(row_pages):
            page = row_pages[row - 1]
        ref = SourceRef(page=page, table=getattr(ev, "table", None), row=row,
                        raw_text=(clean(raw)[:300] or None) if raw else None)
        self.rec.sources[ptr] = ref
        return ref

    # -- driver ------------------------------------------------------------
    def run(self, blocks: list[Block]) -> ExtractedSyllabus:
        for ev in _events(blocks):
            self.cur = ev
            if isinstance(ev, _Heading):
                self.section, self.section_title = ev.section, ev.text
                if ev.section == "appendix":
                    self.program = None
                    # The heading itself may name the program.
                    name = program_name(ev.text)
                    if name:
                        self.program = self._get_program(name)
                continue
            if isinstance(ev, _KV):
                self._set(ev.target, ev.value)
                self.raw.setdefault("Header", []).append(ev.value)
                continue
            if isinstance(ev, _Text):
                self._raw(ev.text)
                self.on_text(ev.text)
            elif isinstance(ev, _Rows):
                for r in ev.rows:
                    self._raw(" | ".join(r))
                for n in ev.notes:
                    self.note(self.section_title, n)
                self.on_rows(ev.rows)
        return self.finish()

    # -- text --------------------------------------------------------------
    def on_text(self, text: str) -> None:
        s = self.section
        if s in _FREE_TEXT:
            self.free[s].append(text)
            self._src(_FREE_PTR[s], raw=text)
        elif s == "clos":
            m = re.match(r"^\s*clo\s*#?\s*(\d{1,2})\s*[:.)\-–]?\s*(.+)$", clean(text), re.I)
            if m:
                self._add_clo(int(m.group(1)), m.group(2))
        elif s == "appendix":
            name = program_name(text)
            if name:
                self.program = self._get_program(name)
                return
            low = text.lower()
            if "addressed" in low and re.search(r"\d", text):
                prog = self._prog("Appendix")
                prog.abet_addressed = sorted(set(prog.abet_addressed) | set(parse_clo_list(text.split(":")[-1])))

    # -- tables ------------------------------------------------------------
    def on_rows(self, rows: list[list[str]]) -> None:
        s = self.section
        if s in _FREE_TEXT:
            for r in rows:
                txt = " ".join(c for c in r if clean(c))
                if txt:
                    self._src(_FREE_PTR[s], raw=txt, match=next((c for c in r if clean(c)), None))
                if txt:
                    self.free[s].append(txt)
        elif s == "clos":
            self._clo_table(rows)
        elif s == "assessments":
            self._assessment_table(rows)
        elif s == "weekly":
            self.weekly_tables.append((rows, self.cur))
        elif s == "appendix":
            self._appendix_table(rows)
        elif s == "header":
            # A header-area table that wasn't KV: maybe a CLO table without heading.
            if any(_CLO_CELL.match(r[0] or "") for r in rows if r):
                self._clo_table(rows)

    # CLOs ---------------------------------------------------------------
    def _add_clo(self, n: int, text: str) -> None:
        text = clean(text)
        if not text:
            return
        if any(c.number == n for c in self.rec.clos):
            self.note("Course Learning Outcomes", f"CLO {n} appears twice; kept the first.")
            return
        self.rec.clos.append(CLOItem(number=n, text=text))
        ref = self._src(f"_clo/{n}", raw=f"CLO {n}: {text}", match=f"CLO {n}") or self._src(f"_clo/{n}", match=text)
        if ref:
            self.clo_src[n] = self.rec.sources.pop(f"_clo/{n}")

    def _clo_table(self, rows: list[list[str]]) -> None:
        for r in rows:
            cells = [clean(c) for c in r]
            if not cells:
                continue
            m = _CLO_CELL.match(cells[0]) or re.match(r"^\s*(\d{1,2})\s*[.)]?\s*$", cells[0])
            if m:
                rest = [c for c in cells[1:] if c]
                if rest:
                    self._add_clo(int(m.group(1)), max(rest[:2], key=len))
                continue
            m = re.match(r"^\s*clo\s*#?\s*(\d{1,2})\s*[:.)\-–]\s*(.+)$", cells[0], re.I)
            if m:
                self._add_clo(int(m.group(1)), m.group(2))

    # Assessment weights + CLO matrix -----------------------------------
    def _add_weight(self, name: str, pct: float | None) -> None:
        name = clean(name)
        if not name or re.match(r"^(total|sum)\b", name, re.I):
            return
        self._src(f"/weights/{len(self.rec.weights)}", raw=f"{name} {pct if pct is not None else ''}%", match=name)
        self.rec.weights.append(WeightEntry(name=name, weight_pct=pct))

    def _assessment_table(self, rows: list[list[str]]) -> None:
        rows = [[clean(c) for c in r] for r in rows if any(clean(c) for c in r)]
        if not rows:
            return
        clo_rows = [r for r in rows if _CLO_CELL.match(r[0])]
        pct_rows = [i for i, r in enumerate(rows)
                    if sum(1 for c in r[1:] if parse_pct(c) is not None and "%" in c) >= 2
                    or (label_key(r[0]).startswith(("weight", "percentage", "grade")) and len(r) > 2)]
        header_has_clos = sum(1 for c in rows[0] if _CLO_CELL.match(c)) >= 1

        if pct_rows and not header_has_clos:
            # Horizontal: names in the row above the weights row; CLO rows mark X.
            wi = pct_rows[0]
            weights = rows[wi]
            # AURAK style: each header cell holds both, e.g. "Quizzes 15%".
            named = sum(1 for c in weights[1:] if parse_pct(c) is not None
                        and re.search(r"[A-Za-z]{3,}", re.sub(r"\d+(?:\.\d+)?\s*%", "", c)))
            if named >= 2:
                names = [weights[0]] + [_unwrap(clean(re.sub(r"\(?\s*\d+(?:\.\d+)?\s*%\s*\)?", " ", c)).strip(" -–:"))
                                        for c in weights[1:]]
            elif wi > 0:
                names = rows[wi - 1]
            else:
                names = [f"Assessment {i}" for i in range(len(weights))]
                self.note("Assessment Activities", "Weights found without assessment names; named them 'Assessment n'.")
            cols = []
            for ci in range(1, min(len(names), len(weights))):
                nm = names[ci]
                if not nm or re.match(r"^(total|sum)\b", nm, re.I):
                    continue
                self._add_weight(nm, parse_pct(weights[ci]))
                cols.append((ci, nm))
            if clo_rows:
                self._matrix_from_rows(cols, clo_rows)
            return

        if header_has_clos:
            # Vertical: [Assessment, Weight, CLO 1, CLO 2, ...]
            hdr = rows[0]
            clo_cols = {i: n for i, c in enumerate(hdr) if (n := _clo_no(c)) is not None}
            wcol = next((i for i, c in enumerate(hdr) if label_key(c).startswith(("weight", "percentage", "grade"))), None)
            for r in rows[1:]:
                if not r or not r[0] or re.match(r"^(total|sum)\b", r[0], re.I):
                    continue
                pct = parse_pct(r[wcol]) if wcol is not None and wcol < len(r) else None
                if wcol is not None or pct is not None:
                    self._add_weight(r[0], pct)
                clos = sorted({n for i, n in clo_cols.items() if i < len(r) and is_mark(r[i])})
                self._src(f"/clo_matrix/{len(self.rec.clo_matrix)}", raw=" | ".join(r), match=r[0])
                self.rec.clo_matrix.append(MatrixEntry(assessment=r[0], clo_numbers=clos))
            return

        if clo_rows and len(rows[0]) > 2:
            # Matrix only (weights in a separate table): header = assessment names.
            cols = [(ci, n) for ci, n in enumerate(rows[0]) if ci > 0 and n and not re.match(r"^(total|sum)\b", n, re.I)]
            self._matrix_from_rows(cols, clo_rows)
            return

        # Vertical weights only: [name, weight%]
        found = False
        for r in rows:
            if len(r) >= 2 and parse_pct(r[-1]) is not None and "%" in " ".join(r[1:]):
                pct_cell = next(c for c in r[1:] if parse_pct(c) is not None)
                self._add_weight(r[0], parse_pct(pct_cell))
                found = True
        if not found:
            self.note("Assessment Activities", "A table in this section could not be read as weights or a CLO matrix.")

    def _matrix_from_rows(self, cols: list[tuple[int, str]], clo_rows: list[list[str]]) -> None:
        for ci, nm in cols:
            clos = sorted({n for r in clo_rows if ci < len(r) and is_mark(r[ci]) and (n := _clo_no(r[0])) is not None})
            self._src(f"/clo_matrix/{len(self.rec.clo_matrix)}", raw=nm, match=nm)
            self.rec.clo_matrix.append(MatrixEntry(assessment=nm, clo_numbers=clos))

    # Appendix ------------------------------------------------------------
    def _get_program(self, name: str) -> ProgramBlock:
        key = label_key(name)
        for p in self.rec.programs:
            if label_key(p.name) == key:
                return p
        p = ProgramBlock(name=name)
        self._src(f"/programs/{len(self.rec.programs)}", raw=name, match=name)
        self.rec.programs.append(p)
        return p

    def _pptr(self, prog: ProgramBlock) -> str:
        return f"/programs/{self.rec.programs.index(prog)}"

    def _prog(self, where: str) -> ProgramBlock:
        if self.program is None:
            self.program = self._get_program(f"Program {len(self.rec.programs) + 1}")
            self.note(where or "Appendix", f"Appendix table found before any program name; filed under '{self.program.name}'.")
        return self.program

    def _appendix_table(self, rows: list[list[str]]) -> None:
        rows = [[clean(c) for c in r] for r in rows if any(clean(c) for c in r)]
        if not rows:
            return
        # A program title may sit in the first row of the table.
        if len([c for c in rows[0] if c]) == 1:
            name = program_name(rows[0][0] or next(c for c in rows[0] if c))
            if name:
                self.program = self._get_program(name)
                rows = rows[1:]
                if not rows:
                    return
        cols = _header_outcome_cols(rows[0])
        has_clo_rows = any(_CLO_CELL.match(r[0]) for r in rows)
        if cols and has_clo_rows:
            self._mapping_table(rows, cols)
        elif cols:
            prog = self._prog("Appendix")
            addr = set(prog.abet_addressed)
            for r in rows[1:]:
                for ci, n in cols.items():
                    if ci < len(r) and (is_mark(r[ci]) or parse_int(r[ci]) == n):
                        addr.add(n)
            prog.abet_addressed = sorted(addr)
            if addr:
                self._src(f"{self._pptr(prog)}/abet_addressed", raw=f"addressed: {sorted(addr)}")
        else:
            self._plo_list_table(rows)

    def _mapping_table(self, rows: list[list[str]], cols: dict[int, int]) -> None:
        prog = self._prog("CLO-PLO mapping")
        addr = set(prog.abet_addressed)
        odd_rows = 0
        vertical_abet = False  # inside a fused '[n] | outcome text | X' addressed table
        for r in rows[1:]:
            if vertical_abet:
                lead = _OUTCOME_LEAD.match(r[0] or "")
                if lead and lead.group(1):
                    if any(is_mark(c) for c in r[1:]):
                        addr.add(int(lead.group(1)))
                    continue
                if any(re.search(r"addressed", c, re.I) for c in r):
                    continue  # header repeated after a page break
                vertical_abet = False
            if not _CLO_CELL.match(r[0]) and any(re.search(r"addressed\s+in", c, re.I) for c in r[1:]):
                # CENG 411 style: the 'Addressed in Course' table is glued under the mapping.
                vertical_abet = True
                odd_rows += 1
                continue
            m = _CLO_CELL.match(r[0])
            if m:
                clo = int(m.group(1))
                for ci, plo in cols.items():
                    st = parse_strength(r[ci]) if ci < len(r) else None
                    if st:
                        self._src(f"{self._pptr(prog)}/clo_plo", raw=" | ".join(r), match=r[0])
                        prog.clo_plo.append(CLOPLOLink(clo=clo, plo=plo, strength=st))
                continue
            new_cols = _header_outcome_cols(r)
            if new_cols:
                cols = new_cols  # a second header row inside a fused table
                odd_rows += 1
                continue
            marks = {plo for ci, plo in cols.items() if ci < len(r) and (is_mark(r[ci]) or parse_int(r[ci]) == plo)}
            if marks and re.search(r"address|abet|outcome|course|covered", r[0], re.I):
                addr |= marks
                odd_rows += 1
                continue
            if any(r):
                odd_rows += 1
                self.note(f"Appendix ({prog.name})", f"Unrecognised row in CLO-PLO mapping table: {' | '.join(r)[:120]}")
        prog.abet_addressed = sorted(addr)
        if addr:
            self._src(f"{self._pptr(prog)}/abet_addressed", raw=f"addressed: {sorted(addr)}")
        if odd_rows:
            self.note(f"Appendix ({prog.name})",
                      "CLO-PLO mapping table also contains other rows (e.g. an ABET 'addressed' table fused into it). "
                      "Check the mapping and the addressed outcomes for this program.")

    def _plo_list_table(self, rows: list[list[str]]) -> None:
        is_addressed_table = any(re.search(r"addressed", c, re.I) for c in rows[0])
        prog = self._prog("PLO list")
        if is_addressed_table:
            # The 'addressed in course' table doesn't always follow its own program
            # (CENG 401 puts CE's after CS's mapping): file it by PLO wording.
            prog = self._program_by_wording(rows) or prog
        addr = set(prog.abet_addressed)
        for r in rows:
            if not r[0]:
                continue
            if re.search(r"addressed", r[0], re.I) and len(r) > 1:
                addr |= set(parse_clo_list(" ".join(r[1:])))
                continue
            m = _OUTCOME_LEAD.match(r[0])
            if not m:
                continue
            n = int(m.group(1))
            lead_rest = clean(r[0][m.end():])
            texts = [c for c in [lead_rest, *r[1:]] if len(c) > 15]
            # An addressed table repeats the outcomes; it only fills a PLO list that is missing.
            if texts and not any(p.number == n for p in prog.plos) and not (is_addressed_table and prog.plos):
                # The text cell often repeats the number: 'PLO 1. Analyze …', '1. An ability …'
                text = re.sub(r"^\s*(?:(?:PLO|SO|PO)\s*#?\s*)?\d{1,2}\s*[.:)\-–]\s*", "", max(texts, key=len),
                              flags=re.I)
                self._src(f"{self._pptr(prog)}/plos/{len(prog.plos)}", raw=text, match=r[0])
                prog.plos.append(PLOItem(number=n, text=text))
            # A mark is 'X' (or ✓), or the outcome's own number (CENG 401's CS table).
            if any(is_mark(c) or (len(clean(c)) <= 3 and parse_int(c) == n) for c in r[1:]):
                addr.add(n)
        prog.abet_addressed = sorted(addr)
        if addr:
            self._src(f"{self._pptr(prog)}/abet_addressed", raw=f"addressed: {sorted(addr)}")

    def _program_by_wording(self, rows: list[list[str]]) -> ProgramBlock | None:
        def toks(s: str) -> set[str]:
            return {w[:6] for w in re.findall(r"[a-z]{4,}", s.lower())}

        texts: dict[int, set[str]] = {}
        for r in rows:
            m = _OUTCOME_LEAD.match(r[0] or "")
            if m:
                long = [c for c in r[1:] if len(c) > 15]
                if long:
                    texts[int(m.group(1))] = toks(max(long, key=len))
        best, best_score = None, 0.0
        for p in self.rec.programs:
            scores = []
            for plo in p.plos:
                if texts.get(plo.number):
                    a, b = texts[plo.number], toks(plo.text)
                    scores.append(len(a & b) / max(1, min(len(a), len(b))))
            if scores:
                score = sum(scores) / len(scores) * min(1.0, len(scores) / max(1, len(texts)))
                if score > best_score:
                    best, best_score = p, score
        return best if best_score >= 0.6 else None

    # Weekly --------------------------------------------------------------
    def _weekly(self) -> None:
        year = term_year(self.rec.offering.term)
        colmap: dict[str, int] | None = None
        last: WeekRow | None = None
        last_assess_raw = ""
        for rows, ev in self.weekly_tables:
            self.cur = ev
            for r in rows:
                cells = [c.strip() for c in r]
                low = [label_key(c) for c in cells]
                if any(k.startswith("week") for k in low) and sum(1 for k in low if k) >= 3 and not parse_int(cells[0]):
                    colmap = self._weekly_header(low)
                    continue
                cm = colmap or self._default_weekly_cols(len(cells))

                def cell(name: str) -> str:
                    i = cm.get(name)
                    return cells[i] if i is not None and i < len(cells) else ""

                wk_txt = clean(cell("week"))
                wk = parse_int(wk_txt)
                if wk is None and not wk_txt and last is not None:
                    # Continuation row (table broken across pages): merge into previous week.
                    last.topics += split_lines(cell("topic"))
                    last.readings += split_lines(cell("readings"))
                    if clean(cell("assessment")):
                        # Re-parse the joined cell so '– 25%' on the next row stays with 'Project Due'.
                        last_assess_raw = last_assess_raw + "\n" + cell("assessment")
                        last.assessments = parse_assessment_cell(last_assess_raw, year)
                    extra = parse_clo_list(cell("clo"))
                    last.clo_numbers = sorted(set(last.clo_numbers) | set(extra))
                    continue
                if wk is None:
                    if not wk_txt:
                        continue
                    wk = (last.week_no + 1) if last else 1
                    self.note("Weekly Course Information", f"Week cell '{wk_txt}' has no number; treated as week {wk}.")
                row = WeekRow(
                    week_no=wk,
                    topics=split_lines(cell("topic")),
                    readings=split_lines(cell("readings")),
                    assessments=parse_assessment_cell(cell("assessment"), year),
                    clo_numbers=parse_clo_list(cell("clo")),
                    clo_text_raw=clean(cell("clo")) or None,
                )
                self._src(f"/weekly/{len(self.rec.weekly)}", raw=" | ".join(c for c in cells if c), match=wk_txt)
                self.rec.weekly.append(row)
                last = row
                last_assess_raw = cell("assessment")

    @staticmethod
    def _weekly_header(low: list[str]) -> dict[str, int]:
        cm: dict[str, int] = {}
        for i, k in enumerate(low):
            if not k:
                continue
            if "clo" in k or k.startswith("mapping"):
                cm.setdefault("clo", i)
            elif k.startswith("week"):
                cm.setdefault("week", i)
            elif "topic" in k or "content" in k:
                cm.setdefault("topic", i)
            elif "reading" in k or "chapter" in k:
                cm.setdefault("readings", i)
            elif "assess" in k or "assignment" in k or "due" in k:
                cm.setdefault("assessment", i)
        return cm

    @staticmethod
    def _default_weekly_cols(n: int) -> dict[str, int]:
        order = ["week", "topic", "readings", "assessment", "clo"]
        return {name: i for i, name in enumerate(order[:n])}

    # Finish ----------------------------------------------------------------
    def finish(self) -> ExtractedSyllabus:
        r = self.rec
        r.offering.term = normalise_term(r.offering.term_raw)
        r.offering.meetings = parse_meetings(r.offering.class_timing_raw)
        if r.course.code:
            r.course.code = re.sub(r"\s+", " ", re.sub(r"([A-Za-z])\s*(\d)", r"\1 \2", r.course.code.strip())).upper()
        if not r.course.description and self.free["description"]:
            r.course.description = "\n".join(_join_prose(self.free["description"]))
        if not r.course.additional_info and self.free["additional_info"]:
            r.course.additional_info = "\n".join(_join_prose(self.free["additional_info"]))
        r.resources.textbooks = _join_prose(self.free["textbooks"])
        r.resources.other = _join_prose(self.free["other_resources"])
        r.resources.web = _join_prose(self.free["web_resources"])
        self._weekly()
        r.clos.sort(key=lambda c: c.number)
        for i, c in enumerate(r.clos):
            if c.number in self.clo_src:
                r.sources[f"/clos/{i}"] = self.clo_src[c.number]
        r.raw_sections = {k: "\n".join(v) for k, v in self.raw.items()}
        if not r.weekly and self.weekly_tables:
            self.note("Weekly Course Information", "Weekly table found but no week rows could be read.")
        return r


_ENDS_ITEM = re.compile(r"[.!?:;)\]]$|^https?://\S+$")
_STARTS_ITEM = re.compile(r"^(?:https?://|[-•*]\s)")


def _join_prose(lines: list[str]) -> list[str]:
    """Rejoin text that a PDF broke into visual lines.

    DOCX paragraphs arrive whole and usually end in sentence punctuation, so
    they stay separate. A PDF line that doesn't end a sentence (or isn't a
    bare URL) is continued by the next line.
    """
    out: list[str] = []
    for raw in lines:
        t = clean(raw)
        if not t:
            continue
        if out and not _ENDS_ITEM.search(out[-1]) and not _STARTS_ITEM.match(t):
            prev = out[-1]
            out[-1] = prev[:-1] + t if prev.endswith("-") and not prev.endswith(" -") else prev + " " + t
        else:
            out.append(t)
    return out


def map_blocks(blocks: list[Block]) -> ExtractedSyllabus:
    return _Mapper().run(blocks)
