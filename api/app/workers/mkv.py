"""MKV extract/embed worker functions.

`extract_sub_track` and `embed_sub_track` are pure functions with injectable
`runner` for testing (avoids real subprocess calls in tests).

`do_extract` / `do_embed` contain the DB logic; they are called both by
the ARQ tasks and by the synchronous fallback path in the API.
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.core.safe_fs import ensure_within, replace_with_backup
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

log = logging.getLogger(__name__)

# mkvextract codec → file extension
_CODEC_TO_EXT: dict[str, str] = {
    "subrip": "srt",
    "srt": "srt",
    "ass": "ass",
    "ssa": "ass",
    "webvtt": "vtt",
    "vtt": "vtt",
    "pgs": "sup",
    "hdmv_pgs_subtitle": "sup",
    "dvd_subtitle": "sub",
    "vobsub": "sub",
}


def _run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def extract_sub_track(
    video_path: Path,
    track_index: int,
    out_path: Path,
    runner=None,
) -> None:
    """Call mkvextract to pull one subtitle track to out_path."""
    if runner is None:
        runner = _run
    cmd = ["mkvextract", "tracks", str(video_path), f"{track_index}:{out_path}"]
    rc, stdout, stderr = runner(cmd)
    if rc != 0:
        raise RuntimeError(f"mkvextract failed (rc={rc}): {stderr or stdout}")


def embed_sub_track(
    video_path: Path,
    sub_path: Path,
    out_path: Path,
    language: str | None,
    forced: bool,
    runner=None,
) -> None:
    """Call mkvmerge to add a subtitle track into an MKV, writing to out_path.

    mkvmerge exit codes: 0 = success, 1 = success with warnings, 2+ = error.
    """
    if runner is None:
        runner = _run
    cmd = ["mkvmerge", "-o", str(out_path), str(video_path)]
    if language:
        cmd += ["--language", f"0:{language}"]
    if forced:
        cmd += ["--forced-track", "0:yes"]
    cmd.append(str(sub_path))
    rc, stdout, stderr = runner(cmd)
    if rc >= 2:
        raise RuntimeError(f"mkvmerge failed (rc={rc}): {stderr or stdout}")


def do_extract(job_id: int, *, session: Session, runner=None) -> dict:
    """Core extract logic — called by ARQ worker and the sync fallback."""
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

        ext = _CODEC_TO_EXT.get(embedded.codec, "srt")
        lang = embedded.language or "und"
        out_path = Path(
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
        out_path.parent.mkdir(parents=True, exist_ok=True)

        extract_sub_track(Path(vf.path), track_index, out_path, runner=runner)

        sub = ExternalSubtitle(
            movie_id=movie.id,
            path=str(out_path),
            real_path=str(out_path),
            is_symlink=False,
            filename=out_path.name,
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
        session.add(sub)

        job.status = JobStatus.done
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        job.log += f"Extracted track {track_index} → {out_path.name}\n"
        session.add(job)
        session.commit()
        session.refresh(sub)
        return {"sub_id": sub.id, "path": str(out_path)}

    except Exception as exc:
        log.exception("do_extract failed for job %s", job_id)
        job.status = JobStatus.failed
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        raise


def do_embed(job_id: int, *, session: Session, runner=None) -> dict:
    """Core embed logic — called by ARQ worker and the sync fallback."""
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
        sub_id: int = params["sub_id"]

        vf = session.get(VideoFile, vf_id)
        if not vf:
            raise RuntimeError(f"VideoFile {vf_id} not found")

        sub = session.get(ExternalSubtitle, sub_id)
        if not sub:
            raise RuntimeError(f"ExternalSubtitle {sub_id} not found")

        if vf.container != "mkv":
            raise RuntimeError(f"VideoFile {vf_id} is not MKV (container={vf.container})")

        video_path = Path(vf.path)
        sub_path = Path(sub.path)
        ensure_within(video_path)
        ensure_within(sub_path)

        out_path = video_path.with_name(
            f"{video_path.stem}.new.{int(time.time() * 1000)}.mkv"
        )
        embed_sub_track(
            video_path,
            sub_path,
            out_path,
            language=sub.language,
            forced=sub.forced,
            runner=runner,
        )
        backup = replace_with_backup(video_path, out_path)

        job.status = JobStatus.done
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        job.log += (
            f"Embedded {sub_path.name} into {video_path.name}; "
            f"backup: {backup.name}\n"
        )
        session.add(job)
        session.commit()
        return {"backup": str(backup)}

    except Exception as exc:
        log.exception("do_embed failed for job %s", job_id)
        job.status = JobStatus.failed
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        raise


# ---- ARQ tasks ----

async def run_extract(ctx: dict, job_id: int) -> dict:  # noqa: ARG001
    with Session(engine) as session:
        return do_extract(job_id, session=session)


async def run_embed(ctx: dict, job_id: int) -> dict:  # noqa: ARG001
    with Session(engine) as session:
        return do_embed(job_id, session=session)
