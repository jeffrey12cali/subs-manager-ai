"""Parse season and episode markers from series video filenames.

The parser is pure. It prefers an explicit marker over a bare number, and it
uses the nearest recognized season folder only when the filename has no season.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_RESOLUTION_NUMBERS = frozenset({480, 576, 720, 1080, 2160, 4320})

_SEASON_EPISODE_RE = re.compile(
    r"(?<![A-Za-z0-9])[Ss](\d{1,3})[\s._-]*[Ee](\d{1,4})(?!\d)"
)
_SEASON_X_EPISODE_RE = re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,4})(?!\d)")
_EPISODE_ONLY_RE = re.compile(r"(?<![A-Za-z0-9])[Ee](\d{1,4})(?!\d)")
_LEADING_NUM_RE = re.compile(r"^(\d{1,4})(?![0-9])")
_SIMPLE_SUFFIX_NUM_RE = re.compile(r"^[A-Za-z]{1,12}[\s_-]+(\d{1,4})$")
_TRAILING_ANY_NUM_RE = re.compile(r"(?<!\d)(\d{1,4})$")
_SEASON_FOLDER_RE = re.compile(
    r"(?:\b(?:season|temporada)\s*0*(\d{1,2})\b)|^(?:[st])(\d{1,2})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EpisodeMarker:
    season: int | None = None
    episode: int | None = None
    label: str | None = None


def _reject_number(raw: str, following: str = "") -> bool:
    """Reject a bare number that is more likely a year or a resolution."""
    value = int(raw)
    if (
        len(raw) == 4
        and not raw.startswith("0")
        and 1900 <= value <= 2099
    ):
        return True
    return (
        value in _RESOLUTION_NUMBERS
        and following[:1].lower() in {"p", "i"}
    )


def _label(season: int | None, episode: int, raw: str) -> str:
    width = max(2, len(raw))
    number = f"{episode:0{width}d}"
    if season is None:
        return f"E{number}"
    return f"S{season:02d}E{number}"


def _season_from_folders(parent_names: Iterable[str]) -> int | None:
    for name in parent_names:
        match = _SEASON_FOLDER_RE.search(name)
        if match:
            value = match.group(1) or match.group(2)
            if value is not None:
                return int(value)
    return None


def parse_episode(
    filename: str,
    parent_names: Iterable[str] = (),
) -> EpisodeMarker:
    """Return the best season/episode marker for a video filename."""
    stem = Path(filename).stem

    match = _SEASON_EPISODE_RE.search(stem)
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        return EpisodeMarker(
            season=season,
            episode=episode,
            label=_label(season, episode, match.group(2)),
        )

    match = _SEASON_X_EPISODE_RE.search(stem)
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        return EpisodeMarker(
            season=season,
            episode=episode,
            label=_label(season, episode, match.group(2)),
        )

    match = _EPISODE_ONLY_RE.search(stem)
    if match:
        episode = int(match.group(1))
        season = _season_from_folders(parent_names)
        return EpisodeMarker(
            season=season,
            episode=episode,
            label=_label(season, episode, match.group(1)),
        )

    match = _LEADING_NUM_RE.search(stem)
    if match and not _reject_number(match.group(1), stem[match.end() :]):
        episode = int(match.group(1))
        season = _season_from_folders(parent_names)
        return EpisodeMarker(
            season=season,
            episode=episode,
            label=_label(season, episode, match.group(1)),
        )

    match = _SIMPLE_SUFFIX_NUM_RE.search(stem)
    if match and not _reject_number(match.group(1)):
        episode = int(match.group(1))
        season = _season_from_folders(parent_names)
        return EpisodeMarker(
            season=season,
            episode=episode,
            label=_label(season, episode, match.group(1)),
        )

    season = _season_from_folders(parent_names)
    if season is not None:
        match = _TRAILING_ANY_NUM_RE.search(stem)
        if match and not _reject_number(match.group(1)):
            episode = int(match.group(1))
            return EpisodeMarker(
                season=season,
                episode=episode,
                label=_label(season, episode, match.group(1)),
            )

    return EpisodeMarker()
