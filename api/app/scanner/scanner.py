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
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import xxhash
from sqlmodel import Session, select

from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    LanguageSource,
    MediaKind,
    Movie,
    Series,
    SubSource,
    VideoFile,
)
from app.scanner.episode_parser import EpisodeMarker, parse_episode
from app.scanner.langdetect_op import detect_language
from app.scanner.probe import ProbeError, ProbeRunner, probe_file
from app.scanner.sub_name_parser import parse_subtitle_filename
from app.scanner.walker import (
    WalkedFile,
    WalkedMovie,
    WalkedSeries,
    walk_library,
    walk_series_library,
)

log = logging.getLogger(__name__)

ProgressCb = Callable[[int, int], None]

_HASH_CHUNK = 1024 * 1024  # 1 MB

_COMMON_VARIANTS = frozenset(
    {"ESP", "LAT", "EN", "ES", "ENG", "SPA", "VOSE", "VOSTFR", "MULTI"}
)


def _empty_stats() -> dict[str, int]:
    return {
        "movies": 0,
        "series": 0,
        "episodes": 0,
        "videos": 0,
        "subs": 0,
        "probe_errors": 0,
        "unmatched_subs": 0,
    }


def scan_library(
    root: Path,
    session: Session,
    probe_runner: ProbeRunner | None = None,
    progress: ProgressCb | None = None,
    kind: str = "movies",
    library_id: str | None = None,
) -> dict[str, Any]:
    """Scan `root`, upsert results into `session`, return summary stats."""
    if kind == "series":
        return _scan_series_library(
            root, session, probe_runner, progress, library_id
        )
    return _scan_movie_library(root, session, probe_runner, progress, library_id)


def _scan_movie_library(
    root: Path,
    session: Session,
    probe_runner: ProbeRunner | None,
    progress: ProgressCb | None,
    library_id: str | None,
) -> dict[str, Any]:
    walked = walk_library(root)
    total = len(walked)
    stats = _empty_stats()

    for i, wm in enumerate(walked, 1):
        try:
            _process_movie(wm, session, probe_runner, stats, library_id)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("scan: failed processing %s — skipping", wm.folder_path)
        if progress:
            progress(i, total)

    return stats


def _scan_series_library(
    root: Path,
    session: Session,
    probe_runner: ProbeRunner | None,
    progress: ProgressCb | None,
    library_id: str | None,
) -> dict[str, Any]:
    walked = walk_series_library(root)
    total = len(walked)
    stats = _empty_stats()

    for i, ws in enumerate(walked, 1):
        try:
            _process_series(ws, session, probe_runner, stats, library_id)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("scan: failed processing %s — skipping", ws.folder_path)
        if progress:
            progress(i, total)

    return stats


# ---- per-movie ----


def _process_movie(
    wm: WalkedMovie,
    session: Session,
    probe_runner: ProbeRunner | None,
    stats: dict,
    library_id: str | None,
) -> None:
    movie = _upsert_movie(wm, session, library_id)
    stats["movies"] += 1

    for wf in wm.videos:
        _upsert_video_file(wf, movie, session, probe_runner, stats)
        stats["videos"] += 1

    for ws in wm.subs:
        _upsert_external_sub(ws, movie, session)
        stats["subs"] += 1


def _upsert_movie(
    wm: WalkedMovie, session: Session, library_id: str | None
) -> Movie:
    stem = f"{wm.title} ({wm.year})" if wm.year else wm.title
    existing = session.exec(
        select(Movie).where(Movie.folder_path == str(wm.folder_path))
    ).first()
    if existing:
        existing.title = wm.title
        existing.year = wm.year
        existing.kind = MediaKind.movie
        existing.library_id = library_id
        existing.series_id = None
        existing.season_number = None
        existing.episode_number = None
        existing.episode_label = None
        existing.subtitle_dir = str(wm.folder_path)
        existing.subtitle_stem = stem
        existing.scanned_at = datetime.now(UTC)
        session.add(existing)
        return existing

    movie = Movie(
        folder_path=str(wm.folder_path),
        title=wm.title,
        year=wm.year,
        kind=MediaKind.movie,
        library_id=library_id,
        subtitle_dir=str(wm.folder_path),
        subtitle_stem=stem,
        scanned_at=datetime.now(UTC),
    )
    session.add(movie)
    session.flush()  # populates movie.id
    return movie


@dataclass
class _EpisodeGroup:
    season: int | None
    episode: int | None
    label: str
    folder_path: str
    subtitle_dir: str
    subtitle_stem: str
    rel_dir: str
    videos: list[WalkedFile] = field(default_factory=list)
    primary: WalkedFile | None = None
    movie: Movie | None = None


def _parent_names(rel_dir: str) -> list[str]:
    if not rel_dir:
        return []
    return list(reversed(Path(rel_dir).parts))


def _relative_path(path: Path, folder: Path) -> str:
    try:
        return path.relative_to(folder).as_posix()
    except ValueError:
        return path.name


def _episode_base_stem(filename: str) -> str:
    stem = Path(filename).stem
    match = re.search(r"\s+-\s+([A-Za-z0-9]{1,6})$", stem)
    if match:
        token = match.group(1)
        if token.isupper() or token.isdigit() or token.upper() in _COMMON_VARIANTS:
            return stem[: match.start()].rstrip()
    return stem


def _group_episodes(ws: WalkedSeries) -> list[_EpisodeGroup]:
    groups: dict[tuple, _EpisodeGroup] = {}
    for wf in ws.videos:
        marker: EpisodeMarker = parse_episode(
            wf.path.name, _parent_names(wf.rel_dir)
        )
        if marker.episode is None:
            key = ("u", wf.rel_dir, wf.path.name)
            groups[key] = _EpisodeGroup(
                season=None,
                episode=None,
                label=Path(wf.path.name).stem,
                folder_path=(
                    f"{ws.folder_path}#{_relative_path(wf.path, ws.folder_path)}"
                ),
                subtitle_dir=str(wf.path.parent),
                subtitle_stem=_episode_base_stem(wf.path.name),
                rel_dir=wf.rel_dir,
                videos=[wf],
                primary=wf,
            )
            continue

        season_key = marker.season if marker.season is not None else wf.rel_dir
        key = ("n", season_key, marker.episode)
        if key not in groups:
            if marker.season is None:
                folder_path = (
                    f"{ws.folder_path}#{wf.rel_dir}E{marker.episode:02d}"
                )
            else:
                folder_path = (
                    f"{ws.folder_path}#{wf.rel_dir}"
                    f"S{marker.season:02d}E{marker.episode:02d}"
                )
            groups[key] = _EpisodeGroup(
                season=marker.season,
                episode=marker.episode,
                label=marker.label or f"E{marker.episode:02d}",
                folder_path=folder_path,
                subtitle_dir=str(wf.path.parent),
                subtitle_stem=_episode_base_stem(wf.path.name),
                rel_dir=wf.rel_dir,
                videos=[wf],
                primary=wf,
            )
        else:
            groups[key].videos.append(wf)
    return list(groups.values())


def _process_series(
    ws: WalkedSeries,
    session: Session,
    probe_runner: ProbeRunner | None,
    stats: dict,
    library_id: str | None,
) -> None:
    series = _upsert_series(ws, session, library_id)
    stats["series"] += 1

    groups = _group_episodes(ws)
    for group in groups:
        movie = _upsert_episode(series, group, session, library_id)
        group.movie = movie
        stats["episodes"] += 1
        for wf in group.videos:
            _upsert_video_file(wf, movie, session, probe_runner, stats)
            stats["videos"] += 1

    _associate_series_subs(ws, groups, session, stats)


def _upsert_series(
    ws: WalkedSeries, session: Session, library_id: str | None
) -> Series:
    existing = session.exec(
        select(Series).where(Series.folder_path == str(ws.folder_path))
    ).first()
    if existing:
        existing.title = ws.title
        existing.year = ws.year
        if library_id is not None:
            existing.library_id = library_id
        existing.scanned_at = datetime.now(UTC)
        session.add(existing)
        return existing

    series = Series(
        library_id=library_id or "",
        folder_path=str(ws.folder_path),
        title=ws.title,
        year=ws.year,
        scanned_at=datetime.now(UTC),
    )
    session.add(series)
    session.flush()
    return series


def _upsert_episode(
    series: Series,
    group: _EpisodeGroup,
    session: Session,
    library_id: str | None,
) -> Movie:
    existing = session.exec(
        select(Movie).where(Movie.folder_path == group.folder_path)
    ).first()
    values = {
        "folder_path": group.folder_path,
        "title": series.title,
        "year": series.year,
        "kind": MediaKind.episode,
        "library_id": library_id if library_id is not None else series.library_id,
        "series_id": series.id,
        "season_number": group.season,
        "episode_number": group.episode,
        "episode_label": group.label,
        "subtitle_dir": group.subtitle_dir,
        "subtitle_stem": group.subtitle_stem,
        "scanned_at": datetime.now(UTC),
    }
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        session.add(existing)
        return existing

    movie = Movie(**values)
    session.add(movie)
    session.flush()
    return movie


def _associate_series_subs(
    ws: WalkedSeries,
    groups: list[_EpisodeGroup],
    session: Session,
    stats: dict,
) -> None:
    if not groups:
        stats["unmatched_subs"] += len(ws.subs)
        return

    video_stems = [
        (Path(video.path.name).stem, group)
        for group in groups
        for video in group.videos
    ]

    for walked_sub in ws.subs:
        sub_stem = Path(walked_sub.path.name).stem
        candidates: dict[int, _EpisodeGroup] = {}

        direct: list[tuple[int, _EpisodeGroup]] = []
        for video_stem, group in video_stems:
            if sub_stem == video_stem or (
                sub_stem.startswith(video_stem)
                and len(sub_stem) > len(video_stem)
                and sub_stem[len(video_stem)] in "._ -"
            ):
                direct.append((len(video_stem), group))
        if direct:
            longest = max(length for length, _ in direct)
            candidates = {
                id(group): group for length, group in direct if length == longest
            }

        if not candidates:
            marker = parse_episode(
                walked_sub.path.name, _parent_names(walked_sub.rel_dir)
            )
            if marker.episode is not None:
                candidates = {
                    id(group): group
                    for group in groups
                    if group.episode == marker.episode
                    and (marker.season is None or group.season == marker.season)
                }

        if not candidates:
            directory_groups = [
                group for group in groups if group.rel_dir == walked_sub.rel_dir
            ]
            if len(directory_groups) == 1:
                candidates = {id(directory_groups[0]): directory_groups[0]}

        if not candidates and len(groups) == 1:
            candidates = {id(groups[0]): groups[0]}

        if len(candidates) != 1:
            stats["unmatched_subs"] += 1
            log.debug(
                "series sub %s has no unique episode in %s",
                walked_sub.path,
                ws.folder_path,
            )
            continue

        group = next(iter(candidates.values()))
        if group.movie is None:
            stats["unmatched_subs"] += 1
            continue
        _upsert_external_sub(walked_sub, group.movie, session)
        stats["subs"] += 1


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
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC) if stat else None
    size = stat.st_size if stat else None
    file_hash = _hash_file(wf.real_path) if stat else None
    base_stem = movie.subtitle_stem or (
        f"{movie.title} ({movie.year})" if movie.year else movie.title
    )
    variant = _parse_variant(wf.path.name, base_stem)
    container = wf.path.suffix.lstrip(".").lower() or None

    if existing:
        vf = existing
        vf.movie_id = movie.id
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
    session: Session,
) -> ExternalSubtitle:
    real = str(ws.real_path)
    existing = session.exec(
        select(ExternalSubtitle).where(ExternalSubtitle.real_path == real)
    ).first()

    base_stem = movie.subtitle_stem or (
        f"{movie.title} ({movie.year})" if movie.year else movie.title
    )
    parsed = parse_subtitle_filename(ws.path.name, base_stem)
    rel_dir = _relative_dir(ws.path.parent, Path(movie.subtitle_dir or movie.folder_path))

    # Filename gave no language — fall back to reading the subtitle content.
    # Skip the re-read if a previous scan already resolved a language for
    # this file (content or filename), to avoid re-parsing on every rescan.
    language, language_source = parsed.language, parsed.language_source
    needs_detect = parsed.language is None and (existing is None or existing.language is None)
    if needs_detect:
        detected = detect_language(ws.real_path, parsed.format)
        if detected:
            language, language_source = detected, LanguageSource.content

    # Manual language overrides are sticky — don't overwrite them on rescan.
    if existing:
        sub = existing
        sub.movie_id = movie.id
        sub.path = str(ws.path)
        sub.is_symlink = ws.is_symlink
        sub.filename = ws.path.name
        sub.rel_dir = rel_dir
        sub.format = parsed.format
        sub.forced = parsed.forced
        sub.sdh = parsed.sdh
        sub.custom_tag = parsed.custom_tag
        if sub.language_source != LanguageSource.manual:
            sub.language = language
            sub.language_source = language_source
        session.add(sub)
        return sub

    sub = ExternalSubtitle(
        movie_id=movie.id,
        path=str(ws.path),
        real_path=real,
        is_symlink=ws.is_symlink,
        filename=ws.path.name,
        rel_dir=rel_dir,
        language=language,
        language_source=language_source,
        format=parsed.format,
        forced=parsed.forced,
        sdh=parsed.sdh,
        custom_tag=parsed.custom_tag,
        source=SubSource.preexisting,
        created_at=datetime.now(UTC),
    )
    session.add(sub)
    return sub


# ---- helpers ----


def _parse_variant(filename: str, base: str) -> str | None:
    """Extract variant suffix from filename: `<base> - VAR.ext` → 'VAR'."""
    stem = Path(filename).stem
    if stem.lower().startswith(base.lower()):
        suffix = stem[len(base):].strip()
        if suffix.startswith("- "):
            return suffix[2:].strip()
        if suffix.startswith("-"):
            return suffix[1:].strip()
    return None


def _relative_dir(directory: Path, base: Path) -> str:
    try:
        rel = directory.relative_to(base)
    except ValueError:
        return ""
    return "" if rel == Path(".") else rel.as_posix()


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
