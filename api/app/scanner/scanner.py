"""Main scanner: orchestrate walker + probe + sub_name_parser into DB upserts.

Design:
- Idempotent: running twice on the same folder produces the same rows
  (upsert by real_path, update mtime/hash).
- Error isolation: a probe failure on one file does NOT abort the whole
  scan; it logs a warning and continues.
- Progress: caller supplies an optional callback(done: int, total: int)
  that is invoked after each movie folder completes.
- Hash: xxh64 of first 1 MB + last 1 MB of real_path (fast, good enough
  for change detection on large video files).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import xxhash
from sqlmodel import Session, select

from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    LanguageSource,
    Movie,
    SubSource,
    VideoFile,
)
from app.scanner.probe import ProbeError, ProbeRunner, probe_file
from app.scanner.sub_name_parser import parse_subtitle_filename
from app.scanner.walker import WalkedFile, WalkedMovie, walk_library

log = logging.getLogger(__name__)

ProgressCb = Callable[[int, int], None]

_HASH_CHUNK = 1024 * 1024  # 1 MB


def scan_library(
    root: Path,
    session: Session,
    probe_runner: ProbeRunner | None = None,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Scan `root`, upsert results into `session`, return summary stats."""
    walked = walk_library(root)
    total = len(walked)
    stats = {"movies": 0, "videos": 0, "subs": 0, "probe_errors": 0}

    for i, wm in enumerate(walked, 1):
        try:
            _process_movie(wm, session, probe_runner, stats)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("scan: failed processing %s — skipping", wm.folder_path)
        if progress:
            progress(i, total)

    return stats


# ---- per-movie ----


def _process_movie(
    wm: WalkedMovie,
    session: Session,
    probe_runner: ProbeRunner | None,
    stats: dict,
) -> None:
    movie = _upsert_movie(wm, session)
    stats["movies"] += 1

    # Keep track of real_paths we see this scan to detect removed files.
    seen_video_real_paths: set[str] = set()
    seen_sub_real_paths: set[str] = set()

    for wf in wm.videos:
        _upsert_video_file(wf, movie, session, probe_runner, stats)
        seen_video_real_paths.add(str(wf.real_path))
        stats["videos"] += 1

    for ws in wm.subs:
        _upsert_external_sub(ws, movie, wm.title, session)
        seen_sub_real_paths.add(str(ws.real_path))
        stats["subs"] += 1


def _upsert_movie(wm: WalkedMovie, session: Session) -> Movie:
    existing = session.exec(
        select(Movie).where(Movie.folder_path == str(wm.folder_path))
    ).first()
    if existing:
        existing.title = wm.title
        existing.year = wm.year
        existing.scanned_at = datetime.now(timezone.utc)
        session.add(existing)
        return existing

    movie = Movie(
        folder_path=str(wm.folder_path),
        title=wm.title,
        year=wm.year,
        scanned_at=datetime.now(timezone.utc),
    )
    session.add(movie)
    session.flush()  # populates movie.id
    return movie


def _upsert_video_file(
    wf: WalkedFile,
    movie: Movie,
    session: Session,
    probe_runner: ProbeRunner | None,
    stats: dict,
) -> VideoFile:
    real = str(wf.real_path)
    existing = session.exec(
        select(VideoFile).where(VideoFile.real_path == real)
    ).first()

    stat = _safe_stat(wf.real_path)
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc) if stat else None
    size = stat.st_size if stat else None
    file_hash = _hash_file(wf.real_path) if stat else None
    variant = _parse_variant(wf.path.name, movie.title, movie.year)
    container = wf.path.suffix.lstrip(".").lower() or None

    if existing:
        vf = existing
        vf.path = str(wf.path)
        vf.is_symlink = wf.is_symlink
        vf.filename = wf.path.name
        vf.variant = variant
        vf.mtime = mtime
        vf.size = size
        vf.hash = file_hash
        vf.container = container
    else:
        vf = VideoFile(
            movie_id=movie.id,
            path=str(wf.path),
            real_path=real,
            is_symlink=wf.is_symlink,
            filename=wf.path.name,
            variant=variant,
            mtime=mtime,
            size=size,
            hash=file_hash,
            container=container,
        )

    # Probe for media info — do NOT abort on failure.
    try:
        probed = probe_file(wf.real_path, runner=probe_runner)
        vf.duration = probed.duration
        vf.video_codec = probed.video_codec
        vf.audio_tracks = [
            {
                "index": a.index,
                "codec": a.codec,
                "language": a.language,
                "channels": a.channels,
                "title": a.title,
            }
            for a in probed.audio
        ]
        # Sync embedded subtitle tracks.
        session.add(vf)
        session.flush()
        _sync_embedded_subs(probed.subtitles, vf, session)
    except (ProbeError, Exception) as exc:
        log.warning("probe failed for %s: %s", wf.real_path, exc)
        stats["probe_errors"] += 1
        session.add(vf)
        session.flush()

    return vf


def _sync_embedded_subs(
    probed_subs: list,
    vf: VideoFile,
    session: Session,
) -> None:
    """Replace EmbeddedSubtitle rows for this VideoFile with fresh probe data."""
    existing = session.exec(
        select(EmbeddedSubtitle).where(EmbeddedSubtitle.video_file_id == vf.id)
    ).all()
    for row in existing:
        session.delete(row)
    session.flush()

    for ps in probed_subs:
        session.add(
            EmbeddedSubtitle(
                video_file_id=vf.id,
                track_index=ps.index,
                codec=ps.codec,
                language=ps.language,
                title=ps.title,
                default=ps.default,
                forced=ps.forced,
            )
        )


def _upsert_external_sub(
    ws: WalkedFile,
    movie: Movie,
    movie_title: str,
    session: Session,
) -> ExternalSubtitle:
    real = str(ws.real_path)
    existing = session.exec(
        select(ExternalSubtitle).where(ExternalSubtitle.real_path == real)
    ).first()

    parsed = parse_subtitle_filename(ws.path.name, f"{movie_title} ({movie.year})")

    # Manual language overrides are sticky — don't overwrite them on rescan.
    if existing:
        sub = existing
        sub.path = str(ws.path)
        sub.is_symlink = ws.is_symlink
        sub.filename = ws.path.name
        sub.rel_dir = ws.rel_dir
        sub.format = parsed.format
        sub.forced = parsed.forced
        sub.sdh = parsed.sdh
        sub.custom_tag = parsed.custom_tag
        if sub.language_source != LanguageSource.manual:
            sub.language = parsed.language
            sub.language_source = parsed.language_source
        session.add(sub)
        return sub

    sub = ExternalSubtitle(
        movie_id=movie.id,
        path=str(ws.path),
        real_path=real,
        is_symlink=ws.is_symlink,
        filename=ws.path.name,
        rel_dir=ws.rel_dir,
        language=parsed.language,
        language_source=parsed.language_source,
        format=parsed.format,
        forced=parsed.forced,
        sdh=parsed.sdh,
        custom_tag=parsed.custom_tag,
        source=SubSource.preexisting,
        created_at=datetime.now(timezone.utc),
    )
    session.add(sub)
    return sub


# ---- helpers ----


def _parse_variant(filename: str, title: str, year: int | None) -> str | None:
    """Extract variant suffix from filename: `Title (Year) - VAR.ext` → 'VAR'."""
    stem = Path(filename).stem
    base = f"{title} ({year})" if year else title
    if stem.lower().startswith(base.lower()):
        suffix = stem[len(base):].strip()
        if suffix.startswith("- "):
            return suffix[2:].strip()
        if suffix.startswith("-"):
            return suffix[1:].strip()
    return None


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _hash_file(path: Path) -> str | None:
    """xxh64 of first + last MB. Returns None on any IO error."""
    try:
        size = path.stat().st_size
        h = xxhash.xxh64()
        with open(path, "rb") as f:
            h.update(f.read(_HASH_CHUNK))
            if size > _HASH_CHUNK * 2:
                f.seek(max(0, size - _HASH_CHUNK))
                h.update(f.read(_HASH_CHUNK))
        return h.hexdigest()
    except OSError:
        return None
