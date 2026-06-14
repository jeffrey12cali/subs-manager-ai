"""End-to-end scanner tests with a fake library tree and injected probe runner."""
from __future__ import annotations

from pathlib import Path

from sqlmodel import select

from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    LanguageSource,
    Movie,
    SubSource,
    VideoFile,
)
from app.scanner.scanner import scan_library


def _probe_noop(_path: Path) -> dict:
    """Probe runner that returns an empty but valid JSON-ish response dict."""
    return {"format": {"duration": "3600"}, "streams": []}


def _probe_with_embedded_subs(_path: Path) -> dict:
    return {
        "format": {"duration": "5400"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "index": 0},
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "index": 1,
                "tags": {"language": "eng", "title": "English"},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "codec_type": "subtitle",
                "codec_name": "hdmv_pgs_subtitle",
                "index": 2,
                "tags": {"language": "spa"},
                "disposition": {"default": 0, "forced": 1},
            },
        ],
    }


# ---------- basic scan ----------


def test_scan_creates_movie_and_video(
    session, library_root: Path, make_movie_folder
):
    make_movie_folder("Stalker (1979)", [("Stalker (1979).mp4", b"x")])
    stats = scan_library(library_root, session, probe_runner=_probe_noop)

    assert stats["movies"] == 1
    assert stats["videos"] == 1
    movies = session.exec(select(Movie)).all()
    assert len(movies) == 1
    assert movies[0].title == "Stalker"
    assert movies[0].year == 1979


def test_scan_external_subs_parsed(session, library_root: Path, make_movie_folder):
    make_movie_folder(
        "Shutter (2004)",
        [
            ("Shutter (2004).mp4", b"x"),
            ("Shutter (2004).srt", b"1\n00:00:01,000 --> 00:00:02,000\nHi\n"),
            ("Shutter (2004).spanish.ai.srt", b"1\n00:00:01,000 --> 00:00:02,000\nHola\n"),
        ],
    )
    scan_library(library_root, session, probe_runner=_probe_noop)

    subs = session.exec(select(ExternalSubtitle)).all()
    by_name = {s.filename: s for s in subs}
    assert "Shutter (2004).srt" in by_name
    assert "Shutter (2004).spanish.ai.srt" in by_name

    spanish = by_name["Shutter (2004).spanish.ai.srt"]
    assert spanish.language == "es"
    assert spanish.custom_tag == "ai"
    assert spanish.source == SubSource.preexisting


def test_scan_subs_subfolder(session, library_root: Path, make_movie_folder):
    make_movie_folder(
        "Suicide Club (2001)",
        [
            ("Suicide Club (2001).mp4", b"x"),
            ("subs/3_English.srt", b"x"),
            ("subs/Suicide Club (2001)_es_1.srt", b"x"),
        ],
    )
    scan_library(library_root, session, probe_runner=_probe_noop)

    subs = session.exec(select(ExternalSubtitle)).all()
    by_name = {s.filename: s for s in subs}

    eng = by_name["3_English.srt"]
    assert eng.language == "en"
    assert eng.rel_dir == "subs"

    es1 = by_name["Suicide Club (2001)_es_1.srt"]
    assert es1.language == "es"
    assert es1.custom_tag == "alt-1"


# ---------- multi-variant folder ----------


def test_scan_multi_variant_videos(session, library_root: Path, make_movie_folder):
    make_movie_folder(
        "Superman (2025)",
        [
            ("Superman (2025) - ESP.mkv", b"x"),
            ("Superman (2025) - LAT.mkv", b"x"),
        ],
    )
    scan_library(library_root, session, probe_runner=_probe_noop)

    vfiles = session.exec(select(VideoFile)).all()
    assert len(vfiles) == 2
    variants = {vf.variant for vf in vfiles}
    assert variants == {"ESP", "LAT"}


# ---------- embedded subtitle tracks ----------


def test_scan_embedded_subs_from_probe(session, library_root: Path, make_movie_folder):
    make_movie_folder(
        "Sirat (2025)",
        [("Sirat (2025).mkv", b"x")],
    )
    scan_library(library_root, session, probe_runner=_probe_with_embedded_subs)

    vfile = session.exec(select(VideoFile)).first()
    embedded = session.exec(
        select(EmbeddedSubtitle).where(EmbeddedSubtitle.video_file_id == vfile.id)
    ).all()
    assert len(embedded) == 2
    by_lang = {e.language: e for e in embedded}
    assert "en" in by_lang
    assert "es" in by_lang
    assert by_lang["en"].codec == "srt"
    assert by_lang["en"].default is True
    assert by_lang["es"].codec == "pgs"
    assert by_lang["es"].forced is True


# ---------- idempotency ----------


def test_scan_is_idempotent(session, library_root: Path, make_movie_folder):
    """Scanning the same folder twice must not duplicate rows."""
    make_movie_folder(
        "Stalker (1979)",
        [
            ("Stalker (1979).mp4", b"x"),
            ("Stalker (1979).srt", b"x"),
        ],
    )
    scan_library(library_root, session, probe_runner=_probe_noop)
    scan_library(library_root, session, probe_runner=_probe_noop)

    assert session.exec(select(Movie)).all().__len__() == 1
    assert session.exec(select(VideoFile)).all().__len__() == 1
    assert session.exec(select(ExternalSubtitle)).all().__len__() == 1


def test_embedded_subs_refreshed_on_rescan(session, library_root: Path, make_movie_folder):
    """Re-probing with different tracks should replace, not accumulate."""
    make_movie_folder("Bar (2024)", [("Bar (2024).mkv", b"x")])

    scan_library(library_root, session, probe_runner=_probe_with_embedded_subs)
    assert len(session.exec(select(EmbeddedSubtitle)).all()) == 2

    scan_library(library_root, session, probe_runner=_probe_noop)  # no tracks
    assert len(session.exec(select(EmbeddedSubtitle)).all()) == 0


# ---------- probe error isolation ----------


def _probe_fail(_path: Path) -> dict:
    raise RuntimeError("ffprobe crashed")


def test_probe_failure_does_not_abort_scan(session, library_root: Path, make_movie_folder):
    make_movie_folder("Alpha (2024)", [("Alpha (2024).mkv", b"x")])
    make_movie_folder("Beta (2024)", [("Beta (2024).mkv", b"x")])

    # One runner always fails; should NOT raise.
    call_count = [0]

    def selective_fail(path: Path) -> dict:
        call_count[0] += 1
        if "Alpha" in path.name:
            raise RuntimeError("bang")
        return _probe_noop(path)

    stats = scan_library(library_root, session, probe_runner=selective_fail)
    assert stats["probe_errors"] >= 1

    # Both movies still inserted despite probe failure on Alpha.
    movies = session.exec(select(Movie)).all()
    assert {m.title for m in movies} == {"Alpha", "Beta"}


# ---------- progress callback ----------


def test_progress_callback_called(session, library_root: Path, make_movie_folder):
    make_movie_folder("A (2024)", [("A (2024).mkv", b"x")])
    make_movie_folder("B (2024)", [("B (2024).mkv", b"x")])

    calls: list[tuple[int, int]] = []
    scan_library(library_root, session, probe_runner=_probe_noop, progress=lambda d, t: calls.append((d, t)))

    assert calls == [(1, 2), (2, 2)]


# ---------- language override sticky on rescan ----------


def test_manual_language_override_preserved(session, library_root: Path, make_movie_folder):
    make_movie_folder(
        "Foo (2024)",
        [
            ("Foo (2024).mp4", b"x"),
            ("Foo (2024).srt", b"x"),
        ],
    )
    scan_library(library_root, session, probe_runner=_probe_noop)

    # Simulate user override: mark as manual + set language.
    sub = session.exec(select(ExternalSubtitle)).first()
    sub.language = "fr"
    sub.language_source = LanguageSource.manual
    session.add(sub)
    session.commit()

    # Rescan — parser would say language=None for bare `.srt`, but override is sticky.
    scan_library(library_root, session, probe_runner=_probe_noop)
    sub = session.exec(select(ExternalSubtitle)).first()
    assert sub.language == "fr"
    assert sub.language_source == LanguageSource.manual


# ---------- non-conforming folders skipped ----------


def test_non_conforming_folders_skipped(session, library_root: Path):
    (library_root / "random folder").mkdir()
    (library_root / "random folder" / "video.mp4").write_bytes(b"x")

    scan_library(library_root, session, probe_runner=_probe_noop)
    assert session.exec(select(Movie)).all() == []


# ---------- symlinks ----------


def test_symlinked_video_real_path_stored(
    session, tmp_data: Path, library_root: Path
):
    import os
    raw = tmp_data / "raw"
    raw.mkdir()
    real_video = raw / "real.mp4"
    real_video.write_bytes(b"x")

    folder = library_root / "Link (2024)"
    folder.mkdir()
    link = folder / "Link (2024).mp4"
    os.symlink(real_video, link)

    scan_library(library_root, session, probe_runner=_probe_noop)

    vf = session.exec(select(VideoFile)).first()
    assert vf.is_symlink is True
    assert vf.real_path == str(real_video)
    assert vf.path == str(link)


# ---------- stats ----------


def test_stats_returned(session, library_root: Path, make_movie_folder):
    make_movie_folder(
        "Foo (2024)",
        [
            ("Foo (2024).mkv", b"x"),
            ("Foo (2024).en.srt", b"x"),
            ("Foo (2024).es.srt", b"x"),
        ],
    )
    stats = scan_library(library_root, session, probe_runner=_probe_noop)
    assert stats["movies"] == 1
    assert stats["videos"] == 1
    assert stats["subs"] == 2
    assert stats["probe_errors"] == 0
