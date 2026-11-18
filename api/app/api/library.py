from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.libraries import resolve_library
from app.core import config
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
    library: str | None = None,
    session: Session = Depends(get_session),
):
    """Enqueue scan job(s) for one configured library or for all.

    `root` is kept for the legacy single-root call. `library` selects one
    configured library. With neither parameter, every configured library is
    scanned; database roots and LIBRARY_ROOTS are the legacy fallbacks.
    """
    if root and library:
        raise HTTPException(400, "Use either root or library, not both")

    targets = _resolve_scan_targets(root, library, session)
    if not targets:
        raise HTTPException(400, "No library roots configured. Add a root first.")

    job_ids: list[int] = []
    try:
        from arq import create_pool

        redis = await create_pool(
            __import__("arq.connections", fromlist=["RedisSettings"]).RedisSettings.from_dsn(
                config.settings.redis_url
            )
        )
        for scan_root, kind, library_id in targets:
            job_row = Job(
                type=JobType.scan,
                status=JobStatus.queued,
                params={"root": scan_root, "kind": kind, "library_id": library_id},
                created_at=datetime.now(UTC),
            )
            session.add(job_row)
            session.commit()
            session.refresh(job_row)
            await redis.enqueue_job(
                "run_scan", job_row.id, scan_root, kind, library_id
            )
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

        for scan_root, kind, library_id in targets:
            job_row = Job(
                type=JobType.scan,
                status=JobStatus.running,
                params={"root": scan_root, "kind": kind, "library_id": library_id},
                created_at=datetime.now(UTC),
                started_at=datetime.now(UTC),
            )
            session.add(job_row)
            session.commit()
            session.refresh(job_row)
            try:
                stats = scan_library(
                    Path(scan_root),
                    session,
                    kind=kind,
                    library_id=library_id,
                )
                job_row.status = JobStatus.done
                job_row.progress = 100
                job_row.finished_at = datetime.now(UTC)
                job_row.log = str(stats)
            except Exception as scan_exc:
                job_row.status = JobStatus.failed
                job_row.error = str(scan_exc)
            session.add(job_row)
            session.commit()
            job_ids.append(job_row.id)

    return {"job_ids": job_ids, "roots": [target[0] for target in targets]}


def _resolve_scan_targets(
    root: str | None,
    library: str | None,
    session: Session,
) -> list[tuple[str, str, str | None]]:
    if root:
        return [(root, "movies", None)]
    if library:
        selected = resolve_library(library)
        return [(selected.root, selected.type, selected.id)]

    if config.settings.libraries.strip():
        return [
            (lib.root, lib.type, lib.id)
            for lib in config.settings.configured_libraries
        ]

    db_roots = session.exec(select(LibraryRoot).where(LibraryRoot.enabled.is_(True))).all()
    if db_roots:
        return [(r.path, "movies", None) for r in db_roots]
    return [
        (lib.root, lib.type, lib.id)
        for lib in config.settings.configured_libraries
    ]
