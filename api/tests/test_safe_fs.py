import os
import time
from pathlib import Path

import pytest

from app.core import safe_fs
from app.core.safe_fs import (
    DestinationExistsError,
    PathEscapeError,
    ProtectedFileError,
    atomic_write,
    ensure_within,
    is_video,
    prune_backups,
    replace_with_backup,
    trash,
)

# ---------- ensure_within / is_video ----------


def test_ensure_within_accepts_library_path(tmp_data: Path, library_root: Path):
    p = library_root / "Foo (2024)" / "Foo.srt"
    p.parent.mkdir(parents=True)
    p.write_text("hi")
    ensure_within(p)


def test_ensure_within_accepts_data_dir(tmp_data: Path):
    p = tmp_data / "data" / "x.txt"
    p.write_text("hi")
    ensure_within(p)


def test_ensure_within_rejects_outside(tmp_data: Path, tmp_path: Path):
    outside = tmp_path / "elsewhere" / "evil.srt"
    outside.parent.mkdir(parents=True)
    outside.write_text("nope")
    with pytest.raises(PathEscapeError):
        ensure_within(outside)


def test_ensure_within_rejects_dotdot_escape(tmp_data: Path, library_root: Path):
    sneaky = library_root / ".." / "elsewhere.srt"
    with pytest.raises(PathEscapeError):
        ensure_within(sneaky)


def test_ensure_within_rejects_symlink_pointing_outside(
    tmp_data: Path, library_root: Path, tmp_path: Path
):
    target = tmp_path / "outside.srt"
    target.write_text("x")
    link = library_root / "link.srt"
    os.symlink(target, link)
    with pytest.raises(PathEscapeError):
        ensure_within(link)


def test_ensure_within_accepts_safe_fs_root_not_in_library_roots(
    tmp_data: Path, tmp_path: Path, monkeypatch
):
    """SAFE_FS_ROOTS extends the write allowlist without being a scan target."""
    extra = tmp_path / "raw"
    extra.mkdir()
    p = extra / "video.mkv.tmp"
    p.write_text("x")

    import app.core.config as config_mod

    monkeypatch.setenv("SAFE_FS_ROOTS", str(extra))
    config_mod.settings = config_mod.Settings()

    ensure_within(p)  # allowed via SAFE_FS_ROOTS
    assert str(extra) not in config_mod.settings.library_root_paths


def test_is_video_extensions():
    assert is_video("/x/foo.mkv")
    assert is_video("/x/foo.MP4")
    assert is_video("/x/foo.avi")
    assert not is_video("/x/foo.srt")
    assert not is_video("/x/foo.txt")


# ---------- atomic_write ----------


def test_atomic_write_creates_file(tmp_data: Path, library_root: Path):
    p = library_root / "Foo (2024)" / "Foo (2024).en.srt"
    atomic_write(p, b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
    assert p.exists()
    assert b"hi" in p.read_bytes()


def test_atomic_write_refuses_existing_without_replace(
    tmp_data: Path, library_root: Path
):
    p = library_root / "Foo (2024)" / "Foo (2024).en.srt"
    p.parent.mkdir(parents=True)
    p.write_text("old")
    with pytest.raises(DestinationExistsError):
        atomic_write(p, b"new")
    assert p.read_text() == "old"


def test_atomic_write_replace_overwrites(tmp_data: Path, library_root: Path):
    p = library_root / "Foo (2024)" / "Foo (2024).en.srt"
    p.parent.mkdir(parents=True)
    p.write_text("old")
    atomic_write(p, b"new", replace=True)
    assert p.read_bytes() == b"new"


def test_atomic_write_refuses_video(tmp_data: Path, library_root: Path):
    p = library_root / "Foo (2024)" / "Foo (2024).mkv"
    with pytest.raises(ProtectedFileError):
        atomic_write(p, b"FAKEMKV")


def test_atomic_write_rejects_outside(tmp_path: Path, tmp_data: Path):
    outside = tmp_path / "elsewhere.srt"
    with pytest.raises(PathEscapeError):
        atomic_write(outside, b"x")


def test_atomic_write_no_temp_files_left(tmp_data: Path, library_root: Path):
    p = library_root / "Foo (2024)" / "Foo (2024).en.srt"
    atomic_write(p, b"x")
    leftovers = list(p.parent.glob("*.tmp.*"))
    assert leftovers == []


def test_atomic_write_cleans_up_temp_file_on_failure(
    tmp_data: Path, library_root: Path, monkeypatch
):
    """If fsync (or any step before rename) fails, the temp file is removed
    and the target is never created/touched."""
    p = library_root / "Foo (2024)" / "Foo (2024).en.srt"

    def _boom_fsync(_fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(safe_fs.os, "fsync", _boom_fsync)

    with pytest.raises(OSError, match="simulated fsync failure"):
        atomic_write(p, b"x")

    assert not p.exists()
    assert list(p.parent.glob("*.tmp.*")) == []


# ---------- trash ----------


def test_trash_moves_file(tmp_data: Path, library_root: Path):
    p = library_root / "Foo (2024)" / "Foo (2024).en.srt"
    p.parent.mkdir(parents=True)
    p.write_text("payload")
    dest = trash(p)
    assert not p.exists()
    assert dest.exists()
    assert dest.read_text() == "payload"
    # trash dir lives under DATA_DIR
    assert dest.parent.name == "trash"


def test_trash_refuses_video(tmp_data: Path, library_root: Path):
    p = library_root / "Foo (2024)" / "Foo (2024).mkv"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"FAKEMKV")
    with pytest.raises(ProtectedFileError):
        trash(p)
    assert p.exists(), "video file must NOT be moved"


def test_trash_refuses_path_outside(tmp_path: Path, tmp_data: Path):
    outside = tmp_path / "elsewhere.srt"
    outside.write_text("x")
    with pytest.raises(PathEscapeError):
        trash(outside)


def test_trash_missing_file(tmp_data: Path, library_root: Path):
    p = library_root / "missing.srt"
    with pytest.raises(FileNotFoundError):
        trash(p)


# ---------- replace_with_backup ----------


def test_replace_with_backup_keeps_original(tmp_data: Path, library_root: Path):
    orig = library_root / "Foo (2024)" / "Foo (2024).mkv"
    orig.parent.mkdir(parents=True)
    orig.write_bytes(b"ORIGINAL_MKV")
    new = orig.parent / "Foo (2024).mkv.new"
    new.write_bytes(b"NEW_MKV")

    backup = replace_with_backup(orig, new)

    assert orig.read_bytes() == b"NEW_MKV"
    assert backup.exists()
    assert backup.read_bytes() == b"ORIGINAL_MKV"
    assert ".bak." in backup.name
    # candidate was consumed
    assert not new.exists()


def test_replace_with_backup_missing_target(tmp_data: Path, library_root: Path):
    orig = library_root / "Foo (2024)" / "Foo (2024).mkv"
    new = library_root / "Foo (2024)" / "new.mkv"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"new")
    with pytest.raises(FileNotFoundError):
        replace_with_backup(orig, new)


def test_replace_with_backup_missing_candidate(tmp_data: Path, library_root: Path):
    """new_path (the freshly-written candidate) doesn't exist → FileNotFoundError."""
    orig = library_root / "Foo (2024)" / "Foo (2024).mkv"
    orig.parent.mkdir(parents=True)
    orig.write_bytes(b"ORIGINAL_MKV")
    new = orig.parent / "Foo (2024).mkv.new"

    with pytest.raises(FileNotFoundError):
        replace_with_backup(orig, new)

    # original untouched, not yet renamed to a backup
    assert orig.exists()
    assert orig.read_bytes() == b"ORIGINAL_MKV"


def test_replace_with_backup_rolls_back_on_second_replace_failure(
    tmp_data: Path, library_root: Path, monkeypatch
):
    """If swapping the candidate into place fails, the original is restored."""
    orig = library_root / "Foo (2024)" / "Foo (2024).mkv"
    orig.parent.mkdir(parents=True)
    orig.write_bytes(b"ORIGINAL_MKV")
    new = orig.parent / "Foo (2024).mkv.new"
    new.write_bytes(b"NEW_MKV")

    real_replace = os.replace
    calls = {"n": 0}

    def _flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated failure swapping candidate into place")
        return real_replace(src, dst)

    monkeypatch.setattr(safe_fs.os, "replace", _flaky_replace)

    with pytest.raises(OSError, match="simulated failure"):
        replace_with_backup(orig, new)

    # rolled back: original content restored at its original path, no leftover backup
    assert orig.exists()
    assert orig.read_bytes() == b"ORIGINAL_MKV"


# ---------- prune_backups ----------


def test_prune_backups_removes_old_only(tmp_data: Path, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    fresh = folder / "Foo.mkv.bak.9999999999999"  # far future ms
    old = folder / "Foo.mkv.bak.1"  # epoch ms = 0.001s
    fresh.write_bytes(b"fresh")
    old.write_bytes(b"old")

    pruned = prune_backups(now=time.time())
    assert old in pruned
    assert fresh not in pruned
    assert not old.exists()
    assert fresh.exists()


def test_prune_ignores_unparsable_bak_names(tmp_data: Path, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    weird = folder / "Foo.mkv.bak.notanumber"
    weird.write_bytes(b"x")
    pruned = prune_backups(now=time.time())
    assert weird not in pruned
    assert weird.exists()


# ---------- belt-and-suspenders: video files survive every operation ----------


def test_video_files_never_destroyed_through_public_api(
    tmp_data: Path, library_root: Path
):
    """Smoke: every path that COULD touch a video should refuse."""
    video = library_root / "Foo (2024)" / "Foo (2024).mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"DO NOT TOUCH")

    with pytest.raises(ProtectedFileError):
        atomic_write(video, b"x", replace=True)
    with pytest.raises(ProtectedFileError):
        trash(video)

    assert video.exists()
    assert video.read_bytes() == b"DO NOT TOUCH"


# Suppress unused-import warning from safe_fs reference held for clarity.
_ = safe_fs


def test_atomic_write_survives_chmod_eperm(tmp_data: Path, library_root: Path, monkeypatch):
    """EPERM on chmod (SMB/NFS mounts) is ignored; file still reaches target."""
    import errno

    target = library_root / "Foo (2024)" / "Foo (2024).en.srt"
    target.parent.mkdir(parents=True)

    def _eperm_chmod(path, mode):  # noqa: ARG001
        raise PermissionError(errno.EPERM, "Operation not permitted", str(path))

    monkeypatch.setattr(os, "chmod", _eperm_chmod)
    result = atomic_write(target, b"content", replace=False)
    assert result == target
    assert target.read_bytes() == b"content"
