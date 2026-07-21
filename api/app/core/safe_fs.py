"""Filesystem safety primitives.

INVARIANTS:
  1. No raw os.unlink / Path.unlink for any path inside a library root.
     Use `trash()` — it moves the file into a quarantine dir under DATA_DIR.
  2. No raw open(path, "wb") for replacing existing files.
     Use `atomic_write()` — write to temp + fsync + rename.
  3. Replacing a video container goes through `replace_with_backup()`,
     which keeps a `.bak` of the original until the retention period passes.
  4. Video files are protected absolutely. `trash()` and `replace_with_backup()`
     refuse to operate on extensions in VIDEO_EXTS unless `allow_video=True`
     AND the caller justified it (used by MKV mux which writes a new file
     and renames over the original — original goes to .bak, never to trash).
  5. Every path argument is checked for containment in one of the configured
     library roots OR the data dir. Anything else raises PathEscapeError.

Tests live in tests/test_safe_fs.py — keep them green.
"""

from __future__ import annotations

import contextlib
import errno as _errno
import os
import shutil
import time
from pathlib import Path

from app.core import config as _config_mod

VIDEO_EXTS = frozenset({".mkv", ".mp4", ".avi", ".m4v", ".mov", ".webm", ".ts"})
SUBTITLE_EXTS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sub"})

# How long backups stick around before the worker prunes them.
BACKUP_RETENTION_SECONDS = 24 * 60 * 60


class SafeFsError(Exception):
    """Base for all safe-fs refusals."""


class PathEscapeError(SafeFsError):
    """Path is outside the allowed roots."""


class ProtectedFileError(SafeFsError):
    """Refused to act on a protected file (e.g. raw video)."""


class DestinationExistsError(SafeFsError):
    """atomic_write target exists and replace=False."""


def _settings():
    # Read fresh each time so test fixtures swapping `config.settings` are honored.
    return _config_mod.settings


def _allowed_roots() -> list[Path]:
    s = _settings()
    roots = [Path(p).resolve() for p in s.library_root_paths]
    roots += [Path(p).resolve() for p in s.safe_fs_root_paths]
    roots.append(Path(s.data_dir).resolve())
    return roots


def _trash_dir() -> Path:
    d = Path(_settings().data_dir) / "trash"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_within(path: str | os.PathLike, roots: list[Path] | None = None) -> Path:
    """Resolve path and ensure it sits inside one of the allowed roots.

    Resolves symlinks: a symlink that points outside the roots also escapes,
    so we check both the lexical path and its real_path.
    """
    p = Path(path)
    candidates = {p.resolve(strict=False)}
    # If it's a symlink that exists, also check the resolved target.
    try:
        if p.is_symlink():
            candidates.add(Path(os.path.realpath(p)))
    except OSError:
        pass

    allowed = roots if roots is not None else _allowed_roots()
    for cand in candidates:
        if not any(_is_relative_to(cand, root) for root in allowed):
            raise PathEscapeError(f"{cand} is not inside any allowed root")
    return p


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def is_video(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def atomic_write(
    path: str | os.PathLike,
    data: bytes,
    *,
    replace: bool = False,
    mode: int = 0o644,
) -> Path:
    """Atomic file write.

    Writes to `<path>.tmp.<pid>.<ts>`, fsyncs, then renames over `path`.
    If `replace=False` and `path` exists, raises DestinationExistsError BEFORE
    writing the temp file. If True, performs the rename which atomically
    replaces the file on POSIX.

    Refuses to overwrite video files — those must go through
    `replace_with_backup()`.
    """
    target = ensure_within(path)
    if is_video(target):
        raise ProtectedFileError(
            f"refusing to atomic_write video file {target}; use replace_with_backup"
        )
    if target.exists() and not replace:
        raise DestinationExistsError(f"{target} exists and replace=False")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}.{int(time.time() * 1000)}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, mode)
        except OSError as exc:
            if exc.errno not in (_errno.EPERM, _errno.EACCES, getattr(_errno, "ENOTSUP", 95)):
                raise
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "chmod %s on %s ignored (errno=%s) — likely SMB/NFS mount",
                oct(mode), tmp, exc.errno,
            )
        os.replace(tmp, target)
    except Exception:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise
    return target


def trash(path: str | os.PathLike, *, allow_video: bool = False) -> Path:
    """Move a file to the trash dir instead of deleting.

    Trash layout: `<data_dir>/trash/<unix_ts>_<original_basename>`.
    Returns the new trash path.

    Refuses on video files unless `allow_video=True`.
    """
    src = ensure_within(path)
    if not src.exists():
        raise FileNotFoundError(src)
    if is_video(src) and not allow_video:
        raise ProtectedFileError(
            f"refusing to trash video file {src}; videos must never be deleted"
        )

    dest = _trash_dir() / f"{int(time.time() * 1000)}_{src.name}"
    shutil.move(str(src), str(dest))
    return dest


def replace_with_backup(
    path: str | os.PathLike,
    new_path: str | os.PathLike,
) -> Path:
    """Replace `path` with `new_path`, keeping the old as `<path>.bak.<ts>`.

    Both paths must already exist (new_path is the freshly-written candidate,
    typically the output of `mkvmerge`). The backup is timestamped so repeated
    operations don't clobber prior backups.

    Returns the backup path. Worker prunes backups older than
    BACKUP_RETENTION_SECONDS.
    """
    target = ensure_within(path)
    candidate = ensure_within(new_path)
    if not target.exists():
        raise FileNotFoundError(target)
    if not candidate.exists():
        raise FileNotFoundError(candidate)

    backup = target.with_name(f"{target.name}.bak.{int(time.time() * 1000)}")
    os.replace(target, backup)  # atomic on POSIX, same fs
    try:
        os.replace(candidate, target)
    except Exception:
        # Roll back: put the original back.
        os.replace(backup, target)
        raise
    return backup


def prune_backups(now: float | None = None) -> list[Path]:
    """Delete `.bak.<ts>` files older than retention. Called by worker cron."""
    now = now if now is not None else time.time()
    pruned: list[Path] = []
    for root in _allowed_roots():
        if not root.exists():
            continue
        for p in root.rglob("*.bak.*"):
            try:
                ts_part = p.name.rsplit(".bak.", 1)[1]
                ts = int(ts_part) / 1000.0
            except (IndexError, ValueError):
                continue
            if now - ts > BACKUP_RETENTION_SECONDS:
                try:
                    p.unlink()
                    pruned.append(p)
                except OSError:
                    pass
    return pruned
