"""Background jobs: a small database-backed queue (plan 0.1, 1.9, 2.7).

Extraction and generation can take tens of seconds (PDF parsing, model calls,
rate-limit back-off), so the API enqueues a Job and returns at once; the UI
polls GET /api/jobs/{id} for status and progress.

The queue lives in the database rather than Redis so it needs no extra
service, works on SQLite in development and Postgres in production, and keeps
the job history next to the data it changed. On Postgres, workers claim jobs
with SELECT … FOR UPDATE SKIP LOCKED, so several workers can run safely.

Handlers are registered with @handler("kind"). Each runs in its own session,
reports progress with ctx.progress(pct, message), and returns a JSON-able
result. A WorkflowError becomes a failed job with that error's message and
status, so the UI can show the same text the synchronous API used to.
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Faculty, Job, utcnow

log = logging.getLogger("eduforge.jobs")

_HANDLERS: dict[str, Callable[[Session, Job, JobContext], dict]] = {}
_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()
# Tests swap the session factory; production uses app.db.SessionLocal.
session_factory: Callable[[], Session] | None = None


class JobFailed(Exception):
    def __init__(self, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class JobContext:
    db: Session
    job: Job

    def progress(self, pct: int, message: str) -> None:
        self.job.progress = max(0, min(100, pct))
        self.job.message = message[:300]
        self.db.commit()  # visible to pollers straight away

    @property
    def faculty(self) -> Faculty:
        fac = self.db.get(Faculty, self.job.faculty_id)
        assert fac is not None, "a job always belongs to an existing faculty member"
        return fac


def handler(kind: str):
    def deco(fn):
        _HANDLERS[kind] = fn
        return fn
    return deco


def _sessions() -> Session:
    if session_factory is not None:
        return session_factory()
    from .db import SessionLocal
    return SessionLocal()


# --------------------------------------------------------------------------- #

def enqueue(db: Session, kind: str, faculty: Faculty, payload: dict) -> Job:
    """Create a job and start it according to WORKER_MODE. Commits."""
    if kind not in _HANDLERS:
        _load_handlers()
    job = Job(kind=kind, faculty_id=faculty.id, payload=payload, status="queued", message="Queued")
    db.add(job)
    db.commit()
    mode = get_settings().worker_mode
    if mode == "sync":
        run(job.id)
        db.refresh(job)
    elif mode == "inline":
        _executor().submit(run, job.id)
    # external: a worker process will claim it
    return job


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=max(1, get_settings().worker_threads),
                                       thread_name_prefix="eduforge-job")
        return _pool


def claim_next(db: Session) -> Job | None:
    """Atomically move one queued job to running. Safe with several workers."""
    q = select(Job.id).where(Job.status == "queued").order_by(Job.id).limit(1)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job_id = db.scalar(q)
    if job_id is None:
        db.rollback()
        return None
    res = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                     .values(status="running", started_at=utcnow(), attempts=Job.attempts + 1))
    db.commit()
    if getattr(res, "rowcount", 0) != 1:
        return None  # another worker got it first
    return db.get(Job, job_id)


def run(job_id: int) -> None:
    """Execute one job in its own session. Never raises."""
    _load_handlers()
    db = _sessions()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        if job.status == "queued":
            job.status, job.started_at, job.attempts = "running", utcnow(), (job.attempts or 0) + 1
            db.commit()
        ctx = JobContext(db, job)
        fn = _HANDLERS[job.kind]
        try:
            result = fn(db, job, ctx)
            job.status, job.result, job.progress, job.message = "done", result, 100, "Done"
        except Exception as e:  # noqa: BLE001 - every failure must land on the job
            db.rollback()
            failed = db.get(Job, job_id)
            assert failed is not None
            job = failed
            status = getattr(e, "status", 500)
            job.status, job.error, job.error_status = "failed", _message(e), status
            job.message = "Failed"
            if status >= 500:
                log.error("job %s (%s) failed:\n%s", job_id, job.kind, traceback.format_exc())
        job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()


def _message(e: Exception) -> str:
    detail = getattr(e, "detail", None)
    msg = str(e) or e.__class__.__name__
    if detail:
        items = "; ".join(str(d.get("message") or d.get("msg") or d) for d in detail)[:1500]
        msg = f"{msg} {items}"
    return msg[:4000]


_loaded = False


def _load_handlers() -> None:
    """Import the modules that register handlers (avoids import cycles)."""
    global _loaded
    if _loaded:
        return
    from . import job_handlers  # noqa: F401
    _loaded = True
