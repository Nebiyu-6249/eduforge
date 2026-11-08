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
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Faculty, Job, utcnow

log = logging.getLogger("eduforge.jobs")

# A job that has been "running" for longer than this was almost certainly cut
# off by a restart or a crash; nothing takes this long, so it is marked failed
# rather than left spinning forever in the activity panel.
STALE_AFTER_SECONDS = 20 * 60

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
        self.job.eta_seconds = _eta(self.db, self.job)
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

def enqueue(db: Session, kind: str, faculty: Faculty, payload: dict, *, title: str | None = None,
            course_version_id: int | None = None, link: str | None = None,
            size: int | None = None) -> Job:
    """Create a job and start it according to WORKER_MODE. Commits.

    `title`, `course_version_id` and `link` are what the activity panel shows
    and where it sends the teacher when the work is done; `size` is this job's
    own unit of work (questions, bytes, pages), used to guess how long it will
    take from past jobs of the same kind and size.
    """
    if kind not in _HANDLERS:
        _load_handlers()
    job = Job(kind=kind, faculty_id=faculty.id, payload=payload, status="queued", message="Queued",
              title=title, course_version_id=course_version_id, link=link, size=size)
    job.eta_seconds = _guess_from_history(db, job)
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


# ---- how long is left ----------------------------------------------------- #
#
# Two sources, in order of trust:
#   1. this run's own progress (elapsed / progress x remaining), once there is
#      enough of it to mean anything;
#   2. before that, the median wall time of past jobs of the same kind, scaled
#      by size where both are known.
# The answer is smoothed towards the previous one, so the panel never jumps
# about, and it is only ever shown rounded ("about 2 minutes left").

def _aware(t: datetime | None) -> datetime | None:
    """SQLite hands timestamps back without a time zone; they are all UTC."""
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


def _durations(db: Session, job: Job) -> list[float]:
    """Wall times of finished jobs of this kind, scaled to this job's size."""
    rows = db.execute(
        select(Job.size, Job.started_at, Job.finished_at)
        .where(Job.kind == job.kind, Job.status == "done",
               Job.started_at.is_not(None), Job.finished_at.is_not(None))
        .order_by(Job.id.desc()).limit(60)).all()
    out = []
    for size, started, finished in rows:
        if started is None or finished is None:
            continue
        secs = (_aware(finished) - _aware(started)).total_seconds()  # type: ignore[operator]
        if secs <= 0:
            continue
        # Scale by size where both are known, so "5 questions" can learn from
        # "10 questions" without pretending they take the same time.
        if job.size and size:
            secs = secs * job.size / size
        out.append(secs)
    return out


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def _guess_from_history(db: Session, job: Job) -> int | None:
    secs = _median(_durations(db, job))
    return int(secs) if secs else None


def _smooth(previous: int | None, now: float) -> int:
    """Move a third of the way towards the new estimate, and never upwards by
    much, so the number counts down instead of bouncing."""
    if previous is None:
        return max(1, int(now))
    if now > previous:
        now = min(now, previous + 15)
    return max(1, int(previous + (now - previous) / 3))


def _eta(db: Session, job: Job) -> int | None:
    pct = max(0, min(100, job.progress or 0))
    if pct >= 100:
        return 0
    if job.started_at is None:
        return job.eta_seconds
    elapsed = (utcnow() - _aware(job.started_at)).total_seconds()  # type: ignore[operator]
    # Under a twentieth of the way in, this run's own rate says very little.
    if pct >= 5 and elapsed >= 2:
        return _smooth(job.eta_seconds, elapsed / pct * (100 - pct))
    if job.eta_seconds is not None:
        return max(1, int(job.eta_seconds - elapsed))
    return _guess_from_history(db, job)


def _on_failed(db: Session, job: Job) -> None:
    """Let the thing a job was building know that it will not be finished."""
    from .models import AssessmentForm

    form = db.scalar(select(AssessmentForm).where(AssessmentForm.job_id == job.id))
    if form is None or form.status != "writing":
        return
    reason = job.error or "Something went wrong while writing this quiz. Try again."
    if form.items:
        # Some questions were written before it stopped. Throwing them away
        # would waste the teacher's wait, so the paper opens as a draft with
        # the reason on it.
        form.status = "draft"
    else:
        form.status = "failed"
    form.error = reason


RESTART_MESSAGES = {
    "create_quiz": "Something went wrong while writing this quiz. Try again.",
    "index_material": "Something went wrong while reading this file. Try again.",
    "extract": "Something went wrong while reading this syllabus. Upload it again.",
}


def recover_after_restart(db: Session) -> tuple[int, int]:
    """Inline mode runs jobs inside the web process, so after a restart (a free
    host going to sleep, a redeploy) nothing from before can still be running.
    Running jobs are marked failed with a plain reason, so no quiz stays
    "writing" forever; queued jobs are started again. Returns (failed, restarted)."""
    running = list(db.scalars(select(Job).where(Job.status == "running")))
    for job in running:
        job.status, job.message = "failed", "Stopped"
        job.error = job.error or RESTART_MESSAGES.get(job.kind, "Something went wrong. Try again.")
        job.error_status = job.error_status or 503
        job.finished_at, job.eta_seconds = utcnow(), 0
        _on_failed(db, job)
    db.commit()
    queued = list(db.scalars(select(Job.id).where(Job.status == "queued")))
    for job_id in queued:
        _executor().submit(run, job_id)
    return len(running), len(queued)


def sweep_stale(db: Session) -> int:
    """Fail jobs left running by a restart, so nothing spins forever."""
    cutoff = utcnow() - timedelta(seconds=STALE_AFTER_SECONDS)
    stale = list(db.scalars(select(Job).where(Job.status == "running", Job.started_at < cutoff)))
    for job in stale:
        job.status = "failed"
        job.message = "Stopped"
        job.error = job.error or "Something went wrong. Try again."
        job.finished_at = utcnow()
        job.eta_seconds = 0
        _on_failed(db, job)
    if stale:
        db.commit()
    return len(stale)


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
            _on_failed(db, job)
        job.finished_at = utcnow()
        job.eta_seconds = 0
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
