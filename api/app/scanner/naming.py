"""Canonical subtitle filename generation.

Convention (Jellyfin-compatible):
  {Movie Title} ({Year}).{lang}[.forced][.sdh][.{custom_tag}].{ext}

Examples:
  Stalker (1979).en.srt
  Stalker (1979).es.forced.srt
  Shutter (2004).es.sdh.srt
  Foo (2024).en.forced.sdh.srt
  Taxi Driver (1976).es.ai.srt         (custom_tag="ai")

Rules:
  - lang is required (BCP-47, e.g. "en", "es", "es-419").
  - `forced` comes before `sdh` when both are set.
  - `custom_tag` comes last, before the extension.
  - ext defaults to "srt"; may be "ass", "vtt", etc.
  - Year is omitted from the stem if None.
"""

from __future__ import annotations

from pathlib import PurePath


def canonical_sub_filename(
    title: str,
    year: int | None,
    language: str,
    *,
    forced: bool = False,
    sdh: bool = False,
    custom_tag: str | None = None,
    ext: str = "srt",
) -> str:
    """Return the canonical subtitle filename for a movie."""
    stem = f"{title} ({year})" if year else title
    parts: list[str] = [stem, language]
    if forced:
        parts.append("forced")
    if sdh:
        parts.append("sdh")
    if custom_tag:
        # Sanitise: no slashes or dots in the tag itself.
        safe_tag = custom_tag.replace("/", "-").replace("\\", "-").strip(".")
        if safe_tag:
            parts.append(safe_tag)
    clean_ext = ext.lstrip(".")
    return ".".join(parts) + f".{clean_ext}"


def canonical_sub_path(
    movie_folder: str | PurePath,
    title: str,
    year: int | None,
    language: str,
    *,
    forced: bool = False,
    sdh: bool = False,
    custom_tag: str | None = None,
    ext: str = "srt",
) -> PurePath:
    """Full path: <movie_folder>/<canonical_filename>."""
    filename = canonical_sub_filename(
        title, year, language, forced=forced, sdh=sdh, custom_tag=custom_tag, ext=ext
    )
    return PurePath(movie_folder) / filename


def is_canonical(filename: str, title: str, year: int | None) -> bool:
    """Return True if filename already matches the canonical convention stem."""
    stem = f"{title} ({year})" if year else title
    return PurePath(filename).name.startswith(stem + ".")
