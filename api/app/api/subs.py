from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.policy import PolicyViolation, assert_can_delete_sub
from app.core.safe_fs import atomic_write, trash
from app.core.srt_validator import InvalidSRT, validate_srt_bytes
from app.models import ExternalSubtitle, Job, JobStatus, JobType, LanguageSource, Movie, SubSource
from app.scanner.langdetect_op import detect_language
from app.scanner.naming import canonical_sub_path, is_canonical
from app.schemas import ExternalSubRead, JobRead

log = logging.getLogger(__name__)
router = APIRouter()


# ---- list ----

@router.get("/subs/", response_model=list[ExternalSubRead])
def list_subs(
    movie_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    q = select(ExternalSubtitle)
    if movie_id is not None:
        q = q.where(ExternalSubtitle.movie_id == movie_id)
    return [ExternalSubRead.model_validate(s) for s in session.exec(q).all()]


# ---- upload ----

@router.post("/movies/{movie_id}/subs/upload", response_model=ExternalSubRead)
async def upload_sub(
    movie_id: int,
    file: UploadFile = File(...),
    language: str = Form(...),
    forced: bool = Form(False),
    sdh: bool = Form(False),
    custom_tag: str | None = Form(None),
    force_overwrite: bool = Form(False),
    session: Session = Depends(get_session),
):
    movie = session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")

    # Validate SRT content.
    data = await file.read()
    try:
        validate_srt_bytes(data)
    except InvalidSRT as exc:
        raise HTTPException(422, f"Invalid SRT: {exc}") from exc

    # Determine extension from uploaded filename (default srt).
    uploaded_name = file.filename or "upload.srt"
    ext = Path(uploaded_name).suffix.lstrip(".").lower() or "srt"

    # Build canonical target path.
    target_path = Path(
        canonical_sub_path(
            movie.folder_path, movie.title, movie.year, language,
            forced=forced, sdh=sdh, custom_tag=custom_tag, ext=ext,
        )
    )

    existing_db = session.exec(
        select(ExternalSubtitle).where(ExternalSubtitle.path == str(target_path))
    ).first()

    if target_path.exists() or existing_db:
        if not force_overwrite:
            raise HTTPException(
                409,
                f"{target_path.name} already exists. "
                "Set force_overwrite=true to replace (the old file will be trashed).",
            )
        # Trash the existing file first (safe_fs guarantees no raw delete).
        if target_path.exists():
            trash(target_path)
        if existing_db:
            session.delete(existing_db)
            session.flush()

    atomic_write(target_path, data)

    sub = ExternalSubtitle(
        movie_id=movie_id,
        path=str(target_path),
        real_path=str(target_path),
        is_symlink=False,
        filename=target_path.name,
        rel_dir="",
        language=language,
        language_source=LanguageSource.manual,
        format=ext,
        forced=forced,
        sdh=sdh,
        custom_tag=custom_tag,
        source=SubSource.manual,
        created_at=datetime.now(timezone.utc),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return ExternalSubRead.model_validate(sub)


# ---- delete ----

@router.delete("/subs/{sub_id}")
def delete_sub(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(ExternalSubtitle, sub_id)
    if not sub:
        raise HTTPException(404, "Subtitle not found")

    try:
        assert_can_delete_sub(sub)
    except PolicyViolation as exc:
        raise HTTPException(403, str(exc)) from exc

    sub_path = Path(sub.path)
    if sub_path.exists():
        trash(sub_path)

    session.delete(sub)
    session.commit()
    return {"ok": True, "trashed": sub_path.exists() is False}


# ---- patch (update metadata) ----

@router.patch("/subs/{sub_id}", response_model=ExternalSubRead)
def patch_sub(
    sub_id: int,
    language: str | None = None,
    forced: bool | None = None,
    sdh: bool | None = None,
    custom_tag: str | None = None,
    session: Session = Depends(get_session),
):
    sub = session.get(ExternalSubtitle, sub_id)
    if not sub:
        raise HTTPException(404, "Subtitle not found")

    if language is not None:
        sub.language = language
        sub.language_source = LanguageSource.manual
    if forced is not None:
        sub.forced = forced
    if sdh is not None:
        sub.sdh = sdh
    if custom_tag is not None:
        sub.custom_tag = custom_tag or None

    session.add(sub)
    session.commit()
    session.refresh(sub)
    return ExternalSubRead.model_validate(sub)


# ---- detect language from content ----

@router.post("/subs/{sub_id}/detect-language", response_model=ExternalSubRead)
def detect_sub_language(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(ExternalSubtitle, sub_id)
    if not sub:
        raise HTTPException(404, "Subtitle not found")

    sub_path = Path(sub.real_path)
    if not sub_path.exists():
        raise HTTPException(404, f"File not found on disk: {sub.real_path}")

    detected = detect_language(sub_path, sub.format)
    if not detected:
        raise HTTPException(422, "Could not detect language from the subtitle content.")

    sub.language = detected
    sub.language_source = LanguageSource.content
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return ExternalSubRead.model_validate(sub)


# ---- rename to canonical convention ----

@router.post("/subs/{sub_id}/rename", response_model=ExternalSubRead)
def rename_sub(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(ExternalSubtitle, sub_id)
    if not sub:
        raise HTTPException(404, "Subtitle not found")

    movie = session.get(Movie, sub.movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")

    if is_canonical(sub.filename, movie.title, movie.year):
        return ExternalSubRead.model_validate(sub)

    if sub.language is None:
        raise HTTPException(
            422,
            "Cannot rename: language is unknown. Set it via PATCH first.",
        )

    target_path = Path(
        canonical_sub_path(
            movie.folder_path, movie.title, movie.year, sub.language,
            forced=sub.forced, sdh=sub.sdh,
            custom_tag=sub.custom_tag, ext=sub.format,
        )
    )

    if target_path.exists() and target_path != Path(sub.path):
        raise HTTPException(
            409,
            f"Target {target_path.name} already exists. Delete or rename it first.",
        )

    src = Path(sub.path)
    if not src.exists():
        raise HTTPException(404, f"File not found on disk: {sub.path}")

    os.rename(src, target_path)

    sub.path = str(target_path)
    sub.real_path = str(target_path)
    sub.filename = target_path.name
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return ExternalSubRead.model_validate(sub)


# ---- translate ----

class TranslateRequest(BaseModel):
    target_language: str
    source_language: str | None = None


async def _enqueue_or_run_translate(job: Job, session: Session) -> None:
    from app.core.config import settings

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await redis.enqueue_job("run_translate", job.id)
        await redis.aclose()
    except Exception as exc_redis:
        log.warning("Redis unavailable (%s) — translating synchronously", exc_redis)
        try:
            from app.workers.translate import do_translate

            do_translate(job.id, session=session)
        except Exception as exc_sync:
            log.error("Sync translate failed: %s", exc_sync)
            # Job already marked failed in DB by do_translate; don't re-raise.


@router.post("/subs/{sub_id}/translate", response_model=JobRead)
async def translate_sub(
    sub_id: int,
    req: TranslateRequest,
    session: Session = Depends(get_session),
):
    """Translate an external subtitle to a new language using the configured LLM.

    Creates a Job (type=translate) and runs it. Returns the Job record.
    The translated file is saved next to the source with language=target_language
    and custom_tag='ai'.
    """
    sub = session.get(ExternalSubtitle, sub_id)
    if not sub:
        raise HTTPException(404, "Subtitle not found")

    if req.target_language == (sub.language or ""):
        raise HTTPException(422, "Target language is the same as the source language")

    job = Job(
        type=JobType.translate,
        status=JobStatus.queued,
        movie_id=sub.movie_id,
        target_id=sub_id,
        params={
            "sub_id": sub_id,
            "target_language": req.target_language,
            "source_language": req.source_language,
        },
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    await _enqueue_or_run_translate(job, session)
    session.refresh(job)
    return JobRead.model_validate(job)
