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


def canonical_sub_filename_for_stem(
    stem: str,
    language: str,
    *,
    forced: bool = False,
    sdh: bool = False,
    custom_tag: str | None = None,
    ext: str = "srt",
) -> str:
    """Return the canonical subtitle filename for an explicit stem."""
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
    return canonical_sub_filename_for_stem(
        stem,
        language,
        forced=forced,
        sdh=sdh,
        custom_tag=custom_tag,
        ext=ext,
    )


def canonical_sub_path_for_stem(
    directory: str | PurePath,
    stem: str,
    language: str,
    *,
    forced: bool = False,
    sdh: bool = False,
    custom_tag: str | None = None,
    ext: str = "srt",
) -> PurePath:
    """Full path: <directory>/<canonical_filename_for_stem>."""
    filename = canonical_sub_filename_for_stem(
        stem, language, forced=forced, sdh=sdh, custom_tag=custom_tag, ext=ext
    )
    return PurePath(directory) / filename


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
    stem = f"{title} ({year})" if year else title
    return canonical_sub_path_for_stem(
        movie_folder,
        stem,
        language,
        forced=forced,
        sdh=sdh,
        custom_tag=custom_tag,
        ext=ext,
    )


def is_canonical(filename: str, title: str, year: int | None) -> bool:
    """Return True if filename already matches the canonical convention stem."""
    stem = f"{title} ({year})" if year else title
    return is_canonical_for_stem(filename, stem)


def is_canonical_for_stem(filename: str, stem: str) -> bool:
    """Return True if filename already matches the canonical stem."""
    return PurePath(filename).name.startswith(stem + ".")


def item_subtitle_stem(item: object) -> str:
    """Stem used for an item's sidecar subtitles, with legacy fallback."""
    stem = getattr(item, "subtitle_stem", None)
    if stem:
        return str(stem)
    title = str(getattr(item, "title", ""))
    year = getattr(item, "year", None)
    return f"{title} ({year})" if year else title


def item_subtitle_dir(item: object) -> str:
    """Directory used for an item's sidecar subtitles, with legacy fallback."""
    directory = getattr(item, "subtitle_dir", None)
    if directory:
        return str(directory)
    return str(getattr(item, "folder_path", ""))


def canonical_sub_path_for_item(
    item: object,
    language: str,
    *,
    forced: bool = False,
    sdh: bool = False,
    custom_tag: str | None = None,
    ext: str = "srt",
) -> PurePath:
    """Full sidecar path for a movie or episode row."""
    return canonical_sub_path_for_stem(
        item_subtitle_dir(item),
        item_subtitle_stem(item),
        language,
        forced=forced,
        sdh=sdh,
        custom_tag=custom_tag,
        ext=ext,
    )


def is_canonical_for_item(filename: str, item: object) -> bool:
    """True when filename already uses the item's canonical stem."""
    return is_canonical_for_stem(filename, item_subtitle_stem(item))
