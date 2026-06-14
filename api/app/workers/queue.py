from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from arq.connections import RedisSettings
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import Job, JobStatus
from app.scanner.scanner import scan_library
from app.workers.mkv import run_embed, run_extract
from app.workers.transcribe import run_transcribe
from app.workers.translate import run_translate
from app.workers.translate_embedded import run_translate_embedded

log = logging.getLogger(__name__)


async def ping(ctx: dict) -> str:  # noqa: ARG001
    log.info("ping")
    return "pong"


async def run_scan(ctx: dict, job_id: int, root: str) -> dict:
    """ARQ task: run scanner for one library root, updating Job progress."""
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            log.error("run_scan: job %s not found", job_id)
            return {}

        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()

        def _progress(done: int, total: int) -> None:
            pct = int(done / total * 100) if total else 100
            with Session(engine) as inner:
                j = inner.get(Job, job_id)
                if j:
                    j.progress = pct
                    j.log += f"[{done}/{total}] scanned\n"
                    inner.add(j)
                    inner.commit()

        try:
            stats = scan_library(Path(root), session, progress=_progress)
            with Session(engine) as fin:
                j = fin.get(Job, job_id)
                if j:
                    j.status = JobStatus.done
                    j.progress = 100
                    j.finished_at = datetime.now(timezone.utc)
                    j.log += (
                        f"Done: {stats['movies']} movies, "
                        f"{stats['videos']} videos, "
                        f"{stats['subs']} subs, "
                        f"{stats['probe_errors']} probe errors\n"
                    )
                    fin.add(j)
                    fin.commit()
            return stats
        except Exception as exc:
            log.exception("run_scan failed for root %s", root)
            with Session(engine) as err:
                j = err.get(Job, job_id)
                if j:
                    j.status = JobStatus.failed
                    j.error = str(exc)
                    j.finished_at = datetime.now(timezone.utc)
                    err.add(j)
                    err.commit()
            raise


async def startup(ctx: dict) -> None:
    log.info("worker startup")


async def shutdown(ctx: dict) -> None:  # noqa: ARG001
    log.info("worker shutdown")


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    functions = [ping, run_scan, run_extract, run_embed, run_transcribe, run_translate, run_translate_embedded]
    redis_settings = _redis_settings()
    on_startup = startup
    on_shutdown = shutdown
