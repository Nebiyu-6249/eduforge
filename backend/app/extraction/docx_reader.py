"""DOCX -> blocks (python-docx). Reads tables directly; merged cells are
deduplicated by their underlying <w:tc> element (HANDOFF §8.3)."""

from __future__ import annotations

import io

from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph

from .docmodel import Block, Para, Table
from .normalize import clean


def _cell_text(cell) -> str:
    # Keep paragraph breaks inside a cell: they separate list items.
    lines = [p.text for p in cell.paragraphs]
    # Nested tables: flatten their text into the cell.
    for t in cell.tables:
        for row in t.rows:
            lines.append(" | ".join(c.text for c in row.cells))
    return "\n".join(line.replace(" ", " ").rstrip() for line in lines).strip()


def _table_rows(tbl: DocxTable) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in tbl.rows:
        seen: set[int] = set()
        cells: list[str] = []
        for cell in row.cells:
            key = id(cell._tc)
            if key in seen:  # horizontally merged cell repeats
                continue
            seen.add(key)
            cells.append(_cell_text(cell))
        rows.append(cells)
    return rows


def read_docx(data: bytes) -> list[Block]:
    doc = Document(io.BytesIO(data))
    blocks: list[Block] = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = clean(p.text)
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            blocks.append(Para(text=p.text.strip(), is_heading=style.lower().startswith(("heading", "title"))))
        elif tag == "tbl":
            blocks.append(Table(rows=_table_rows(DocxTable(child, doc))))
    return blocks
