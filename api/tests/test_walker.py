"""Walker tests using a tmp tree that mirrors the user's actual library
structure: symlinks, multi-video folders (Superman ESP/LAT, Taxi Driver
EN/ES), `subs/` and `alt/` subfolders, junk files."""

from __future__ import annotations

import os
from pathlib import Path

from app.scanner.walker import (
    parse_folder_name,
    walk_library,
)

# ----- folder name parser -----


def test_parse_folder_name_simple():
    assert parse_folder_name("Stalker (1979)") == ("Stalker", 1979)


def test_parse_folder_name_with_punctuation():
    assert parse_folder_name("Scent of a Woman (1992)") == ("Scent of a Woman", 1992)


def test_parse_folder_name_recent():
    assert parse_folder_name("Sirat (2025)") == ("Sirat", 2025)


def test_parse_folder_name_invalid_returns_none():
    assert parse_folder_name("not a movie") is None
    assert parse_folder_name("Movie 1979") is None
    assert parse_folder_name("Movie (79)") is None


# ----- walking an empty / missing root -----


def test_walk_missing_root(tmp_path: Path):
    assert walk_library(tmp_path / "nope") == []


def test_walk_empty_root(library_root: Path):
    assert walk_library(library_root) == []


# ----- baseline: one folder, one video, one sub -----


def test_walk_basic_folder(library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    (folder / "Stalker (1979).mp4").write_bytes(b"x")
    (folder / "Stalker (1979).srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n")

    movies = walk_library(library_root)
    assert len(movies) == 1
    m = movies[0]
    assert m.title == "Stalker"
    assert m.year == 1979
    assert len(m.videos) == 1
    assert len(m.subs) == 1
    assert m.videos[0].path.name == "Stalker (1979).mp4"
    assert m.subs[0].rel_dir == ""


# ----- mirrors the user's tree -----


def test_walk_mirrors_user_library(library_root: Path):
    """Build the exact folders shown in the user's tree and verify the
    walker partitions them correctly."""
    # 1) Plain movie + symlinked video + symlinked sub (Stalker).
    raw_root = library_root.parent / "raw_targets"
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_video = raw_root / "Stalker.1979.mp4"
    raw_sub = raw_root / "Stalker.1979.srt"
    raw_video.write_bytes(b"video")
    raw_sub.write_text("sub")

    stalker = library_root / "Stalker (1979)"
    stalker.mkdir()
    os.symlink(raw_video, stalker / "Stalker (1979).mp4")
    os.symlink(raw_sub, stalker / "Stalker (1979).srt")

    # 2) Multiple subs, junk file (Shutter).
    shutter = library_root / "Shutter (2004)"
    shutter.mkdir()
    (shutter / "Shutter (2004).mp4").write_bytes(b"x")
    (shutter / "Shutter (2004).srt").write_text("x")
    (shutter / "Shutter (2004).spanish.ai.srt").write_text("x")
    (shutter / "www.YTS.MX.jpg").write_bytes(b"x")  # JUNK

    # 3) `subs/` and `alt/` subfolders (Suicide Club).
    suicide = library_root / "Suicide Club (2001)"
    suicide.mkdir()
    (suicide / "Suicide Club (2001).mp4").write_bytes(b"x")
    (suicide / "Suicide Club (2001).srt").write_text("x")
    (suicide / "Suicide Club (2001).spanish.ai.srt").write_text("x")
    (suicide / "alt").mkdir()
    (suicide / "alt" / "Suicide Club (2001).avi").write_bytes(b"x")
    (suicide / "subs").mkdir()
    (suicide / "subs" / "3_English.srt").write_text("x")
    (suicide / "subs" / "4_Chinese.srt").write_text("x")
    (suicide / "subs" / "Suicide Club (2001)_es_1.srt").write_text("x")
    (suicide / "subs" / "Suicide Club (2001)_es_2.srt").write_text("x")

    # 4) Multi-variant videos (Superman ESP/LAT).
    superman = library_root / "Superman (2025)"
    superman.mkdir()
    (superman / "Superman (2025) - ESP.mkv").write_bytes(b"x")
    (superman / "Superman (2025) - LAT.mkv").write_bytes(b"x")

    # 5) Mixed mp4 + mkv variants (Taxi Driver).
    taxi = library_root / "Taxi Driver (1976)"
    taxi.mkdir()
    (taxi / "Taxi Driver (1976) - EN.mp4").write_bytes(b"x")
    (taxi / "Taxi Driver (1976) - ES.mkv").write_bytes(b"x")
    (taxi / "Taxi Driver (1976).srt").write_text("x")
    (taxi / "Taxi Driver (1976).spanish.ai.srt").write_text("x")
    (taxi / "www.YTS.AM.jpg").write_bytes(b"x")  # JUNK

    # 6) Non-conforming folder name — must be skipped.
    bogus = library_root / "Random Stuff"
    bogus.mkdir()
    (bogus / "video.mp4").write_bytes(b"x")

    # ---- Assertions ----
    movies = {m.title: m for m in walk_library(library_root)}
    assert set(movies) == {
        "Stalker",
        "Shutter",
        "Suicide Club",
        "Superman",
        "Taxi Driver",
    }, "non-conforming folder must not appear"

    # Stalker — symlinks resolved
    s = movies["Stalker"]
    assert len(s.videos) == 1
    assert s.videos[0].is_symlink is True
    assert s.videos[0].real_path == raw_video
    assert s.subs[0].is_symlink is True
    assert s.subs[0].real_path == raw_sub

    # Shutter — junk filtered
    sh = movies["Shutter"]
    assert {p.path.name for p in sh.subs} == {
        "Shutter (2004).srt",
        "Shutter (2004).spanish.ai.srt",
    }
    assert all(not p.path.name.endswith(".jpg") for p in sh.videos + sh.subs)

    # Suicide Club — alt + subs picked up at depth 1
    sc = movies["Suicide Club"]
    video_names = {v.path.name for v in sc.videos}
    assert video_names == {
        "Suicide Club (2001).mp4",
        "Suicide Club (2001).avi",
    }
    # The avi from alt/ should carry rel_dir="alt"
    avi_record = next(v for v in sc.videos if v.path.name.endswith(".avi"))
    assert avi_record.rel_dir == "alt"
    sub_paths = {(s.rel_dir, s.path.name) for s in sc.subs}
    assert sub_paths == {
        ("", "Suicide Club (2001).srt"),
        ("", "Suicide Club (2001).spanish.ai.srt"),
        ("subs", "3_English.srt"),
        ("subs", "4_Chinese.srt"),
        ("subs", "Suicide Club (2001)_es_1.srt"),
        ("subs", "Suicide Club (2001)_es_2.srt"),
    }

    # Superman — both variants picked up
    sm = movies["Superman"]
    assert {v.path.name for v in sm.videos} == {
        "Superman (2025) - ESP.mkv",
        "Superman (2025) - LAT.mkv",
    }

    # Taxi Driver — mp4 + mkv variants
    td = movies["Taxi Driver"]
    assert {v.path.name for v in td.videos} == {
        "Taxi Driver (1976) - EN.mp4",
        "Taxi Driver (1976) - ES.mkv",
    }


# ----- depth limit -----


def test_depth_limit_respects_max(library_root: Path):
    folder = library_root / "Deep (2024)"
    deep = folder / "subs" / "deeper" / "deepest"
    deep.mkdir(parents=True)
    (folder / "Deep (2024).mkv").write_bytes(b"x")
    (folder / "subs" / "Deep.en.srt").write_text("x")  # depth 1, OK
    (folder / "subs" / "deeper" / "Deep.es.srt").write_text("x")  # depth 2, OK
    (deep / "Deep.zh.srt").write_text("x")  # depth 3, REJECTED

    movies = walk_library(library_root)
    assert len(movies) == 1
    sub_dirs = {s.rel_dir for s in movies[0].subs}
    assert "subs" in sub_dirs
    assert "subs/deeper" in sub_dirs
    assert "subs/deeper/deepest" not in sub_dirs


# ----- dotfiles & metadata folders -----


def test_dotfolders_skipped(library_root: Path):
    folder = library_root / "Dot (2024)"
    extras = folder / ".extras"
    extras.mkdir(parents=True)
    (folder / "Dot (2024).mkv").write_bytes(b"x")
    (extras / "Dot.bonus.srt").write_text("x")

    movies = walk_library(library_root)
    assert movies[0].subs == []


def test_dotfiles_skipped(library_root: Path):
    folder = library_root / "Dot (2024)"
    folder.mkdir()
    (folder / "Dot (2024).mkv").write_bytes(b"x")
    (folder / ".DS_Store").write_bytes(b"x")
    (folder / ".hidden.srt").write_text("x")

    movies = walk_library(library_root)
    assert movies[0].subs == []


# ----- ordering is stable for idempotent scans -----


def test_movie_order_alphabetical(library_root: Path):
    for name in ("Charlie (2024)", "Alpha (2024)", "Bravo (2024)"):
        (library_root / name).mkdir()
        (library_root / name / f"{name}.mkv").write_bytes(b"x")
    titles = [m.title for m in walk_library(library_root)]
    assert titles == ["Alpha", "Bravo", "Charlie"]


def test_files_order_within_movie(library_root: Path):
    folder = library_root / "Multi (2024)"
    folder.mkdir()
    for name in ("c.srt", "a.srt", "b.srt"):
        (folder / name).write_text("x")
    (folder / "Multi (2024).mkv").write_bytes(b"x")
    movie = walk_library(library_root)[0]
    assert [s.path.name for s in movie.subs] == ["a.srt", "b.srt", "c.srt"]
