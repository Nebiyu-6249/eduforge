"""PDF -> blocks (pdfplumber). Layout text first, tables by ruling lines.

Text outside detected tables becomes paragraphs; everything is emitted in
reading order (page, then top). Tables split across pages arrive as several
Table blocks; the template mapper stitches them (continuation rows, repeated
header rows).

When a section's table structure is ambiguous the vision fallback (page image
+ vision model through the LLM gateway) is the next step; see
``app.extraction.pipeline``.
"""

from __future__ import annotations

import io
import re

import pdfplumber

from .docmodel import Block, Para, Table
from .normalize import clean

# Word gap threshold in points. Some AURAK PDFs (e.g. CENG 401) contain no
# space characters: letters sit ~0.03 pt apart, words ~2.1-3.7 pt. pdfplumber's
# default of 3 pt glues words together ("NetworkServers&Architecture").
_X_TOL = 1.5

_TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines", "snap_tolerance": 4}


def _inside(word, bbox) -> bool:
    x0, top, x1, bottom = bbox
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _lines_from_words(words, y_tol: float = 3.0) -> list[tuple[float, str]]:
    lines: list[tuple[float, list]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0] - w["top"]) <= y_tol:
            lines[-1][1].append(w)
        else:
            lines.append((w["top"], [w]))
    return [(top, " ".join(x["text"] for x in sorted(ws, key=lambda x: x["x0"]))) for top, ws in lines]


_ITEM_START = re.compile(
    # Only words that START assessment names. 'exam', 'presentation', 'report'
    # also occur mid-name when a cell wraps ('Midterm / Exam –25%', CSCI 372).
    r"^(?:[-•▪●◦·*]|\d+[.)]\s|(?:quiz|hw|homework|assignment|midterm|mid-term|final|lab|project|"
    r"ch\.|chapter|clo)\b"
    # any 'Name (N%)' line, e.g. 'AWS Lab 1 (5%) Due: 2-Oct'
    r"|[A-Za-z][\w#&/.\- ]{0,40}\(\s*\d+(?:\.\d+)?\s*%\s*\))", re.I)


def join_wrapped(cell: str) -> str:
    """Undo soft line wraps inside a PDF table cell.

    A PDF can't tell a wrapped line from a real break, so a new line starts
    a new item only when it begins with a bullet or an item keyword (an
    assessment name, 'Ch.', 'CLO'), or the previous line ended an item
    (';', '.', ')' or '%'). Otherwise it is joined to the previous line.
    """
    lines = [ln.strip() for ln in cell.split("\n") if ln.strip()]
    if len(lines) <= 1:
        return cell.strip()
    out = [lines[0]]
    for ln in lines[1:]:
        prev = out[-1]
        if prev.count("(") > prev.count(")"):
            out[-1] = prev + " " + ln  # still inside '(report and / presentation)'
        elif _ITEM_START.match(ln) or prev.endswith((";", ".", ")", "%")):
            out.append(ln)
        elif prev.endswith("-") and not prev.endswith(" -"):
            out[-1] = prev + ln  # hyphenated wrap: 'client-' + 'server'
        else:
            out[-1] = prev + " " + ln
    return "\n".join(out)


def read_pdf(data: bytes) -> list[Block]:
    blocks: list[Block] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables(_TABLE_SETTINGS)
            items: list[tuple[float, Block]] = []
            bboxes = [t.bbox for t in tables]
            for t in tables:
                rows = []
                for r in t.extract(x_tolerance=_X_TOL):
                    cells = [join_wrapped(c or "") for c in r]
                    # pdfplumber returns None for cells spanned by a merge.
                    if any(cells):
                        rows.append(cells)
                if rows:
                    items.append((t.bbox[1], Table(rows=rows, page=pno, row_pages=[pno] * len(rows))))
            words = [w for w in page.extract_words(x_tolerance=_X_TOL, keep_blank_chars=False, use_text_flow=False)
                     if not any(_inside(w, b) for b in bboxes)]
            for top, text in _lines_from_words(words):
                if clean(text):
                    items.append((top, Para(text=text, page=pno)))
            items.sort(key=lambda it: it[0])
            blocks.extend(b for _, b in items)
    return _stitch_page_split_tables(_merge_paragraph_lines(blocks))


def _stitch_page_split_tables(blocks: list[Block]) -> list[Block]:
    """Join a table that continues at the top of the next page.

    Two Table blocks are one table when nothing but page furniture sits
    between them, the second starts on a later page, and both have the same
    number of columns. A header row repeated on the new page is dropped.
    """
    out: list[Block] = []
    for b in blocks:
        prev = out[-1] if out else None
        prev_end = prev.row_pages[-1] if isinstance(prev, Table) and prev.row_pages else getattr(prev, "page", None)
        if (isinstance(b, Table) and isinstance(prev, Table) and b.page and prev_end and b.page > prev_end
                and b.rows and prev.rows and len(b.rows[0]) == len(prev.rows[0])):
            rows = b.rows[1:] if [clean(c) for c in b.rows[0]] == [clean(c) for c in prev.rows[0]] else b.rows
            prev.rows.extend(rows)
            # Track each row's page. The stitched table now ends on this page, so a
            # second table further down the same page is a new table, not a continuation.
            prev.row_pages = (prev.row_pages or [prev.page or b.page] * (len(prev.rows) - len(rows))) + [b.page] * len(rows)
            continue
        out.append(b)
    return out


_PAGE_NO = re.compile(r"^(?:page\s*:?\s*\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*(?:of|/)\s*\d+)$", re.I)


def _merge_paragraph_lines(blocks: list[Block]) -> list[Block]:
    """PDF text arrives line by line; leave lines separate (the mapper joins
    free-text sections) but drop page furniture like bare page numbers."""
    out: list[Block] = []
    for b in blocks:
        if isinstance(b, Para) and _PAGE_NO.match(clean(b.text)):
            continue  # 'Page 3', 'Page: 12 of 13', '3 / 13
        if isinstance(b, Para) and clean(b.text).isdigit():
            continue
        out.append(b)
    return out
