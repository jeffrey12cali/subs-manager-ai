"""Probe tests with canned ffprobe JSON — no real ffprobe needed."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.scanner.probe import ProbedSub, ProbeError, probe_file

FAKE_PATH = Path("/library/Movie (2024)/Movie (2024).mkv")


def _runner(data: dict):
    """Return a runner fixture that always returns `data`."""
    return lambda _path: data


# ---- basic mapping ----


def test_duration_parsed():
    raw = {
        "format": {"duration": "7320.5"},
        "streams": [],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.duration == pytest.approx(7320.5)


def test_container_from_extension():
    raw = {"format": {}, "streams": []}
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.container == "mkv"


def test_video_codec_extracted():
    raw = {
        "format": {},
        "streams": [{"codec_type": "video", "codec_name": "h264", "index": 0}],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.video_codec == "h264"


def test_attached_picture_skipped():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "mjpeg",
                "index": 0,
                "disposition": {"attached_pic": 1},
            },
            {"codec_type": "video", "codec_name": "h264", "index": 1},
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.video_codec == "h264"


def test_audio_tracks():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "index": 1,
                "channels": 2,
                "tags": {"language": "eng", "title": "Stereo"},
            }
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert len(pv.audio) == 1
    a = pv.audio[0]
    assert a.codec == "aac"
    assert a.language == "en"  # iso-3 → bcp47
    assert a.channels == 2
    assert a.title == "Stereo"


# ---- embedded subtitle tracks ----


def test_mkv_with_srt_and_pgs_tracks():
    raw = {
        "format": {"duration": "5400"},
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "index": 0},
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "index": 2,
                "tags": {"language": "eng", "title": "English"},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "codec_type": "subtitle",
                "codec_name": "hdmv_pgs_subtitle",
                "index": 3,
                "tags": {"language": "spa"},
                "disposition": {"default": 0, "forced": 1},
            },
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert len(pv.subtitles) == 2

    eng, spa = pv.subtitles
    assert eng.codec == "srt"
    assert eng.language == "en"
    assert eng.default is True
    assert eng.forced is False

    assert spa.codec == "pgs"
    assert spa.language == "es"
    assert spa.forced is True


def test_mp4_no_embedded_subs():
    raw = {
        "format": {"duration": "3600"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "index": 0},
            {"codec_type": "audio", "codec_name": "aac", "index": 1, "tags": {}},
        ],
    }
    pv = probe_file(Path("/library/M (2024)/M (2024).mp4"), runner=_runner(raw))
    assert pv.subtitles == []


# ---- language normalisation ----


def test_iso3_to_bcp47_mapping():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "subtitle",
                "codec_name": "ass",
                "index": 0,
                "tags": {"language": "jpn"},
                "disposition": {},
            }
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.subtitles[0].language == "ja"


def test_und_language_normalised_to_none():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "index": 0,
                "tags": {"language": "und"},
                "disposition": {},
            }
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.subtitles[0].language is None


def test_no_language_tag_gives_none():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "index": 0,
                "tags": {},
                "disposition": {},
            }
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.subtitles[0].language is None


# ---- codec mapping ----


def test_unknown_sub_codec_passed_through():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "subtitle",
                "codec_name": "some_exotic_codec",
                "index": 0,
                "tags": {},
                "disposition": {},
            }
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.subtitles[0].codec == "some_exotic_codec"


def test_ass_codec_mapping():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "subtitle",
                "codec_name": "ass",
                "index": 0,
                "tags": {},
                "disposition": {},
            }
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.subtitles[0].codec == "ass"


# ---- error handling ----


def test_probe_error_on_runner_exception():
    def bad_runner(_p):
        raise RuntimeError("boom")

    with pytest.raises((RuntimeError, ProbeError)):
        probe_file(FAKE_PATH, runner=bad_runner)


def test_bad_duration_is_ignored():
    raw = {"format": {"duration": "not_a_number"}, "streams": []}
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.duration is None


def test_missing_format_key_ok():
    pv = probe_file(FAKE_PATH, runner=_runner({"streams": []}))
    assert pv.duration is None


def test_multiple_audio_tracks():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "ac3",
                "index": 1,
                "channels": 6,
                "tags": {"language": "eng"},
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "index": 2,
                "channels": 2,
                "tags": {"language": "spa"},
            },
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert len(pv.audio) == 2
    langs = [a.language for a in pv.audio]
    assert "en" in langs
    assert "es" in langs


def test_subtitle_list_type():
    """Sanity: subtitles is always a list, never None."""
    pv = probe_file(FAKE_PATH, runner=_runner({"streams": []}))
    assert isinstance(pv.subtitles, list)
    assert isinstance(pv.audio, list)


def test_empty_raw_dict_gives_empty_probed_video():
    """A completely empty ffprobe response (no `format`/`streams` keys) must not crash."""
    pv = probe_file(FAKE_PATH, runner=_runner({}))
    assert pv.duration is None
    assert pv.video_codec is None
    assert pv.audio == []
    assert pv.subtitles == []
    assert pv.container == "mkv"


def test_subtitle_missing_codec_name_defaults_to_unknown():
    raw = {
        "format": {},
        "streams": [{"codec_type": "subtitle", "index": 0, "tags": {}, "disposition": {}}],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.subtitles[0].codec == "unknown"


def test_subtitle_missing_index_defaults_to_minus_one():
    raw = {
        "format": {},
        "streams": [
            {"codec_type": "subtitle", "codec_name": "subrip", "tags": {}, "disposition": {}}
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.subtitles[0].index == -1


def test_duration_zero_string_parsed_as_zero():
    raw = {"format": {"duration": "0"}, "streams": []}
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert pv.duration == 0.0


def test_returns_typed_probed_sub_objects():
    raw = {
        "format": {},
        "streams": [
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "index": 0,
                "tags": {},
                "disposition": {"default": 0, "forced": 0},
            }
        ],
    }
    pv = probe_file(FAKE_PATH, runner=_runner(raw))
    assert isinstance(pv.subtitles[0], ProbedSub)
