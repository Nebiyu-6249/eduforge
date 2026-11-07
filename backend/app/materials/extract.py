"""Materials -> text units -> chunks (plan 2.2).

A unit is the natural piece of a file: a PDF page, a PPTX slide (with its
speaker notes), a DOCX section under one heading, a text paragraph block.
Chunks join consecutive units up to ~500–800 tokens (≈4 characters a token)
and remember where they came from, e.g. "slides 3–5" or "§ Regression".
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

TARGET_CHARS = 2600  # ≈650 tokens
MAX_CHARS = 3200     # ≈800 tokens


@dataclass
class Unit:
    label: str  # "slide 3", "page 2", "§ Linear regression"
    text: str


@dataclass
class ChunkText:
    location: str
    text: str

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.text) // 4)


class UnsupportedMaterial(ValueError):
    pass


def _clean(s: str) -> str:
    s = s.replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def units_from_file(filename: str, data: bytes) -> list[Unit]:
    name = filename.lower()
    if data[:5] == b"%PDF-":
        return _pdf(data)
    if name.endswith(".pptx"):
        return _pptx(data)
    if name.endswith(".docx"):
        return _docx(data)
    if name.endswith((".txt", ".md")):
        return _text(data.decode("utf-8", errors="replace"))
    raise UnsupportedMaterial("Materials can be PDF, PPTX, DOCX, TXT or MD.")


def _pdf(data: bytes) -> list[Unit]:
    import pdfplumber

    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = _clean(page.extract_text(x_tolerance=1.5) or "")
            if text:
                out.append(Unit(f"page {i}", text))
    return out


def _pptx(data: bytes) -> list[Unit]:
    from pptx import Presentation

    out = []
    for i, slide in enumerate(Presentation(io.BytesIO(data)).slides, 1):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text
            if notes.strip():
                parts.append(f"Notes: {notes}")
        text = _clean("\n".join(parts))
        if text:
            out.append(Unit(f"slide {i}", text))
    return out


def _docx(data: bytes) -> list[Unit]:
    from docx import Document

    out: list[Unit] = []
    heading: str = "start"
    buf: list[str] = []
    for p in Document(io.BytesIO(data)).paragraphs:
        style = (p.style.name if p.style is not None else "").lower()
        if style.startswith(("heading", "title")) and p.text.strip():
            if buf:
                out.append(Unit(f"§ {heading}", _clean("\n".join(buf))))
            heading, buf = p.text.strip()[:60], []
        elif p.text.strip():
            buf.append(p.text)
    if buf:
        out.append(Unit(f"§ {heading}", _clean("\n".join(buf))))
    return out


def _text(text: str) -> list[Unit]:
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [Unit(f"part {i}", _clean(b)) for i, b in enumerate(blocks, 1)]


def _split_long(u: Unit) -> list[Unit]:
    if len(u.text) <= MAX_CHARS:
        return [u]
    pieces, cur = [], ""
    for para in re.split(r"(?<=[.!?])\s+|\n", u.text):
        if cur and len(cur) + len(para) > TARGET_CHARS:
            pieces.append(cur)
            cur = ""
        cur = f"{cur} {para}".strip()
    if cur:
        pieces.append(cur)
    return [Unit(f"{u.label} (part {i})", p) for i, p in enumerate(pieces, 1)]


def chunk_units(units: list[Unit]) -> list[ChunkText]:
    """Pack consecutive units into chunks of about TARGET_CHARS."""
    flat = [p for u in units for p in _split_long(u)]
    chunks: list[ChunkText] = []
    group: list[Unit] = []

    def flush():
        if not group:
            return
        first, last = group[0].label, group[-1].label
        loc = first if first == last else _range_label(first, last)
        chunks.append(ChunkText(loc, "\n\n".join(u.text for u in group)))
        group.clear()

    size = 0
    for u in flat:
        if group and size + len(u.text) > TARGET_CHARS:
            flush()
            size = 0
        group.append(u)
        size += len(u.text)
    flush()
    return chunks


def _range_label(first: str, last: str) -> str:
    a, b = first.split(" ", 1), last.split(" ", 1)
    if a[0] == b[0] and len(a) == 2 and len(b) == 2:
        return f"{a[0]}s {a[1]}–{b[1]}"  # "slides 3–5"
    return f"{first} – {last}"
