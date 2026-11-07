"""Course materials library: upload, index, retrieve (plan 2.1–2.4).

Data hygiene (plan 11, 14.10): real exam items go only to a local model or the
chosen no-retention provider. A past exam is real exam material, so unless the
deployment sets LLM_NO_RETENTION (or the provider is local Ollama) its text is
embedded with the local embedder only and never placed in a generation prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm.embeddings import Embedder, LocalHashEmbedder, cosine, get_embedder
from app.models import MATERIAL_KINDS, Chunk, Course, CourseVersion, Faculty, Material, utcnow
from app.services.course_versions import WorkflowError, read_source, store_file

from .extract import UnsupportedMaterial, chunk_units, units_from_file

ALLOWED_SUFFIXES = (".pdf", ".pptx", ".docx", ".txt", ".md")


def sensitive_ok() -> bool:
    """May real exam material reach the configured model?"""
    s = get_settings()
    return s.llm_no_retention or (s.llm_provider or "").lower() in {"ollama", "none", "fake"}


def _course_of(db: Session, cv: CourseVersion) -> Course:
    if cv.course_id is None:
        raise WorkflowError("Lock the course version first: materials belong to the course.", 409)
    course = db.get(Course, cv.course_id)
    assert course is not None
    return course


def add_material(db: Session, me: Faculty, cv: CourseVersion, filename: str, data: bytes, kind: str,
                 week_no: int | None, title: str | None, licensed: bool) -> Material:
    if cv.faculty_id != me.id:
        raise WorkflowError("Not your course version.", 404)
    if kind not in MATERIAL_KINDS:
        raise WorkflowError(f"Kind must be one of {', '.join(MATERIAL_KINDS)}.", 422)
    if not filename.lower().endswith(ALLOWED_SUFFIXES) and data[:5] != b"%PDF-":
        raise WorkflowError("Materials can be PDF, PPTX, DOCX, TXT or MD.", 415)
    course = _course_of(db, cv)
    sf = _store_any(db, me, filename, data)
    m = Material(course_id=course.id, faculty_id=me.id, file_id=sf.id, kind=kind, week_no=week_no,
                 title=(title or filename)[:300], licensed=licensed, status="pending")
    db.add(m)
    db.flush()
    return m


def _store_any(db: Session, me: Faculty, filename: str, data: bytes):
    """store_file sniffs syllabus types (PDF/DOCX); materials also allow PPTX/TXT/MD."""
    import hashlib

    from app.models import SourceFile

    if data[:2] == b"PK":
        from app.upload_guard import RejectedUpload, check_office_zip

        try:
            # Office files must look like Office; a .zip (QTI package) gets the general ZIP checks.
            check_office_zip(data, office=not filename.lower().endswith(".zip"))  # plan H.3
        except RejectedUpload as e:
            raise WorkflowError(str(e), 415) from e
    if data[:5] == b"%PDF-" or filename.lower().endswith(".docx"):
        return store_file(db, me, filename, data)
    sha = hashlib.sha256(data).hexdigest()
    ext = filename.rsplit(".", 1)[-1].lower()
    key = f"{sha[:2]}/{sha}.{ext}"
    from app import storage

    storage.put(db, key, data)
    mime = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "txt": "text/plain", "md": "text/markdown"}.get(ext, "application/octet-stream")
    sf = SourceFile(filename=filename, mime=mime, sha256=sha, size_bytes=len(data), storage_key=key,
                    uploaded_by_id=me.id)
    db.add(sf)
    db.flush()
    return sf


def index_material(db: Session, m: Material, embedder: Embedder | None = None,
                   progress: Callable[[int, str], None] | None = None) -> Material:
    """Extract, chunk and embed one material (the 'index_material' job)."""
    step = progress or (lambda pct, msg: None)
    m.chunks.clear()
    m.chunk_count, m.error = 0, None
    if m.kind == "textbook" and not m.licensed:
        m.status = "blocked"
        m.error = ("Commercial textbooks are not indexed unless you confirm the university holds a licence "
                   "that allows it (plan 2.4).")
        db.flush()
        return m
    step(10, "Reading the file")
    try:
        units = units_from_file(m.file.filename, read_source(m.file))
    except UnsupportedMaterial as e:
        m.status, m.error = "failed", str(e)
        db.flush()
        return m
    except Exception as e:  # noqa: BLE001 - corrupt or protected files
        m.status, m.error = "failed", f"Couldn't read the file: {e}"[:500]
        db.flush()
        return m
    chunks = chunk_units(units)
    if not chunks:
        m.status, m.error = "failed", "No text found (scanned images need OCR, which isn't supported yet)."
        db.flush()
        return m
    if m.kind == "past_exam" and not sensitive_ok():
        embedder = LocalHashEmbedder()  # never send real exam items to a hosted model
    embedder = embedder or get_embedder()
    step(40, f"Embedding {len(chunks)} chunk(s)")
    vecs: list[list[float]] = []
    for i in range(0, len(chunks), 32):
        vecs.extend(embedder.embed([c.text for c in chunks[i:i + 32]]))
    for i, (c, v) in enumerate(zip(chunks, vecs)):
        m.chunks.append(Chunk(course_id=m.course_id, ord=i, week_no=m.week_no, location=c.location, text=c.text,
                              token_estimate=c.token_estimate, embed_model=embedder.name, embedding=v))
    m.status, m.chunk_count, m.embed_model, m.indexed_at = "indexed", len(chunks), embedder.name, utcnow()
    db.flush()
    return m


# --------------------------------------------------------------------------- #
# Retrieval (plan 2.3)
# --------------------------------------------------------------------------- #

@dataclass
class Hit:
    chunk: Chunk
    score: float
    material: Material


def retrieve(db: Session, course_id: int, query: str, weeks: list[int] | None = None, k: int = 5,
             embedder: Embedder | None = None, include_exams: bool | None = None) -> list[Hit]:
    """Top-k chunks of this course for a query, filtered by week range.

    Week filter: chunks tagged with a week inside [min(weeks)-1, max(weeks)]
    (the week before often introduces the topic), plus untagged general
    material. Cosine similarity is computed in Python: a course has hundreds of
    chunks, not millions; switch to pgvector SQL ordering + an HNSW index if
    that changes.
    """
    embedder = embedder or get_embedder()
    include_exams = sensitive_ok() if include_exams is None else include_exams
    q = select(Chunk, Material).join(Material, Chunk.material_id == Material.id).where(
        Chunk.course_id == course_id, Material.status == "indexed", Chunk.embed_model == embedder.name)
    if not include_exams:
        q = q.where(Material.kind != "past_exam")
    if weeks:
        lo, hi = min(weeks) - 1, max(weeks)
        q = q.where((Chunk.week_no.is_(None)) | ((Chunk.week_no >= lo) & (Chunk.week_no <= hi)))
    rows = db.execute(q).all()
    if not rows:
        return []
    qv = embedder.embed([query])[0]
    hits = [Hit(c, cosine(qv, list(c.embedding)), mat) for c, mat in rows]
    hits.sort(key=lambda h: h.score, reverse=True)
    return [h for h in hits[:k] if h.score > 0.05]
