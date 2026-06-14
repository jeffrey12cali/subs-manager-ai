"""Validate SRT file content before accepting an upload.

Strategy: parse with pysrt (lenient), require at least one cue entry.
Supports UTF-8 and common encodings (Latin-1 fallback).
"""
from __future__ import annotations

import pysrt


class InvalidSRT(ValueError):
    """Raised when uploaded bytes are not a valid SRT file."""


def validate_srt_bytes(data: bytes) -> int:
    """Parse `data` as SRT. Returns the number of subtitle entries on success.

    Raises `InvalidSRT` with a human-readable message on failure.
    """
    if not data:
        raise InvalidSRT("File is empty.")

    text = _decode(data)
    try:
        subs = pysrt.from_string(text, error_handling=pysrt.SubRipFile.ERROR_PASS)
    except Exception as exc:
        raise InvalidSRT(f"Could not parse SRT: {exc}") from exc

    if len(subs) == 0:
        raise InvalidSRT("SRT file contains no subtitle entries.")

    return len(subs)


def _decode(data: bytes) -> str:
    # Strip UTF-8 BOM if present.
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InvalidSRT("Could not decode file — only UTF-8 and Latin-1 are supported.")
