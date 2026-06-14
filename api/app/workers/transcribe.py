"""Whisper transcription worker.

`_default_transcribe` is the real faster-whisper call and is injectable so
tests never load a model. `do_transcribe` contains all DB logic and is called
by both the ARQ task and the synchronous API fallback.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlmodel import Session, select

from app.core.db import engine
from app.core.safe_fs import atomic_write
from app.models import (
    ExternalSubtitle,
    Job,
    JobStatus,
    LanguageSource,
    Movie,
    SubSource,
    VideoFile,
)
from app.scanner.naming import canonical_sub_path

log = logging.getLogger(__name__)


class Segment(Protocol):
    start: float
    end: float
    text: str


def _fmt_ts(secs: float) -> str:
    total_ms = round(secs * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: Iterable[Any]) -> str:
    """Convert faster-whisper segment objects to SRT text."""
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_fmt_ts(seg.start)} --> {_fmt_ts(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


def _default_transcribe(
    video_path: Path,
    *,
    model_size: str,
    compute_type: str,
    vad: bool,
    language: str | None,
) -> tuple[Iterable[Any], str]:
    """Real faster-whisper call. Returns (segments_iterable, detected_language)."""
    from faster_whisper import WhisperModel  # noqa: PLC0415

    model = WhisperModel(model_size, compute_type=compute_type)
    segments, info = model.transcribe(
        str(video_path),
        vad_filter=vad,
        language=language or None,
    )
    return segments, info.language


def do_transcribe(
    job_id: int,
    *,
    session: Session,
    transcribe_fn: Callable | None = None,
) -> dict:
    """Core transcription logic — called by ARQ worker and sync fallback."""
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
        language: str | None = params.get("language")

        vf = session.get(VideoFile, vf_id)
        if not vf:
            raise RuntimeError(f"VideoFile {vf_id} not found")

        movie = session.get(Movie, vf.movie_id)
        if not movie:
            raise RuntimeError(f"Movie {vf.movie_id} not found")

        from app.core.config import settings  # noqa: PLC0415

        fn = transcribe_fn or _default_transcribe
        segments_gen, detected_lang = fn(
            Path(vf.path),
            model_size=settings.whisper_model,
            compute_type=settings.whisper_compute_type,
            vad=settings.whisper_vad,
            language=language,
        )

        # Collect segments; update progress every 5 percentage points.
        lang = language or detected_lang or "und"
        total_duration = vf.duration or 0.0
        collected: list[Any] = []
        last_pct = 0

        for seg in segments_gen:
            collected.append(seg)
            if total_duration > 0:
                pct = min(99, int(seg.end / total_duration * 100))
                if pct - last_pct >= 5:
                    job.progress = pct
                    job.log += f"[{seg.end:.1f}s / {total_duration:.1f}s]\n"
                    session.add(job)
                    session.commit()
                    last_pct = pct

        srt_text = segments_to_srt(collected)

        out_path = Path(
            canonical_sub_path(
                movie.folder_path,
                movie.title,
                movie.year,
                lang,
                forced=False,
                sdh=False,
                custom_tag="whisper",
                ext="srt",
            )
        )
        atomic_write(out_path, srt_text.encode("utf-8"), replace=True)

        # Replace any existing whisper sub for the same language.
        existing = session.exec(
            select(ExternalSubtitle)
            .where(ExternalSubtitle.movie_id == movie.id)
            .where(ExternalSubtitle.source == SubSource.whisper)
            .where(ExternalSubtitle.language == (lang if lang != "und" else None))
        ).first()
        if existing:
            session.delete(existing)
            session.flush()

        sub = ExternalSubtitle(
            movie_id=movie.id,
            path=str(out_path),
            real_path=str(out_path),
            is_symlink=False,
            filename=out_path.name,
            rel_dir="",
            language=lang if lang != "und" else None,
            language_source=LanguageSource.content,
            format="srt",
            forced=False,
            sdh=False,
            custom_tag="whisper",
            source=SubSource.whisper,
            linked_video_file_id=vf_id,
            created_at=datetime.now(timezone.utc),
        )
        session.add(sub)

        job.status = JobStatus.done
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        job.log += f"Transcribed → {out_path.name} (lang={lang})\n"
        session.add(job)
        session.commit()
        session.refresh(sub)
        return {"sub_id": sub.id, "path": str(out_path), "language": lang}

    except Exception as exc:
        log.exception("do_transcribe failed for job %s", job_id)
        job.status = JobStatus.failed
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        raise


async def run_transcribe(ctx: dict, job_id: int) -> dict:  # noqa: ARG001
    with Session(engine) as session:
        return do_transcribe(job_id, session=session)
