"""Walk a library root and return movie folders with their files.

Layout assumption (Jellyfin-style, per PLAN §A):
  <root>/<Title (Year)>/<video files at depth 0..2>
                       /<sub files at depth 0..2>

A movie folder is any direct subdirectory of a library root whose name
matches `<Title> (YYYY)`. Folders that don't match the pattern are
skipped — they may be Jellyfin metadata folders, .extras, etc.

Symlinks are resolved (`real_path` recorded) but the original path is
preserved too. The walker does NOT call ffprobe — see `probe.py`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.safe_fs import SUBTITLE_EXTS, VIDEO_EXTS

# Maximum recursion depth for finding videos/subs inside a movie folder.
# Depth 0 = direct children, 1 = `subs/`, 2 = `subs/sub/`. Two is enough for
# the patterns observed in the user's library (`subs/`, `alt/`).
MAX_INNER_DEPTH = 2

# Junk extensions/names we never care about. Posters, NFO, sample files, etc.
_JUNK_EXTS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".nfo", ".txt", ".db", ".ds_store"}
)

# Folder name `<Title> (YYYY)`. Year 1888 = first ever motion picture; cap
# generously into the future.
_FOLDER_RE = re.compile(r"^(?P<title>.+?) \((?P<year>(?:18|19|20|21)\d{2})\)$")


@dataclass(frozen=True)
class WalkedFile:
    """A discovered file inside a movie folder."""

    path: Path  # path as walked (may be a symlink)
    real_path: Path  # resolved (`os.path.realpath`)
    is_symlink: bool
    rel_dir: str  # "" for direct child, "subs", "alt", etc.


@dataclass
class WalkedMovie:
    folder_path: Path
    title: str
    year: int
    videos: list[WalkedFile] = field(default_factory=list)
    subs: list[WalkedFile] = field(default_factory=list)


def parse_folder_name(name: str) -> tuple[str, int] | None:
    """Returns (title, year) if `name` matches `<Title> (YYYY)`, else None."""
    m = _FOLDER_RE.match(name)
    if not m:
        return None
    return m.group("title"), int(m.group("year"))


def walk_library(root: Path) -> list[WalkedMovie]:
    """Top-level entrypoint: enumerate movie folders under `root`.

    Non-conforming folders are silently skipped. Files at the library
    root that aren't inside a movie folder are also skipped — Jellyfin
    libraries always foldered.
    """
    root = Path(root)
    if not root.exists() or not root.is_dir():
        return []

    movies: list[WalkedMovie] = []
    for entry in sorted(root.iterdir()):
        # Allow symlinks to directories (jellyfin libs sometimes use them
        # for organization), but don't follow non-directory entries.
        if not entry.is_dir():
            continue
        parsed = parse_folder_name(entry.name)
        if not parsed:
            continue
        title, year = parsed
        movies.append(_walk_movie_folder(entry, title, year))
    return movies


def _walk_movie_folder(folder: Path, title: str, year: int) -> WalkedMovie:
    movie = WalkedMovie(folder_path=folder, title=title, year=year)
    for path, rel_dir in _iter_inner_files(folder):
        ext = path.suffix.lower()
        if ext in _JUNK_EXTS or path.name.startswith("."):
            continue
        if ext in VIDEO_EXTS:
            movie.videos.append(_to_walked(path, rel_dir))
        elif ext in SUBTITLE_EXTS:
            movie.subs.append(_to_walked(path, rel_dir))
        # Anything else (e.g. unfamiliar formats) is ignored.
    # Stable ordering helps idempotency tests.
    movie.videos.sort(key=lambda w: w.path.name)
    movie.subs.sort(key=lambda w: (w.rel_dir, w.path.name))
    return movie


def _iter_inner_files(folder: Path):
    """Yield (path, rel_dir) for every regular file at depth ≤ MAX_INNER_DEPTH.

    rel_dir is the slash-separated subdirectory name relative to the movie
    folder, or "" for direct children. This matches what we store in
    ExternalSubtitle.rel_dir.
    """
    for current, dirs, files in os.walk(folder, followlinks=False):
        rel = Path(current).relative_to(folder)
        depth = 0 if rel == Path(".") else len(rel.parts)
        if depth > MAX_INNER_DEPTH:
            # Don't descend further.
            dirs.clear()
            continue
        # Skip dot-folders (e.g. .extras).
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_dir = "" if rel == Path(".") else rel.as_posix()
        for fname in files:
            yield Path(current) / fname, rel_dir


def _to_walked(path: Path, rel_dir: str) -> WalkedFile:
    is_link = path.is_symlink()
    real = Path(os.path.realpath(path)) if is_link else path
    return WalkedFile(path=path, real_path=real, is_symlink=is_link, rel_dir=rel_dir)
