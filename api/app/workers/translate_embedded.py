"""Chain extract → translate for embedded subtitle tracks.

A single Job row covers both phases:
  0–50 %  extract (fast)
  50–100% translate (slow)

Re-embedding the translated sidecar into the MKV is left as a separate
manual action via POST /video-files/{id}/embed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pysrt
from sqlmodel import Session, select

from app.core.db import engine
from app.core.safe_fs import atomic_write
from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    Job,
    JobStatus,
    LanguageSource,
    Movie,
    SubSource,
    VideoFile,
)
from app.scanner.naming import canonical_sub_path
from app.workers.mkv import _CODEC_TO_EXT, extract_sub_track
from app.workers.translate import BATCH_SIZE, _NL, _default_translate, _translate_batch

log = logging.getLogger(__name__)

# Codecs that are text-based and can be parsed as SRT after extraction.
_TEXT_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "webvtt", "vtt"})


def do_translate_embedded(
    job_id: int,
    *,
    session: Session,
    runner=None,
    translate_fn: Callable | None = None,
) -> dict:
    """Extract an embedded track then translate the resulting SRT.

    Job params expected:
      video_file_id: int
      track_index: int
      target_language: str
      source_language: str | None
    """
    job = session.get(Job, job_id)
    if not job:
        raise RuntimeError(f"Job {job_id} not found")

    job.status = JobStatus.running
    job.started_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()

    try:
        params = job.params or {}
        vf_id: int = params["video_file_id"]
        track_index: int = params["track_index"]
        target_lang: str = params["target_language"]
        source_lang: str | None = params.get("source_language")

        vf = session.get(VideoFile, vf_id)
        if not vf:
            raise RuntimeError(f"VideoFile {vf_id} not found")

        movie = session.get(Movie, vf.movie_id)
        if not movie:
            raise RuntimeError(f"Movie {vf.movie_id} not found")

        embedded = session.exec(
            select(EmbeddedSubtitle)
            .where(EmbeddedSubtitle.video_file_id == vf_id)
            .where(EmbeddedSubtitle.track_index == track_index)
        ).first()
        if not embedded:
            raise RuntimeError(f"Embedded track {track_index} not found on vf {vf_id}")

        if embedded.codec not in _TEXT_CODECS:
            raise RuntimeError(
                f"Codec {embedded.codec!r} is not text-based — cannot translate directly"
            )

        # ---- phase 1: extract ----
        job.log += f"Extracting track {track_index} ({embedded.codec})…\n"
        job.progress = 5
        session.add(job)
        session.commit()

        ext = _CODEC_TO_EXT.get(embedded.codec, "srt")
        lang = embedded.language or "und"
        extract_path = Path(
            canonical_sub_path(
                movie.folder_path,
                movie.title,
                movie.year,
                lang,
                forced=embedded.forced,
                sdh=False,
                custom_tag="extracted",
                ext=ext,
            )
        )
        extract_path.parent.mkdir(parents=True, exist_ok=True)
        extract_sub_track(Path(vf.path), track_index, extract_path, runner=runner)

        # Upsert the extracted ExternalSubtitle row.
        existing_ext = session.exec(
            select(ExternalSubtitle).where(ExternalSubtitle.path == str(extract_path))
        ).first()
        if existing_ext:
            session.delete(existing_ext)
            session.flush()

        ext_sub = ExternalSubtitle(
            movie_id=movie.id,
            path=str(extract_path),
            real_path=str(extract_path),
            is_symlink=False,
            filename=extract_path.name,
            rel_dir="",
            language=embedded.language,
            language_source=LanguageSource.filename,
            format=ext,
            forced=embedded.forced,
            sdh=False,
            custom_tag="extracted",
            source=SubSource.extracted,
            linked_video_file_id=vf_id,
            created_at=datetime.now(timezone.utc),
        )
        session.add(ext_sub)
        session.flush()

        job.progress = 50
        job.log += f"Extracted → {extract_path.name}\n"
        session.add(job)
        session.commit()

        # ---- phase 2: translate ----
        from app.core.config import settings  # noqa: PLC0415

        if translate_fn is None and not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        fn = translate_fn or _default_translate

        srt_content = extract_path.read_text(encoding="utf-8", errors="replace")
        srt_subs = pysrt.from_string(srt_content)
        texts = [item.text for item in srt_subs]
        total = len(texts)

        if total == 0:
            raise RuntimeError("Extracted subtitle file is empty")

        translated: list[str] = []
        batches = [texts[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

        for batch_idx, batch in enumerate(batches):
            translated_batch = _translate_batch(
                batch,
                fn,
                target_lang,
                source_lang or embedded.language,
                api_key=settings.deepseek_api_key,
                base_url=settings.openai_base_url,
                model=settings.translate_model,
            )
            translated.extend(translated_batch)
            translate_pct = int((batch_idx + 1) / len(batches) * 50)
            job.progress = 50 + translate_pct
            job.log += f"[batch {batch_idx + 1}/{len(batches)}] {len(translated)}/{total} lines\n"
            session.add(job)
            session.commit()

        for item, new_text in zip(srt_subs, translated, strict=True):
            item.text = new_text
        out_srt = "\n".join(str(item) for item in srt_subs)

        out_path = Path(
            canonical_sub_path(
                movie.folder_path,
                movie.title,
                movie.year,
                target_lang,
                forced=embedded.forced,
                sdh=False,
                custom_tag="ai",
                ext="srt",
            )
        )
        atomic_write(out_path, out_srt.encode("utf-8"), replace=True)

        existing_trans = session.exec(
            select(ExternalSubtitle)
            .where(ExternalSubtitle.movie_id == movie.id)
            .where(ExternalSubtitle.source == SubSource.translated)
            .where(ExternalSubtitle.language == target_lang)
        ).first()
        if existing_trans:
            session.delete(existing_trans)
            session.flush()

        translated_sub = ExternalSubtitle(
            movie_id=movie.id,
            path=str(out_path),
            real_path=str(out_path),
            is_symlink=False,
            filename=out_path.name,
            rel_dir="",
            language=target_lang,
            language_source=LanguageSource.manual,
            format="srt",
            forced=embedded.forced,
            sdh=False,
            custom_tag="ai",
            source=SubSource.translated,
            linked_video_file_id=vf_id,
            created_at=datetime.now(timezone.utc),
        )
        session.add(translated_sub)

        job.status = JobStatus.done
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        job.log += f"Translated {total} lines → {out_path.name}\n"
        session.add(job)
        session.commit()
        session.refresh(translated_sub)
        return {"sub_id": translated_sub.id, "path": str(out_path), "language": target_lang}

    except Exception as exc:
        log.exception("do_translate_embedded failed for job %s", job_id)
        job.status = JobStatus.failed
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        raise


async def run_translate_embedded(ctx: dict, job_id: int) -> dict:  # noqa: ARG001
    with Session(engine) as session:
        return do_translate_embedded(job_id, session=session)
