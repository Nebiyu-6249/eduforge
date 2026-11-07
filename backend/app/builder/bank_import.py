"""Import existing question banks (plan 3.7).

DOCX / PDF / TXT question files and QTI packages -> items with status
`suggested`, tagged with CLO, week and Bloom level, then reviewed as usual.

Old exams are real exam items, so (plan 14.10) no hosted model reads them:
questions are split deterministically, and tags come from the local embedder
(question text vs the locked CLOs and weekly topics) plus Bloom verbs. A
question whose answer isn't in the file is imported without a key; its schema
check then fails until faculty add the key, so nothing unchecked can be approved.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from app.drafts import bloom
from app.extraction.schema import ExtractedSyllabus
from app.llm.embeddings import LocalHashEmbedder, cosine


@dataclass
class Parsed:
    stem: str
    options: list[tuple[str, str]] = field(default_factory=list)
    answer: str | None = None


_Q = re.compile(r"^\s*(?:Q(?:uestion)?\s*)?(\d{1,3})\s*[.)]\s+(.*)$", re.I)
_OPT = re.compile(r"^\s*\(?([A-Ea-e])[.)]\s+(.*)$")
_ANS = re.compile(r"^\s*(?:answer|ans|key|correct(?: answer)?)\s*[:\-]\s*\(?([A-Ea-e])?\)?\s*(.*)$", re.I)


def _lines_from(filename: str, data: bytes) -> list[str]:
    name = filename.lower()
    if data[:5] == b"%PDF-":
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [ln for p in pdf.pages for ln in (p.extract_text(x_tolerance=1.5) or "").splitlines()]
    if name.endswith(".docx"):
        from docx import Document

        return [p.text for p in Document(io.BytesIO(data)).paragraphs]
    return data.decode("utf-8", errors="replace").splitlines()


def parse_text(filename: str, data: bytes) -> list[Parsed]:
    out: list[Parsed] = []
    cur: Parsed | None = None
    for raw in _lines_from(filename, data):
        line = raw.strip()
        if not line:
            continue
        if m := _Q.match(line):
            cur = Parsed(stem=m.group(2).strip())
            out.append(cur)
        elif cur and (m := _OPT.match(line)):
            cur.options.append((m.group(1).upper(), m.group(2).strip()))
        elif cur and (m := _ANS.match(line)):
            cur.answer = (m.group(1) or "").upper() or m.group(2).strip() or None
        elif cur:
            if cur.options:  # wrapped option text
                lbl, txt = cur.options[-1]
                cur.options[-1] = (lbl, f"{txt} {line}")
            else:
                cur.stem = f"{cur.stem} {line}"
    return [q for q in out if len(q.stem) > 5]


def parse_qti(data: bytes) -> list[Parsed]:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if not name.lower().endswith(".xml") or name.endswith("imsmanifest.xml"):
                continue
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            if not root.tag.endswith("assessmentItem"):
                continue
            ns = {"q": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
            pre = "q:" if ns else ""
            body = root.find(f"{pre}itemBody", ns)
            if body is None:
                continue
            stem = " ".join(p.text or "" for p in body.findall(f"{pre}p", ns)).strip() or (root.get("title") or "")
            opts = [(c.get("identifier") or "", (c.text or "").strip())
                    for c in body.iter() if c.tag.endswith("simpleChoice")]
            corr = root.find(f".//{pre}correctResponse/{pre}value", ns)
            labels = "ABCDE"
            remap = {ident: labels[i] for i, (ident, _) in enumerate(opts[:5])}
            out.append(Parsed(stem=stem, options=[(remap[i], t) for i, t in opts[:5]],
                              answer=remap.get(corr.text.strip()) if corr is not None and corr.text else None))
    return out


def parse(filename: str, data: bytes) -> list[Parsed]:
    if data[:2] == b"PK" and not filename.lower().endswith(".docx"):
        return parse_qti(data)
    return parse_text(filename, data)


def tag(questions: list[Parsed], rec: ExtractedSyllabus) -> list[dict]:
    """CLO and week by local-embedding similarity; Bloom by verbs. Never leaves the server."""
    emb = LocalHashEmbedder()
    clo_vecs = emb.embed([c.text for c in rec.clos]) if rec.clos else []
    week_vecs = emb.embed([" ".join(w.topics) for w in rec.weekly]) if rec.weekly else []
    qvecs = emb.embed([q.stem + " " + " ".join(t for _, t in q.options) for q in questions])
    tags = []
    for q, v in zip(questions, qvecs):
        cs = sorted(((cosine(v, cv), c.number) for c, cv in zip(rec.clos, clo_vecs)), reverse=True)
        ws = sorted(((cosine(v, wv), w.week_no) for w, wv in zip(rec.weekly, week_vecs)), reverse=True)
        level = bloom.clo_level(q.stem) or ("remember" if q.options else "understand")
        tags.append({"clo_numbers": [cs[0][1]] if cs else [], "week_no": ws[0][1] if ws and ws[0][0] > 0.1 else None,
                     "bloom_level": level, "difficulty": "medium",
                     "confidence": round(cs[0][0], 3) if cs else 0.0})
    return tags


def to_item_parts(q: Parsed) -> tuple[str, dict, dict, dict]:
    """(type, body, answer_key, feedback). A missing answer leaves the key incomplete on purpose."""
    if len(q.options) >= 2:
        body = {"stem": q.stem, "options": [{"label": lbl, "text": t} for lbl, t in q.options], "figure": None}
        key = {"correct": q.answer if q.answer in {lbl for lbl, _ in q.options} else "", "why_correct": "",
               "why_others_wrong": {}}
        return "mcq", body, key, {"hint": "", "explanation": ""}
    body = {"question": q.stem, "expected_length": "a few sentences", "figure": None}
    key = {"model_answer": q.answer or "", "key_points": [q.answer] if q.answer else []}
    return "short_answer", body, key, {"hint": "", "explanation": ""}
