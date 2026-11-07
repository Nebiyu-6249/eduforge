"""Job worker process (WORKER_MODE=external): `python -m app.worker`.

Claims queued jobs one at a time and runs them. Start several for more
throughput; on Postgres they never take the same job (SKIP LOCKED).
On start, jobs left 'running' by a crashed worker are put back in the queue.
"""

from __future__ import annotations

import logging
import signal
import time

from sqlalchemy import update

from .db import SessionLocal
from .jobs import claim_next, run
from .models import Job

log = logging.getLogger("eduforge.worker")
_stop = False


def _requeue_stale() -> None:
    db = SessionLocal()
    try:
        res = db.execute(update(Job).where(Job.status == "running").values(status="queued"))
        n = getattr(res, "rowcount", 0)
        db.commit()
        if n:
            log.warning("re-queued %d job(s) left running by a previous worker", n)
    finally:
        db.close()


def main(poll_seconds: float = 1.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    def stop(*_):
        global _stop
        _stop = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    _requeue_stale()
    log.info("worker started")
    while not _stop:
        db = SessionLocal()
        try:
            job = claim_next(db)
        finally:
            db.close()
        if job is None:
            time.sleep(poll_seconds)
            continue
        log.info("running job %s (%s)", job.id, job.kind)
        run(job.id)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
