"""Export APPROVED items only, as DOCX or PDF (D9: files, no Blackboard).

Items render to a small neutral block list first, then to python-docx or
reportlab, so both formats lay out the same. The answer key (keys, model
answers, teaching notes, feedback prompts) goes in a separate section that
can be left out for a student-facing copy.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import date

from app.extraction.schema import ExtractedSyllabus
from app.models import Item

from .schemas import ITEM_TYPES, TYPE_LABELS

Block = tuple  # ("h1"|"h2"|"h3"|"p"|"small"|"bullets"|"numbered"|"table", payload)

_GROUP_TITLES = {
    "mcq": "Multiple-choice questions", "short_answer": "Short-answer questions", "problem": "Problems",
    "practice_set": "Practice exercises", "code_exercise": "Code exercises", "lesson_plan": "Lesson plans",
    "case_study": "Case studies",
    "learning_resource": "Learning resources", "rubric": "Rubrics",
}


def _tagline(it: Item) -> str:
    parts = [f"CLO {', '.join(map(str, it.clo_ids))}"]
    if it.week_no:
        parts.append(f"Week {it.week_no}")
    if it.bloom_level:
        parts.append(it.bloom_level.capitalize())
    if it.difficulty:
        parts.append(it.difficulty)
    return " · ".join(parts)


def _body_blocks(it: Item, n: int) -> list[Block]:
    b = it.body_json
    out: list[Block] = []
    t = it.type
    if t == "mcq":
        out.append(("p", f"{n}. {b['stem']}"))
        out.append(("bullets", [f"{o['label']}. {o['text']}" for o in b["options"]]))
    elif t == "short_answer":
        out.append(("p", f"{n}. {b['question']}"))
        out.append(("small", f"Expected length: {b['expected_length']}"))
    elif t == "problem":
        out.append(("p", f"{n}. {b['statement']}"))
        if b.get("given"):
            out.append(("bullets", [f"{g['name']} = {g['value']:g}{(' ' + g['unit']) if g.get('unit') else ''}"
                                    f"{(' — ' + g['description']) if g.get('description') else ''}" for g in b["given"]]))
        out.append(("p", f"Find: {b['asks_for']}"))
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
    if t == "code_exercise":
        out.append(("p", f"{n}. {b['prompt']}"))
        out.append(("code", b.get("starter_code", "")))
    out += _figure_blocks(b.get("figure"))
    out.append(("small", _tagline(it)))
    return out


def _key_blocks(it: Item, n: int) -> list[Block]:
    k, f, b = it.answer_key_json or {}, it.feedback_prompts_json or {}, it.body_json
    out: list[Block] = []
    t = it.type
    if t == "mcq":
        out.append(("p", f"{n}. {k['correct']} — {k['why_correct']}"))
        if k.get("why_others_wrong"):
            out.append(("bullets", [f"{lbl}: {why}" for lbl, why in sorted(k["why_others_wrong"].items())]))
    elif t == "short_answer":
        out.append(("p", f"{n}. {k['model_answer']}"))
        out.append(("bullets", [f"Key point: {p}" for p in k["key_points"]]))
    elif t == "problem":
        out.append(("p", f"{n}. {k['final_answer_text']}"))
        out.append(("numbered", k["solution_steps"]))
    elif t == "practice_set":
        out.append(("p", f"{n}. {b['title']}"))
        out.append(("numbered", [e["answer"] for e in b["exercises"]]))
    elif t == "code_exercise":
        out.append(("p", f"{n}. Reference solution"))
        out.append(("code", k.get("solution_code", "")))
        out.append(("p", "Hidden tests"))
        out.append(("code", k.get("tests_code", "")))
        if k.get("explanation"):
            out.append(("p", k["explanation"]))
    elif t == "case_study":
        out.append(("p", f"{n}. {b['title']}"))
        out.append(("numbered", [q["model_answer"] for q in b["questions"]]))
        out.append(("p", f"Teaching notes: {k['teaching_notes']}"))
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
    if f:
        out.append(("small", f"Hint: {f.get('hint', '')}  Explanation: {f.get('explanation', '')}"))
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


def build_blocks(rec: ExtractedSyllabus, items: list[Item], include_key: bool) -> list[Block]:
    approvers = sorted({i.approved_by.name for i in items if i.approved_by})
    blocks: list[Block] = [
        ("h1", f"{rec.course.code} {rec.course.title}"),
        ("p", f"{rec.offering.term or ''} · {len(items)} approved item(s) · exported {date.today():%d %B %Y}"),
        ("small", (f"Drafted with AI assistance and approved by {', '.join(approvers) or 'faculty'}. "
                   "Assessment material: handle under the AURAK Honor Code.")),
    ]
    by_type: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_type[it.type].append(it)
    order = [t for t in ITEM_TYPES if t in by_type]
    for t in order:
        blocks.append(("h2", _GROUP_TITLES[t]))
        for n, it in enumerate(by_type[t], 1):
            blocks += _body_blocks(it, n)
    if include_key:
        key_sections = [(t, [(n, it) for n, it in enumerate(by_type[t], 1)]) for t in order]
        key_blocks: list[Block] = []
        for t, numbered in key_sections:
            section = [b for n, it in numbered for b in _key_blocks(it, n)]
            if section:
                key_blocks.append(("h2", f"{_GROUP_TITLES[t]} — answer key"))
                key_blocks += section
        if key_blocks:
            blocks.append(("pagebreak", None))
            blocks.append(("h1", "Answer key"))
            blocks += key_blocks
    return blocks


# --------------------------------------------------------------------------- #

def to_docx(blocks: list[Block]) -> bytes:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Inches, Pt

    from .rich import render_math, split_math

    def rich(par, text: str) -> None:
        """Text with $…$ math: the math becomes inline images (plan 2.17)."""
        for kind_, piece in split_math(str(text)):
            if kind_ == "math":
                try:
                    shape = par.add_run().add_picture(io.BytesIO(render_math(piece)), height=Pt(12))
                    shape._inline.docPr.set("descr", piece)  # alt text = the LaTeX (plan H.4)
                    continue
                except ValueError:
                    piece = f"${piece}$"  # unparseable: keep the source
            par.add_run(piece)

    doc = Document()
    for kind, payload in blocks:
        if kind == "h1":
            doc.add_heading(payload, level=1)
        elif kind == "h2":
            doc.add_heading(payload, level=2)
        elif kind == "h3":
            rich(doc.add_heading(level=3), payload)
        elif kind == "p":
            rich(doc.add_paragraph(), payload)
        elif kind == "small":
            r = doc.add_paragraph().add_run(payload)
            r.italic = True
            r.font.size = Pt(8.5)
        elif kind == "bullets":
            for x in payload:
                rich(doc.add_paragraph(style="List Bullet"), x)
        elif kind == "numbered":
            for i, x in enumerate(payload, 1):
                rich(doc.add_paragraph(), f"({chr(96 + i) if i <= 26 else i}) {x}")
        elif kind == "image":
            png, alt = payload
            shape = doc.add_picture(io.BytesIO(png), width=Inches(4.5))
            shape._inline.docPr.set("descr", alt)  # alt text (plan H.4)
        elif kind == "code":
            for line in str(payload).splitlines() or [""]:
                r = doc.add_paragraph().add_run(line)
                r.font.name = "Consolas"
                r.font.size = Pt(9)
        elif kind == "table":
            t = doc.add_table(rows=len(payload), cols=max(len(r) for r in payload))
            t.style = "Table Grid"
            for ri, row in enumerate(payload):
                for ci, cell in enumerate(row):
                    t.cell(ri, ci).text = cell
        elif kind == "pagebreak":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def to_pdf(blocks: list[Block]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=8, textColor=colors.HexColor("#555555"))
    cell = ss["BodyText"].clone("cell", fontSize=8.5, leading=10.5)

    import tempfile

    from reportlab.platypus import Image, Preformatted

    from .rich import render_math, split_math

    tmp = tempfile.TemporaryDirectory(prefix="eduforge-export-")
    n_img = [0]

    def esc_plain(s: str) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

    def esc(s: str) -> str:
        """Escape for reportlab markup; $…$ math becomes an inline image (plan 2.17)."""
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

    code_style = ss["Code"].clone("code", fontSize=8, leading=9.5)
    story = []
    width = A4[0] - 4 * cm
    for kind, payload in blocks:
        if kind in {"h1", "h2", "h3"}:
            story.append(Paragraph(esc(payload), ss[{"h1": "Heading1", "h2": "Heading2", "h3": "Heading3"}[kind]]))
        elif kind == "p":
            story.append(Paragraph(esc(payload), ss["BodyText"]))
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
            story.append(Spacer(1, 6))
        elif kind in {"bullets", "numbered"}:
            story.append(ListFlowable([ListItem(Paragraph(esc(x), ss["BodyText"])) for x in payload],
                                      bulletType="bullet" if kind == "bullets" else "a", leftIndent=14))
        elif kind == "table":
            ncol = max(len(r) for r in payload)
            data = [[Paragraph(esc(c), cell) for c in r] + [""] * (ncol - len(r)) for r in payload]
            t = Table(data, colWidths=[width / ncol] * ncol)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1efe8"))]))
            story.append(t)
            story.append(Spacer(1, 6))
        elif kind == "pagebreak":
            story.append(PageBreak())
    buf = io.BytesIO()
    try:
        SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, title="Approved items").build(story)
    finally:
        tmp.cleanup()
    return buf.getvalue()


def render(rec: ExtractedSyllabus, items: list[Item], fmt: str, include_key: bool) -> tuple[bytes, str, str]:
    blocks = build_blocks(rec, items, include_key)
    code = (rec.course.code or "course").replace(" ", "")
    name = f"{code}_{(rec.offering.term or '').replace(' ', '')}_approved_items{'_with_key' if include_key else ''}"
    if fmt == "docx":
        return to_docx(blocks), name + ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if fmt == "pdf":
        return to_pdf(blocks), name + ".pdf", "application/pdf"
    raise ValueError(f"Unknown format '{fmt}'")


__all__ = ["TYPE_LABELS", "render"]
