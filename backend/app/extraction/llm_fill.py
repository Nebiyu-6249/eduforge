"""LLM fallback for sections the deterministic parser couldn't read (HANDOFF §8.3).

Runs only when a core section is still EMPTY after the deterministic pass:

* CLOs, the weight table + CLO matrix, the weekly plan, the appendix programs.

The model gets that section's text as read from the file and, for PDFs, images
of the pages where the section's heading appears (the vision fallback for
tables without ruling lines, whose structure the text alone loses). Its answer
must fit a fixed JSON schema; weekly assessment and CLO cells go through the
same normalisers as the deterministic path.

Every section filled this way gets an ExtractionNote, which the validator
turns into an EX flag: faculty must check it before locking. Nothing the
model writes is trusted silently, and it is told never to invent values.
"""

from __future__ import annotations

import io
import re
from typing import Any

from pydantic import BaseModel, Field

from app.llm.gateway import LLMError, LLMGateway, Prompt

from .mapper import match_section
from .normalize import clean, parse_assessment_cell, parse_clo_list, term_year
from .schema import CLOItem, ExtractedSyllabus, ExtractionNote, MatrixEntry, ProgramBlock, WeekRow, WeightEntry

_SYSTEM = (
    "You transcribe one section of a university course syllabus into JSON. Copy text exactly as it appears in the "
    "document. Never invent, infer, complete or correct anything: if a value is absent or unreadable, leave it "
    "empty. Keep numbers exactly as written. When page images are attached, use them to read the table layout "
    "(which cell belongs to which row and column); the text is the same document without its layout. "
    "Reply with JSON only."
)

_SECTION_TEXT = "SECTION TEXT (layout may be lost):\n<<<\n{text}\n>>>\n\n"


def _prompt(section: str, version: str, task: str) -> Prompt:
    return Prompt(id=f"extract.{section}", version=version, system=_SYSTEM, user=_SECTION_TEXT + task)


PROMPTS = {
    "clos": _prompt("clos", "1", "Extract the Course Learning Outcomes: their number (CLO 1 -> 1) and full text."),
    "assessments": _prompt("assessments", "1", (
        "This is the 'Assessment Activities' section. Extract:\n"
        "- weights: every assessment (or assessment category) in the grading-weight table with its percentage "
        "(number only, e.g. 15 for '15%'); skip any 'Total' column;\n"
        "- clo_matrix: for each of those assessments, the CLO numbers marked (X) against it in the CLO matrix. "
        "Use the assessment names exactly as in the weights.")),
    "weekly": _prompt("weekly", "1", (
        "This is the weekly schedule table. Return one entry per week with: week_no; topics (one string per "
        "topic); readings (one string per reading); assessment_text (the assessment/assignment cell copied "
        "verbatim, including weights and due dates, '' if empty); clo_text (the CLO-mapping cell copied verbatim, "
        "'' if empty). If a week's row continues onto a following row without a week number, merge it into that "
        "week.")),
    "programs": _prompt("programs", "1", (
        "This is the APPENDIX. For each program it covers, extract: name (e.g. 'Computer Science'); plos (number "
        "and text); clo_plo (each CLO-to-PLO cell that has a value: clo number, plo number, strength high/medium/"
        "low from H/M/L or the words); abet_addressed (outcome numbers marked as addressed in the course).")),
}


class _CLOs(BaseModel):
    clos: list[CLOItem] = Field(default_factory=list)


class _Assessments(BaseModel):
    weights: list[WeightEntry] = Field(default_factory=list)
    clo_matrix: list[MatrixEntry] = Field(default_factory=list)


class _Week(BaseModel):
    week_no: int
    topics: list[str] = Field(default_factory=list)
    readings: list[str] = Field(default_factory=list)
    assessment_text: str = ""
    clo_text: str = ""


class _Weekly(BaseModel):
    weeks: list[_Week] = Field(default_factory=list)


class _Programs(BaseModel):
    programs: list[ProgramBlock] = Field(default_factory=list)


_SCHEMAS: dict[str, type[BaseModel]] = {"clos": _CLOs, "assessments": _Assessments, "weekly": _Weekly, "programs": _Programs}
_LABELS = {"clos": "Course Learning Outcomes", "assessments": "Assessment Activities",
           "weekly": "Weekly Course Information", "programs": "Appendix (PLOs and mapping)"}
# Page-text anchors for finding a section's pages in a PDF.
_ANCHORS = {
    "clos": r"course\s+learning\s+outcomes",
    "assessments": r"assessment\s+activities",
    "weekly": r"weekly\s+(?:course\s+information|schedule)|course\s+schedule",
    "programs": r"\bappendix\b|program\s+learning\s+outcomes",
}
_MAX_PAGES = 3
_MIN_TEXT = 40  # characters; less than this and there's nothing to transcribe from


def missing_sections(rec: ExtractedSyllabus) -> list[str]:
    out = []
    if not rec.clos:
        out.append("clos")
    if not rec.weights:
        out.append("assessments")
    if not rec.weekly:
        out.append("weekly")
    if not rec.programs or not any(p.plos or p.clo_plo for p in rec.programs):
        out.append("programs")
    return out


def _section_text(rec: ExtractedSyllabus, section: str) -> str:
    key = "appendix" if section == "programs" else section
    parts = [text for heading, text in rec.raw_sections.items() if match_section(heading) == key]
    return "\n".join(parts).strip()


def _page_images(pdf_bytes: bytes, section: str) -> list[bytes]:
    """PNG renders of the page where the section heading appears and the next
    page(s), up to _MAX_PAGES. Empty if the heading isn't found."""
    import pdfplumber

    anchor = re.compile(_ANCHORS[section], re.I)
    out: list[bytes] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        start = None
        for i, page in enumerate(pdf.pages):
            text = page.extract_text(x_tolerance=1.5) or ""
            if anchor.search(text):
                start = i
                break
        if start is None:
            return []
        last = len(pdf.pages) if section == "programs" else start + _MAX_PAGES
        for page in pdf.pages[start:min(last, start + _MAX_PAGES)]:
            buf = io.BytesIO()
            page.to_image(resolution=110).original.save(buf, format="PNG")
            out.append(buf.getvalue())
    return out


def _apply(rec: ExtractedSyllabus, section: str, data: Any) -> bool:
    """Write the model's answer into the record. Returns False if it was empty."""
    if section == "clos":
        seen: set[int] = set()
        rec.clos = []
        for c in data.clos:
            if clean(c.text) and c.number not in seen:
                seen.add(c.number)
                rec.clos.append(c)
        rec.clos.sort(key=lambda c: c.number)
        return bool(rec.clos)
    if section == "assessments":
        rec.weights = [w for w in data.weights if clean(w.name) and not re.match(r"^total\b", w.name, re.I)]
        rec.clo_matrix = [m for m in data.clo_matrix if clean(m.assessment)]
        return bool(rec.weights)
    if section == "weekly":
        year = term_year(rec.offering.term)
        rec.weekly = [
            WeekRow(week_no=w.week_no, topics=[clean(t) for t in w.topics if clean(t)],
                    readings=[clean(r) for r in w.readings if clean(r)],
                    assessments=parse_assessment_cell(w.assessment_text, year),
                    clo_numbers=parse_clo_list(w.clo_text), clo_text_raw=clean(w.clo_text) or None)
            for w in sorted(data.weeks, key=lambda w: w.week_no)]
        return bool(rec.weekly)
    if section == "programs":
        rec.programs = [p for p in data.programs if clean(p.name)]
        return bool(rec.programs)
    return False


def fill_missing(rec: ExtractedSyllabus, kind: str, data: bytes, llm: LLMGateway | None) -> ExtractedSyllabus:
    """Ask the model to fill empty core sections. Never overwrites parsed data."""
    if llm is None or not llm.available:
        return rec
    for section in missing_sections(rec):
        text = _section_text(rec, section)
        images = _page_images(data, section) if kind == "pdf" else []
        if len(text) < _MIN_TEXT and not images:
            continue  # nothing in the file to transcribe from; V12 will flag the gap
        prompt = PROMPTS[section]
        try:
            try:
                out = llm.json(prompt, _SCHEMAS[section], images=images or None, text=text or "(no text found)")
            except LLMError as e:
                # Rate limits / overload aren't about the images: don't spend another call.
                if not images or any(code in str(e) for code in ("429", "500", "502", "503", "504")):
                    raise
                # The model may not accept images: retry with the text alone.
                images = []
                out = llm.json(prompt, _SCHEMAS[section], text=text)
        except LLMError as e:
            rec.notes.append(ExtractionNote(
                where=_LABELS[section],
                message=f"Couldn't read this section, and the model fallback failed ({str(e)[:120]}). "
                        "Enter it by hand or re-upload later."))
            continue
        if _apply(rec, section, out):
            how = f"its text and {len(images)} page image(s)" if images else "its text"
            rec.notes.append(ExtractionNote(
                where=_LABELS[section],
                message=f"The parser couldn't read this section's table, so the model ({prompt.id}@{prompt.version}) "
                        f"transcribed it from {how}. Check every value against the file before accepting."))
    return rec
