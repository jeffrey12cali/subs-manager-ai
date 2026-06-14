from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import get_session
from app.models import Job, JobStatus, JobType, LibraryRoot

router = APIRouter()


@router.get("/roots", response_model=list[LibraryRoot])
def list_roots(session: Session = Depends(get_session)):
    return session.exec(select(LibraryRoot)).all()


@router.post("/roots", response_model=LibraryRoot)
def add_root(root: LibraryRoot, session: Session = Depends(get_session)):
    session.add(root)
    session.commit()
    session.refresh(root)
    return root


@router.delete("/roots/{root_id}")
def delete_root(root_id: int, session: Session = Depends(get_session)):
    root = session.get(LibraryRoot, root_id)
    if not root:
        raise HTTPException(404)
    session.delete(root)
    session.commit()
    return {"ok": True}


@router.post("/scan")
async def trigger_scan(
    root: str | None = None,
    session: Session = Depends(get_session),
):
    """Enqueue scan job(s). If `root` is given, scans only that root;
    otherwise scans all enabled LibraryRoot rows (and falls back to
    LIBRARY_ROOTS from config if the table is empty).

    Returns a list of created Job IDs.
    """
    roots_to_scan = _resolve_roots(root, session)
    if not roots_to_scan:
        raise HTTPException(400, "No library roots configured. Add a root first.")

    job_ids: list[int] = []
    try:
        from arq import create_pool

        redis = await create_pool(
            __import__("arq.connections", fromlist=["RedisSettings"]).RedisSettings.from_dsn(
                settings.redis_url
            )
        )
        for r in roots_to_scan:
            job_row = Job(
                type=JobType.scan,
                status=JobStatus.queued,
                params={"root": r},
                created_at=datetime.now(timezone.utc),
            )
            session.add(job_row)
            session.commit()
            session.refresh(job_row)
            await redis.enqueue_job("run_scan", job_row.id, r)
            job_ids.append(job_row.id)
        await redis.aclose()
    except Exception as exc:
        # Redis not available (e.g. in tests or dev without worker).
        # Fall through with a synchronous scan in-process.
        import logging
        logging.getLogger(__name__).warning(
            "Redis unavailable (%s) — running scan synchronously", exc
        )
        from app.scanner.scanner import scan_library

        for r in roots_to_scan:
            job_row = Job(
                type=JobType.scan,
                status=JobStatus.running,
                params={"root": r},
                created_at=datetime.now(timezone.utc),
                started_at=datetime.now(timezone.utc),
            )
            session.add(job_row)
            session.commit()
            session.refresh(job_row)
            try:
                stats = scan_library(Path(r), session)
                job_row.status = JobStatus.done
                job_row.progress = 100
                job_row.finished_at = datetime.now(timezone.utc)
                job_row.log = str(stats)
            except Exception as scan_exc:
                job_row.status = JobStatus.failed
                job_row.error = str(scan_exc)
            session.add(job_row)
            session.commit()
            job_ids.append(job_row.id)

    return {"job_ids": job_ids, "roots": roots_to_scan}


def _resolve_roots(root: str | None, session: Session) -> list[str]:
    if root:
        return [root]
    db_roots = session.exec(select(LibraryRoot).where(LibraryRoot.enabled.is_(True))).all()
    if db_roots:
        return [r.path for r in db_roots]
    return settings.library_root_paths
