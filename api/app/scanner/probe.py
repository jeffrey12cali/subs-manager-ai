"""Wrap ffprobe to extract duration, video/audio info, and embedded
subtitle tracks from a media file.

The subprocess invocation is injectable via `runner=` so tests don't
need ffprobe installed.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Map ffprobe `codec_name` for subtitles → our `EmbeddedSubtitle.codec`.
_SUB_CODEC_MAP: dict[str, str] = {
    "subrip": "srt",
    "srt": "srt",
    "ass": "ass",
    "ssa": "ssa",
    "webvtt": "vtt",
    "hdmv_pgs_subtitle": "pgs",
    "dvd_subtitle": "vobsub",
    "dvb_subtitle": "dvb",
    "mov_text": "mov_text",
}

# ISO-639-2 → BCP-47 (subset; matches the parser table).
_ISO3_TO_BCP47: dict[str, str] = {
    "eng": "en",
    "spa": "es",
    "fra": "fr",
    "fre": "fr",
    "deu": "de",
    "ger": "de",
    "ita": "it",
    "por": "pt",
    "jpn": "ja",
    "chi": "zh",
    "zho": "zh",
    "kor": "ko",
    "rus": "ru",
    "ara": "ar",
    "dut": "nl",
    "nld": "nl",
    "pol": "pl",
    "tur": "tr",
    "hin": "hi",
    "swe": "sv",
    "nor": "no",
    "dan": "da",
    "fin": "fi",
    "cze": "cs",
    "ces": "cs",
    "gre": "el",
    "ell": "el",
    "hun": "hu",
    "rum": "ro",
    "ron": "ro",
    "heb": "he",
    "tha": "th",
    "vie": "vi",
    "ind": "id",
}

ProbeRunner = Callable[[Path], dict]


@dataclass
class ProbedAudio:
    index: int
    codec: str | None = None
    language: str | None = None
    channels: int | None = None
    title: str | None = None


@dataclass
class ProbedSub:
    index: int  # ffprobe global stream index
    codec: str
    language: str | None = None
    title: str | None = None
    default: bool = False
    forced: bool = False


@dataclass
class ProbedVideo:
    duration: float | None = None
    container: str | None = None
    video_codec: str | None = None
    audio: list[ProbedAudio] = field(default_factory=list)
    subtitles: list[ProbedSub] = field(default_factory=list)


class ProbeError(Exception):
    """Raised when ffprobe fails or returns unparseable output."""


def probe_file(path: Path, runner: ProbeRunner | None = None) -> ProbedVideo:
    """Run ffprobe and map its output to a ProbedVideo.

    `runner` may be supplied in tests to bypass the real subprocess call;
    it should accept a Path and return the parsed JSON dict.
    """
    raw = (runner or _default_runner)(path)
    return _map(raw, path)


# ----- subprocess invocation -----


def _default_runner(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=60
        )
    except FileNotFoundError as e:
        raise ProbeError("ffprobe not found in PATH") from e
    except subprocess.TimeoutExpired as e:
        raise ProbeError(f"ffprobe timed out for {path}") from e

    if result.returncode != 0:
        raise ProbeError(f"ffprobe exit {result.returncode}: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ProbeError(f"ffprobe produced invalid JSON for {path}") from e


# ----- mapping -----


def _map(raw: dict, path: Path) -> ProbedVideo:
    video = ProbedVideo()

    fmt = raw.get("format") or {}
    dur = fmt.get("duration")
    if dur is not None:
        try:
            video.duration = float(dur)
        except (TypeError, ValueError):
            log.warning("unparseable duration %r for %s", dur, path)
    video.container = path.suffix.lstrip(".").lower() or None

    for stream in raw.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and video.video_codec is None:
            # Take only the first video stream (covers attached pictures).
            if stream.get("disposition", {}).get("attached_pic"):
                continue
            video.video_codec = stream.get("codec_name")
        elif kind == "audio":
            video.audio.append(_map_audio(stream))
        elif kind == "subtitle":
            sub = _map_sub(stream)
            if sub is not None:
                video.subtitles.append(sub)
    return video


def _map_audio(s: dict) -> ProbedAudio:
    tags = s.get("tags") or {}
    return ProbedAudio(
        index=s.get("index", -1),
        codec=s.get("codec_name"),
        language=_normalize_lang(tags.get("language")),
        channels=s.get("channels"),
        title=tags.get("title"),
    )


def _map_sub(s: dict) -> ProbedSub | None:
    raw_codec = s.get("codec_name") or ""
    codec = _SUB_CODEC_MAP.get(raw_codec.lower())
    if codec is None:
        # Unknown subtitle codec — record it raw so the user can see
        # something rather than dropping the track silently.
        codec = raw_codec.lower() or "unknown"

    tags = s.get("tags") or {}
    disp = s.get("disposition") or {}
    return ProbedSub(
        index=s.get("index", -1),
        codec=codec,
        language=_normalize_lang(tags.get("language")),
        title=tags.get("title"),
        default=bool(disp.get("default")),
        forced=bool(disp.get("forced")),
    )


def _normalize_lang(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if v in {"und", "undefined", "unknown", "zxx", ""}:
        return None
    if len(v) == 3 and v in _ISO3_TO_BCP47:
        return _ISO3_TO_BCP47[v]
    if len(v) == 2:
        return v
    return v  # pass through whatever odd thing was set
