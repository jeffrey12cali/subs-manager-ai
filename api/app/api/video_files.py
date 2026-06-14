"""API endpoints for VideoFile-level operations: extract, embed, transcribe."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.db import get_session
from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    Job,
    JobStatus,
    JobType,
    VideoFile,
)

_TEXT_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "webvtt", "vtt"})
from app.schemas import JobRead

log = logging.getLogger(__name__)
router = APIRouter()


def _create_job(
    session: Session,
    job_type: JobType,
    movie_id: int,
    target_id: int,
    params: dict,
) -> Job:
    job = Job(
        type=job_type,
        status=JobStatus.queued,
        movie_id=movie_id,
        target_id=target_id,
        params=params,
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


async def _enqueue_or_run_extract(job: Job, session: Session, runner=None) -> None:
    from app.core.config import settings

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job("run_extract", job.id)
        await redis.aclose()
    except Exception as exc_redis:
        log.warning("Redis unavailable (%s) — extracting synchronously", exc_redis)
        try:
            from app.workers.mkv import do_extract

            do_extract(job.id, session=session, runner=runner)
        except Exception as exc_sync:
            log.error("Sync extract failed: %s", exc_sync)
            # Job already marked failed in DB by do_extract; don't re-raise.


async def _enqueue_or_run_embed(job: Job, session: Session, runner=None) -> None:
    from app.core.config import settings

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job("run_embed", job.id)
        await redis.aclose()
    except Exception as exc_redis:
        log.warning("Redis unavailable (%s) — embedding synchronously", exc_redis)
        try:
            from app.workers.mkv import do_embed

            do_embed(job.id, session=session, runner=runner)
        except Exception as exc_sync:
            log.error("Sync embed failed: %s", exc_sync)
            # Job already marked failed in DB by do_embed; don't re-raise.


# ---- extract ----

@router.post("/video-files/{vf_id}/extract/{track_index}", response_model=JobRead)
async def extract_track(
    vf_id: int,
    track_index: int,
    session: Session = Depends(get_session),
):
    """Extract one embedded subtitle track to a sidecar file.

    Creates a Job (type=extract) and runs it. Returns the Job record.
    Re-scan the library afterward to refresh embedded track counts.
    """
    vf = session.get(VideoFile, vf_id)
    if not vf:
        raise HTTPException(404, "VideoFile not found")
    if vf.container != "mkv":
        raise HTTPException(422, f"Not an MKV (container={vf.container})")

    embedded = session.exec(
        select(EmbeddedSubtitle)
        .where(EmbeddedSubtitle.video_file_id == vf_id)
        .where(EmbeddedSubtitle.track_index == track_index)
    ).first()
    if not embedded:
        raise HTTPException(404, f"Track {track_index} not found on video file {vf_id}")

    job = _create_job(
        session,
        JobType.extract,
        movie_id=vf.movie_id,
        target_id=vf_id,
        params={"video_file_id": vf_id, "track_index": track_index},
    )
    await _enqueue_or_run_extract(job, session)
    session.refresh(job)
    return JobRead.model_validate(job)


# ---- embed ----

class EmbedRequest(BaseModel):
    sub_id: int


@router.post("/video-files/{vf_id}/embed", response_model=JobRead)
async def embed_sub(
    vf_id: int,
    req: EmbedRequest,
    session: Session = Depends(get_session),
):
    """Embed an external subtitle file as a new track in an MKV.

    The original MKV is backed up as `<name>.bak.<ts>.mkv` and replaced
    atomically. Returns the Job record.
    """
    vf = session.get(VideoFile, vf_id)
    if not vf:
        raise HTTPException(404, "VideoFile not found")
    if vf.container != "mkv":
        raise HTTPException(422, f"Not an MKV (container={vf.container})")

    sub = session.get(ExternalSubtitle, req.sub_id)
    if not sub:
        raise HTTPException(404, "ExternalSubtitle not found")
    if sub.movie_id != vf.movie_id:
        raise HTTPException(422, "Sub belongs to a different movie")

    job = _create_job(
        session,
        JobType.embed,
        movie_id=vf.movie_id,
        target_id=vf_id,
        params={"video_file_id": vf_id, "sub_id": req.sub_id},
    )
    await _enqueue_or_run_embed(job, session)
    session.refresh(job)
    return JobRead.model_validate(job)


# ---- transcribe ----

async def _enqueue_or_run_transcribe(job: Job, session: Session) -> None:
    from app.core.config import settings

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job("run_transcribe", job.id)
        await redis.aclose()
    except Exception as exc_redis:
        log.warning("Redis unavailable (%s) — transcribing synchronously", exc_redis)
        try:
            from app.workers.transcribe import do_transcribe

            do_transcribe(job.id, session=session)
        except Exception as exc_sync:
            log.error("Sync transcribe failed: %s", exc_sync)
            # Job already marked failed in DB by do_transcribe; don't re-raise.


@router.post("/video-files/{vf_id}/transcribe", response_model=JobRead)
async def transcribe_video(
    vf_id: int,
    language: str | None = None,
    session: Session = Depends(get_session),
):
    """Transcribe a video file's audio with Whisper and save as a sidecar SRT.

    Optional `language` (BCP-47) skips auto-detection and is faster.
    Returns the Job record — check `status` and `log` for progress.
    """
    vf = session.get(VideoFile, vf_id)
    if not vf:
        raise HTTPException(404, "VideoFile not found")

    job = _create_job(
        session,
        JobType.transcribe,
        movie_id=vf.movie_id,
        target_id=vf_id,
        params={"video_file_id": vf_id, "language": language},
    )
    await _enqueue_or_run_transcribe(job, session)
    session.refresh(job)
    return JobRead.model_validate(job)


# ---- translate-embedded ----

class TranslateEmbeddedRequest(BaseModel):
    target_language: str
    source_language: str | None = None


async def _enqueue_or_run_translate_embedded(job: Job, session: Session) -> None:
    from app.core.config import settings

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job("run_translate_embedded", job.id)
        await redis.aclose()
    except Exception as exc_redis:
        log.warning("Redis unavailable (%s) — translate-embedded synchronously", exc_redis)
        try:
            from app.workers.translate_embedded import do_translate_embedded

            do_translate_embedded(job.id, session=session)
        except Exception as exc_sync:
            log.error("Sync translate-embedded failed: %s", exc_sync)


@router.post("/video-files/{vf_id}/translate-embedded/{track_index}", response_model=JobRead)
async def translate_embedded_track(
    vf_id: int,
    track_index: int,
    req: TranslateEmbeddedRequest,
    session: Session = Depends(get_session),
):
    """Extract an embedded subtitle track and translate it.

    Only text-based codecs (subrip, ass, ssa, webvtt) are supported.
    Returns the Job record.
    """
    vf = session.get(VideoFile, vf_id)
    if not vf:
        raise HTTPException(404, "VideoFile not found")

    embedded = session.exec(
        select(EmbeddedSubtitle)
        .where(EmbeddedSubtitle.video_file_id == vf_id)
        .where(EmbeddedSubtitle.track_index == track_index)
    ).first()
    if not embedded:
        raise HTTPException(404, f"Track {track_index} not found on video file {vf_id}")

    if embedded.codec not in _TEXT_CODECS:
        raise HTTPException(422, f"Codec {embedded.codec!r} is not text-based — cannot translate")

    job = _create_job(
        session,
        JobType.translate_embedded,
        movie_id=vf.movie_id,
        target_id=vf_id,
        params={
            "video_file_id": vf_id,
            "track_index": track_index,
            "target_language": req.target_language,
            "source_language": req.source_language,
        },
    )
    await _enqueue_or_run_translate_embedded(job, session)
    session.refresh(job)
    return JobRead.model_validate(job)
