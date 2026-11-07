"""Upload bytes -> ExtractedSyllabus.

1. Deterministic: DOCX tables / PDF layout text + ruling-line tables, mapped
   onto the AURAK template (mapper.py).
2. Only if a core section is still empty and an LLM is configured: the model
   transcribes that section from its text and, for PDFs, page images
   (llm_fill.py, HANDOFF §8.3). Each such section is flagged for faculty
   review. The model never overwrites what the parser read.
"""

from __future__ import annotations

from app.llm.gateway import LLMGateway

from .docx_reader import read_docx
from .llm_fill import fill_missing
from .mapper import map_blocks
from .pdf_reader import read_pdf
from .schema import ExtractedSyllabus

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"


class UnsupportedFile(ValueError):
    pass


def sniff(filename: str, data: bytes) -> str:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:2] == b"PK":
        from app.upload_guard import RejectedUpload, check_office_zip

        try:
            check_office_zip(data)  # plan H.3: macros, archive bombs, bad archives
        except RejectedUpload as e:
            raise UnsupportedFile(str(e)) from e
        return "docx"
    raise UnsupportedFile("Only PDF and DOCX syllabi are supported.")


def extract(filename: str, data: bytes, llm: LLMGateway | None = None) -> ExtractedSyllabus:
    kind = sniff(filename, data)
    try:
        blocks = read_pdf(data) if kind == "pdf" else read_docx(data)
    except Exception as e:  # corrupt or password-protected files
        raise UnsupportedFile(f"Could not read the {kind.upper()} file: {e}") from e
    rec = map_blocks(blocks)
    if not rec.grading_scale:
        from app.grading.scale import parse_scale

        rec.grading_scale = parse_scale(rec)
    if not rec.grading_scale:
        from app.grading.scale import parse_scale

        rec.grading_scale = parse_scale(rec)
    return fill_missing(rec, kind, data, llm)
