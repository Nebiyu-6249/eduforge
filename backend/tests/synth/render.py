"""Render synthetic syllabus specs as DOCX (python-docx) or PDF (reportlab)."""

from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_BREAK


def to_docx(items: list) -> bytes:
    doc = Document()
    for it in items:
        kind = it[0]
        if kind == "title":
            doc.add_heading(it[1], level=0)
        elif kind == "heading":
            doc.add_heading(it[1], level=1)
        elif kind == "para":
            doc.add_paragraph(it[1])
        elif kind == "pagebreak":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        elif kind == "table":
            rows = it[1]
            ncols = max(len(r) for r in rows)
            t = doc.add_table(rows=len(rows), cols=ncols)
            t.style = "Table Grid"
            for ri, r in enumerate(rows):
                for ci in range(ncols):
                    text = r[ci] if ci < len(r) else ""
                    cell = t.cell(ri, ci)
                    lines = text.split("\n")
                    cell.paragraphs[0].text = lines[0]
                    for extra in lines[1:]:
                        cell.add_paragraph(extra)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def to_pdf(items: list) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"].clone("cell", fontSize=8, leading=10)
    story = []
    page_w = landscape(A4)[0] - 3 * cm

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

    for it in items:
        kind = it[0]
        if kind == "title":
            story.append(Paragraph(esc(it[1]), styles["Title"]))
        elif kind == "heading":
            story.append(Paragraph(esc(it[1]), styles["Heading2"]))
        elif kind == "para":
            story.append(Paragraph(esc(it[1]), styles["BodyText"]))
        elif kind == "pagebreak":
            story.append(PageBreak())
        elif kind == "table":
            rows = it[1]
            ncols = max(len(r) for r in rows)
            data = [[Paragraph(esc(r[c] if c < len(r) else ""), cell_style) for c in range(ncols)] for r in rows]
            if ncols == 2:
                widths = [page_w * 0.25, page_w * 0.75]
            elif ncols == 5 and rows and rows[0] and rows[0][0] in ("Week", "1", "14"):
                widths = [page_w * w for w in (0.06, 0.34, 0.14, 0.31, 0.15)]
            else:
                widths = [page_w / ncols] * ncols
            t = Table(data, colWidths=widths, repeatRows=0)
            grid = (it[2] if len(it) > 2 else {}).get("grid", True)
            style = [("VALIGN", (0, 0), (-1, -1), "TOP")]
            if grid:  # gridless tables have no ruling lines, so pdfplumber can't find them
                style.append(("GRID", (0, 0), (-1, -1), 0.5, colors.black))
            t.setStyle(TableStyle(style))
            story.append(t)
            story.append(Spacer(1, 6))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm).build(story)
    return buf.getvalue()
