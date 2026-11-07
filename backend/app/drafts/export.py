"""Export APPROVED items only, as DOCX or PDF (D9: files, no Blackboard).

Two documents, never one: a **question paper** a student can be handed, and a
separate **answer key** for the faculty member. Nothing that belongs to the
instructor (correct options, rationales, CLO/week/Bloom tags, who approved the
item) appears on the paper, so there is no checkbox to forget.

Items render to a small neutral block list first, then to python-docx or
reportlab, so both formats lay out the same: one typeface at 11 pt, real
headings, MCQ options as a hanging-indented "A. B. C. D." list rather than
bullets, numbered questions with space between them, and a footer carrying the
honor-code line and the page number.
"""

from __future__ import annotations

import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.extraction.schema import ExtractedSyllabus
from app.models import Item

from .schemas import ITEM_TYPES, QUESTION_TYPES, TYPE_LABELS

# Block kinds:
#   h1 h2 h3        headings (real outline levels, plan H.4)
#   p               body paragraph
#   q               a numbered question stem: (number, text, points or None)
#   options         [(label, text)] as a hanging-indent A./B./C. list
#   indent          one indented paragraph (an explanation under a key line)
#   small           small print (tags, notes)
#   bullets         unnumbered list
#   numbered        (a) (b) (c) list
#   table           list of rows
#   code            preformatted text
#   image           (png bytes, alt text)
#   rule            a thin horizontal rule
#   fillin          a name/ID line on a question paper
#   spacer          vertical space
#   pagebreak       page break
Block = tuple

BODY_FONT = "Calibri"  # one clean sans, present in Word everywhere
PDF_FONT = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
BODY_PT = 11.0

HONOR_LINE = "Assessment material. Handle under the AURAK Honor Code."

PART_PAPER = "paper"
PART_KEY = "key"
PARTS = (PART_PAPER, PART_KEY)

_GROUP_TITLES = {
    "mcq": "Multiple-choice questions", "short_answer": "Short-answer questions", "problem": "Problems",
    "practice_set": "Practice exercises", "code_exercise": "Code exercises", "lesson_plan": "Lesson plans",
    "case_study": "Case studies",
    "learning_resource": "Learning resources", "rubric": "Rubrics",
}


@dataclass
class DocMeta:
    """Document-level settings both renderers honour."""

    title: str = "EduForge export"
    footer: str = HONOR_LINE
    page_numbers: bool = True


def _tagline(it: Item) -> str:
    """Outcome / week / thinking level / difficulty. Faculty documents only,
    and in the same words as the rest of the tool: no "CLO"."""
    nums = ", ".join(map(str, it.clo_ids))
    parts = [f"Outcome{'s' if len(it.clo_ids) != 1 else ''} {nums}"]
    if it.week_no:
        parts.append(f"Week {it.week_no}")
    if it.bloom_level:
        parts.append(it.bloom_level.capitalize())
    if it.difficulty:
        parts.append(it.difficulty)
    return " · ".join(parts)


def _body_blocks(it: Item, n: int, tags: bool = False, points: float | None = None) -> list[Block]:
    """One item as it appears to a student. ``tags`` adds the CLO/week/Bloom
    line, so it is off for a question paper and on for faculty documents."""
    b = it.body_json
    out: list[Block] = []
    t = it.type
    if t == "mcq":
        out.append(("q", (n, b["stem"], points)))
        out.append(("options", [(o["label"], o["text"]) for o in b["options"]]))
    elif t == "short_answer":
        out.append(("q", (n, b["question"], points)))
        out.append(("small", f"Expected length: {b['expected_length']}"))
    elif t == "problem":
        out.append(("q", (n, b["statement"], points)))
        if b.get("given"):
            out.append(("bullets", [f"{g['name']} = {g['value']:g}{(' ' + g['unit']) if g.get('unit') else ''}"
                                    f"{(' — ' + g['description']) if g.get('description') else ''}"
                                    for g in b["given"]]))
        out.append(("indent", f"Find: {b['asks_for']}"))
    elif t == "practice_set":
        out.append(("h3", f"{n}. {b['title']}"))
        out.append(("p", b["instructions"]))
        out.append(("numbered", [e["prompt"] for e in b["exercises"]]))
    elif t == "lesson_plan":
        out.append(("h3", f"{n}. {b['title']} ({b['session_minutes']} min)"))
        out.append(("p", "Objectives:"))
        out.append(("bullets", b["objectives"]))
        if b.get("prior_knowledge"):
            out.append(("p", f"Prior knowledge: {b['prior_knowledge']}"))
        out.append(("table", [["Activity", "Min", "Description"]] +
                    [[a["name"], str(a["minutes"]), a["description"]] for a in b["activities"]]))
        if b.get("materials"):
            out.append(("p", "Materials: " + "; ".join(b["materials"])))
        out.append(("p", f"Check for understanding: {b['check_for_understanding']}"))
        if b.get("after_class"):
            out.append(("p", f"After class: {b['after_class']}"))
    elif t == "case_study":
        out.append(("h3", f"{n}. {b['title']}"))
        out.append(("p", b["scenario"]))
        out.append(("numbered", [q["question"] for q in b["questions"]]))
    elif t == "learning_resource":
        out.append(("h3", f"{n}. {b['title']}"))
        for para in b["content"].split("\n\n"):
            if para.strip():
                out.append(("p", para.strip().replace("**", "")))
        if b.get("further_reading"):
            out.append(("p", "Further reading:"))
            out.append(("bullets", b["further_reading"]))
    elif t == "rubric":
        out.append(("h3", f"{n}. {b['title']}"))
        out.append(("p", f"Task: {b['task']}"))
        for c in b["criteria"]:
            levels = sorted(c["levels"], key=lambda lv: -lv["points"])
            out.append(("table", [[c["criterion"]] + [f"{lv['label']} ({lv['points']:g})" for lv in levels],
                                  [""] + [lv["descriptor"] for lv in levels]]))
    elif t == "code_exercise":
        out.append(("q", (n, b["prompt"], points)))
        out.append(("code", b.get("starter_code", "")))
    out += _figure_blocks(b.get("figure"))
    if tags:
        out.append(("small", _tagline(it)))
    out.append(("spacer", 10))
    return out


def _key_blocks(it: Item, n: int, tags: bool = True, shown_label: str | None = None) -> list[Block]:
    """One item's answer key: the correct answer, the explanation, the rationale
    for every wrong option, and the CLO/week/Bloom tags."""
    k, f, b = it.answer_key_json or {}, it.feedback_prompts_json or {}, it.body_json
    out: list[Block] = []
    t = it.type
    if t == "mcq":
        correct = shown_label or k.get("correct", "?")
        out.append(("q", (n, f"Correct answer: {correct}", None)))
        if k.get("why_correct"):
            out.append(("indent", k["why_correct"]))
        wrong = k.get("why_others_wrong") or {}
        if wrong:
            out.append(("indent", "Why the other options are wrong:"))
            out.append(("options", sorted(wrong.items())))
    elif t == "short_answer":
        out.append(("q", (n, k.get("model_answer", ""), None)))
        if k.get("key_points"):
            out.append(("bullets", [f"Key point: {p}" for p in k["key_points"]]))
    elif t == "problem":
        out.append(("q", (n, k.get("final_answer_text", ""), None)))
        out.append(("numbered", k.get("solution_steps") or []))
    elif t == "practice_set":
        out.append(("q", (n, b["title"], None)))
        out.append(("numbered", [e["answer"] for e in b["exercises"]]))
    elif t == "code_exercise":
        out.append(("q", (n, "Reference solution", None)))
        out.append(("code", k.get("solution_code", "")))
        out.append(("p", "Hidden tests"))
        out.append(("code", k.get("tests_code", "")))
        if k.get("explanation"):
            out.append(("indent", k["explanation"]))
    elif t == "case_study":
        out.append(("q", (n, b["title"], None)))
        out.append(("numbered", [q["model_answer"] for q in b["questions"]]))
        out.append(("indent", f"Teaching notes: {k.get('teaching_notes', '')}"))
    else:
        return []
    ds = (b.get("figure") or {}).get("dataset")
    if ds:
        from .rich import DatasetError, generate

        try:
            s = generate(ds)["summary"]
            out.append(("small", "Dataset facts (computed): " + ", ".join(
                f"{key} = {v:.4g}" if isinstance(v, float) else f"{key} = {v}" for key, v in s.items())))
        except DatasetError:
            pass
    if f and (f.get("hint") or f.get("explanation")):
        out.append(("small", " ".join(x for x in [f"Hint: {f.get('hint', '')}".strip(),
                                                  f"Explanation: {f.get('explanation', '')}".strip()] if x)))
    if tags:
        out.append(("small", _tagline(it)))
    out.append(("spacer", 8))
    return out


def _figure_blocks(fig: dict | None) -> list[Block]:
    """A figure as an image; a diagram the server can't render goes out as its source."""
    if not fig:
        return []
    from .rich import DatasetError, figure_png

    caption = fig.get("caption") or ""
    try:
        png = figure_png(fig)
    except DatasetError as e:
        return [("small", f"[Figure not generated: {e}]")]
    if png:
        alt = caption or ("Chart of the generated dataset" if fig.get("dataset") else f"{fig['diagram']['kind']} diagram")
        return [("image", (png, alt)), *([("small", caption)] if caption else [])]
    if fig.get("diagram"):
        dg = fig["diagram"]
        return [("small", f"Diagram ({dg['kind']} source; render it before use): {caption}"), ("code", dg["source"])]
    return []


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #

def course_line(rec: ExtractedSyllabus) -> str:
    return " ".join(x for x in [rec.course.code, rec.course.title] if x) or "Course"


def _by_type(items: list[Item]) -> tuple[dict[str, list[Item]], list[str]]:
    groups: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        groups[it.type].append(it)
    return groups, [t for t in ITEM_TYPES if t in groups]


def paper_heading(rec: ExtractedSyllabus, subtitle: str, name_line: bool) -> list[Block]:
    blocks: list[Block] = [("h1", course_line(rec))]
    sub = " · ".join(x for x in [rec.offering.term or "", subtitle] if x)
    if sub:
        blocks.append(("subtitle", sub))
    blocks.append(("rule", None))
    if name_line:
        blocks.append(("fillin", [("Name", 40), ("Student ID", 18)]))
        blocks.append(("rule", None))
    blocks.append(("spacer", 8))
    return blocks


def build_paper(rec: ExtractedSyllabus, items: list[Item]) -> tuple[list[Block], DocMeta]:
    """The student-facing document: numbered questions, no answers, no tags."""
    groups, order = _by_type(items)
    exam = bool(items) and all(it.type in QUESTION_TYPES for it in items)
    subtitle = "Question paper" if exam else "Approved teaching items"
    blocks = paper_heading(rec, subtitle, name_line=exam)
    single_group = len(order) == 1
    n = 0  # numbering runs through the whole paper, as on a real exam
    for t in order:
        if not single_group:
            blocks.append(("h2", _GROUP_TITLES[t]))
        for it in groups[t]:
            n += 1
            blocks += _body_blocks(it, n, tags=False)
    title = f"{course_line(rec)} — {subtitle}"
    return blocks, DocMeta(title=title, footer=HONOR_LINE)


def build_key(rec: ExtractedSyllabus, items: list[Item]) -> tuple[list[Block], DocMeta]:
    """The faculty answer key, as its own file: correct answers, explanations,
    per-option rationale and the CLO/week/Bloom tags. The numbers match the
    question paper, because both walk the items in the same order."""
    groups, order = _by_type(items)
    approvers = sorted({i.approved_by.name for i in items if i.approved_by})
    blocks: list[Block] = [("h1", f"{course_line(rec)} — Answer key")]
    sub = " · ".join(x for x in [rec.offering.term or "", f"{len(items)} item(s)",
                                 f"exported {date.today():%d %B %Y}"] if x)
    who = ", ".join(approvers) or "faculty"
    blocks += [("subtitle", sub), ("rule", None),
               ("note", f"Faculty copy. Drafted with AI assistance and approved by {who}."),
               ("spacer", 8)]
    single_group = len(order) == 1
    wrote = False
    n = 0
    for t in order:
        section: list[Block] = []
        for it in groups[t]:
            n += 1
            section += _key_blocks(it, n)
        if section:
            if not single_group:
                blocks.append(("h2", _GROUP_TITLES[t]))
            blocks += section
            wrote = True
    if not wrote:
        blocks.append(("p", "None of these item types has an answer key."))
    return blocks, DocMeta(title=f"{course_line(rec)} — Answer key",
                           footer="Faculty answer key. Do not hand out.")


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #

def to_docx(blocks: list[Block], meta: DocMeta | None = None) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    from .rich import render_math, split_math

    meta = meta or DocMeta()
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Inches(1)
    sec.top_margin = sec.bottom_margin = Inches(0.9)
    ink = RGBColor(0x1A, 0x1A, 0x1A)
    grey = RGBColor(0x5F, 0x64, 0x6C)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(BODY_PT)
    normal.font.color.rgb = ink
    normal.paragraph_format.space_after = Pt(6)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    for style_name, size in (("Heading 1", 17), ("Heading 2", 13), ("Heading 3", 11.5)):
        st = doc.styles[style_name]
        st.font.name = BODY_FONT
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = ink
        st.paragraph_format.space_before = Pt(14 if style_name != "Heading 1" else 0)
        st.paragraph_format.space_after = Pt(6)

    def rich(par, text: str) -> None:
        """Text with $...$ math: the math becomes inline images (plan 2.17)."""
        for kind_, piece in split_math(str(text)):
            if kind_ == "math":
                try:
                    shape = par.add_run().add_picture(io.BytesIO(render_math(piece)), height=Pt(12))
                    shape._inline.docPr.set("descr", piece)  # alt text = the LaTeX (plan H.4)
                    continue
                except ValueError:
                    piece = f"${piece}$"  # unparseable: keep the source
            par.add_run(piece)

    def _footer() -> None:
        par = sec.footer.paragraphs[0]
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = par.add_run(meta.footer)
        r.font.size = Pt(8.5)
        r.font.color.rgb = grey
        r.font.name = BODY_FONT
        if meta.page_numbers:
            tail = par.add_run("    Page ")
            tail.font.size = Pt(8.5)
            tail.font.color.rgb = grey
            tail.font.name = BODY_FONT
            for instr in ("PAGE", "NUMPAGES"):
                if instr == "NUMPAGES":
                    sep = par.add_run(" of ")
                    sep.font.size = Pt(8.5)
                    sep.font.color.rgb = grey
                    sep.font.name = BODY_FONT
                fld = par.add_run()._element
                from docx.oxml import OxmlElement

                simple = OxmlElement("w:fldSimple")
                simple.set(qn("w:instr"), instr)
                inner = OxmlElement("w:r")
                rpr = OxmlElement("w:rPr")
                size = OxmlElement("w:sz")
                size.set(qn("w:val"), "17")
                rpr.append(size)
                inner.append(rpr)
                txt = OxmlElement("w:t")
                txt.text = "1"
                inner.append(txt)
                simple.append(inner)
                fld.addnext(simple)

    _footer()

    for kind, payload in blocks:
        if kind in {"h1", "h2", "h3"}:
            rich(doc.add_paragraph(style=f"Heading {kind[1]}"), payload)
        elif kind == "subtitle":
            par = doc.add_paragraph()
            par.paragraph_format.space_after = Pt(8)
            r = par.add_run(payload)
            r.font.size = Pt(10.5)
            r.font.color.rgb = grey
        elif kind == "p":
            rich(doc.add_paragraph(), payload)
        elif kind == "q":
            n, text, points = payload
            par = doc.add_paragraph()
            pf = par.paragraph_format
            pf.space_before = Pt(10)
            pf.left_indent = Inches(0.33)
            pf.first_line_indent = Inches(-0.33)
            par.paragraph_format.tab_stops.add_tab_stop(Inches(0.33), WD_TAB_ALIGNMENT.LEFT)
            head = par.add_run(f"{n}.\t")
            head.bold = True
            rich(par, text)
            if points is not None:
                pts = par.add_run(f"  ({points:g} point{'s' if points != 1 else ''})")
                pts.font.size = Pt(9.5)
                pts.font.color.rgb = grey
        elif kind == "options":
            for label, text in payload:
                par = doc.add_paragraph()
                pf = par.paragraph_format
                pf.left_indent = Inches(0.78)
                pf.first_line_indent = Inches(-0.3)
                pf.space_after = Pt(3)
                par.paragraph_format.tab_stops.add_tab_stop(Inches(0.78), WD_TAB_ALIGNMENT.LEFT)
                par.add_run(f"{label}.\t")
                rich(par, text)
        elif kind == "indent":
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Inches(0.33)
            rich(par, payload)
        elif kind in {"small", "note"}:
            par = doc.add_paragraph()
            if kind == "small":
                par.paragraph_format.left_indent = Inches(0.33)
            r = par.add_run(payload)
            r.font.size = Pt(9)
            r.font.color.rgb = grey
        elif kind == "bullets":
            for x in payload:
                par = doc.add_paragraph(style="List Bullet")
                par.paragraph_format.left_indent = Inches(0.78)
                rich(par, x)
        elif kind == "numbered":
            for i, x in enumerate(payload, 1):
                par = doc.add_paragraph()
                pf = par.paragraph_format
                pf.left_indent = Inches(0.78)
                pf.first_line_indent = Inches(-0.3)
                pf.space_after = Pt(3)
                par.paragraph_format.tab_stops.add_tab_stop(Inches(0.78), WD_TAB_ALIGNMENT.LEFT)
                par.add_run(f"({chr(96 + i) if i <= 26 else i})\t")
                rich(par, x)
        elif kind == "image":
            png, alt = payload
            shape = doc.add_picture(io.BytesIO(png), width=Inches(4.5))
            shape._inline.docPr.set("descr", alt)  # alt text (plan H.4)
        elif kind == "code":
            for line in str(payload).splitlines() or [""]:
                par = doc.add_paragraph()
                par.paragraph_format.left_indent = Inches(0.4)
                par.paragraph_format.space_after = Pt(0)
                r = par.add_run(line)
                r.font.name = "Consolas"
                r.font.size = Pt(9)
        elif kind == "table":
            t = doc.add_table(rows=len(payload), cols=max(len(r) for r in payload))
            t.style = "Table Grid"
            for ri, row in enumerate(payload):
                for ci, cell in enumerate(row):
                    para = t.cell(ri, ci).paragraphs[0]
                    r = para.add_run(cell)
                    r.font.size = Pt(9.5)
                    r.bold = ri == 0
        elif kind == "fillin":
            par = doc.add_paragraph()
            par.paragraph_format.space_before = Pt(6)
            for i, (label, width) in enumerate(payload):
                if i:
                    par.add_run("     ")
                par.add_run(f"{label}: ")
                par.add_run("_" * width)
        elif kind == "rule":
            par = doc.add_paragraph()
            par.paragraph_format.space_after = Pt(2)
            from docx.oxml import OxmlElement

            bottom = OxmlElement("w:pBdr")
            line = OxmlElement("w:bottom")
            line.set(qn("w:val"), "single")
            line.set(qn("w:sz"), "6")
            line.set(qn("w:color"), "BFBFBF")
            bottom.append(line)
            par._p.get_or_add_pPr().append(bottom)
        elif kind == "spacer":
            par = doc.add_paragraph()
            par.paragraph_format.space_after = Pt(float(payload))
        elif kind == "pagebreak":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

def to_pdf(blocks: list[Block], meta: DocMeta | None = None) -> bytes:
    import tempfile

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        Preformatted,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    from .rich import render_math, split_math

    meta = meta or DocMeta()
    ink = colors.HexColor("#1A1A1A")
    grey = colors.HexColor("#5F646C")

    def style(name: str, **kw) -> ParagraphStyle:
        base = dict(fontName=PDF_FONT, fontSize=BODY_PT, leading=BODY_PT * 1.42, textColor=ink,
                    alignment=TA_LEFT, spaceAfter=6)
        base.update(kw)
        return ParagraphStyle(name, **base)

    body = style("body")
    h1 = style("h1", fontName=PDF_FONT_BOLD, fontSize=17, leading=21, spaceAfter=2)
    h2 = style("h2", fontName=PDF_FONT_BOLD, fontSize=13, leading=16, spaceBefore=14, spaceAfter=6)
    h3 = style("h3", fontName=PDF_FONT_BOLD, fontSize=11.5, leading=14, spaceBefore=12, spaceAfter=5)
    subtitle = style("subtitle", fontSize=10.5, textColor=grey, spaceAfter=8)
    question = style("q", leftIndent=20, firstLineIndent=-20, spaceBefore=10)
    option = style("opt", leftIndent=46, firstLineIndent=-24, spaceAfter=3)
    indented = style("indent", leftIndent=20)
    small = style("small", fontSize=9, textColor=grey, leftIndent=20, leading=11.5)
    note = style("note", fontSize=9, textColor=grey, leading=11.5)
    cell = style("cell", fontSize=9.5, leading=12, spaceAfter=0)
    code_style = style("code", fontName="Courier", fontSize=8.5, leading=10.5)
    HEADINGS = {"h1": h1, "h2": h2, "h3": h3}

    tmp = tempfile.TemporaryDirectory(prefix="eduforge-export-")
    n_img = [0]

    def esc_plain(s: str) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

    def esc(s: str) -> str:
        """Escape for reportlab markup; $...$ math becomes an inline image (plan 2.17)."""
        out = []
        for kind_, piece in split_math(str(s)):
            if kind_ == "math":
                try:
                    png = render_math(piece)
                except ValueError:
                    out.append(esc_plain(f"${piece}$"))
                    continue
                n_img[0] += 1
                path = f"{tmp.name}/m{n_img[0]}.png"
                with open(path, "wb") as fh:
                    fh.write(png)
                from PIL import Image as PILImage

                w, h = PILImage.open(io.BytesIO(png)).size
                out.append(f'<img src="{path}" height="11" width="{11 * w / h:.1f}" valign="middle"/>')
            else:
                out.append(esc_plain(piece))
        return "".join(out)

    story: list = []
    width = A4[0] - 4 * cm
    for kind, payload in blocks:
        if kind in HEADINGS:
            story.append(Paragraph(esc(payload), HEADINGS[kind]))
        elif kind == "subtitle":
            story.append(Paragraph(esc(payload), subtitle))
        elif kind == "p":
            story.append(Paragraph(esc(payload), body))
        elif kind == "q":
            n, text, points = payload
            tail = (f' <font size="9.5" color="#5F646C">({points:g} '
                    f"point{'s' if points != 1 else ''})</font>") if points is not None else ""
            story.append(Paragraph(f"<b>{n}.</b>&nbsp;&nbsp;{esc(text)}{tail}", question))
        elif kind == "options":
            for label, text in payload:
                story.append(Paragraph(f"{esc(label)}.&nbsp;&nbsp;&nbsp;{esc(text)}", option))
        elif kind == "indent":
            story.append(Paragraph(esc(payload), indented))
        elif kind == "image":
            from PIL import Image as PILImage

            png, _alt = payload
            w, h = PILImage.open(io.BytesIO(png)).size
            dw = min(width * 0.75, w)
            story.append(Image(io.BytesIO(png), width=dw, height=dw * h / w))
        elif kind == "code":
            story.append(Preformatted(str(payload), code_style))
            story.append(Spacer(1, 4))
        elif kind == "small":
            story.append(Paragraph(esc(payload), small))
        elif kind == "note":
            story.append(Paragraph(esc(payload), note))
        elif kind in {"bullets", "numbered"}:
            story.append(ListFlowable([ListItem(Paragraph(esc(x), body)) for x in payload],
                                      bulletType="bullet" if kind == "bullets" else "a",
                                      leftIndent=26, bulletFontName=PDF_FONT, bulletFontSize=BODY_PT))
        elif kind == "table":
            ncol = max(len(r) for r in payload)
            data = [[Paragraph(esc(c), cell) for c in r] + [""] * (ncol - len(r)) for r in payload]
            t = Table(data, colWidths=[width / ncol] * ncol)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CFCFD2")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("FONTNAME", (0, 0), (-1, 0), PDF_FONT_BOLD),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F3F4"))]))
            story.append(t)
            story.append(Spacer(1, 6))
        elif kind == "fillin":
            line = "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(f"{label}: {'_' * w}" for label, w in payload)
            story.append(Paragraph(line, style("fill", spaceBefore=6)))
        elif kind == "rule":
            story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#BFBFBF"),
                                    spaceBefore=2, spaceAfter=2))
        elif kind == "spacer":
            story.append(Spacer(1, float(payload)))
        elif kind == "pagebreak":
            story.append(PageBreak())

    def decorate(canvas, doc_) -> None:
        canvas.saveState()
        canvas.setFont(PDF_FONT, 8.5)
        canvas.setFillColor(grey)
        text = meta.footer + (f"    Page {doc_.page}" if meta.page_numbers else "")
        canvas.drawCentredString(A4[0] / 2, 1.15 * cm, text)
        canvas.restoreState()

    buf = io.BytesIO()
    try:
        SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.2 * cm,
                          bottomMargin=2 * cm, title=meta.title, author="EduForge",
                          ).build(story, onFirstPage=decorate, onLaterPages=decorate)
    finally:
        tmp.cleanup()
    return buf.getvalue()


# --------------------------------------------------------------------------- #

def write(blocks: list[Block], meta: DocMeta, fmt: str, stem: str) -> tuple[bytes, str, str]:
    if fmt == "docx":
        return (to_docx(blocks, meta), stem + ".docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if fmt == "pdf":
        return to_pdf(blocks, meta), stem + ".pdf", "application/pdf"
    raise ValueError(f"Unknown format '{fmt}'")


def render(rec: ExtractedSyllabus, items: list[Item], fmt: str, part: str = PART_PAPER) -> tuple[bytes, str, str]:
    """``part='paper'`` gives the student question paper, ``part='key'`` the
    faculty answer key. They are always separate files."""
    if part not in PARTS:
        raise ValueError(f"part must be one of {', '.join(PARTS)}")
    blocks, meta = build_key(rec, items) if part == PART_KEY else build_paper(rec, items)
    code = (rec.course.code or "course").replace(" ", "")
    term = (rec.offering.term or "").replace(" ", "")
    stem = "_".join(x for x in [code, term, "answer_key" if part == PART_KEY else "question_paper"] if x)
    return write(blocks, meta, fmt, stem)


__all__ = ["PARTS", "PART_KEY", "PART_PAPER", "TYPE_LABELS", "DocMeta", "build_key", "build_paper", "render",
           "to_docx", "to_pdf", "write"]
