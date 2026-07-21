"""Content-based language detection for subtitle files with no language token
in their filename. Invoked by the scanner (auto, on unknown subs) and by the
`/subs/{id}/detect-language` endpoint (manual re-detect).

Pure module aside from file IO — no DB access here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pysrt
from langdetect import DetectorFactory, LangDetectException, detect

# langdetect is non-deterministic per-process by default; pin the seed so
# repeated scans of the same file always agree.
DetectorFactory.seed = 0

_TAG_RE = re.compile(r"<[^>]+>|\{[^}]+\}")
_MAX_CHARS = 20_000

# langdetect emits a couple of non-BCP-47 codes; normalize those.
_CODE_MAP = {
    "zh-cn": "zh-Hans",
    "zh-tw": "zh-Hant",
}


def extract_text(path: Path, fmt: str) -> str:
    """Read subtitle cue text from disk, stripped of markup."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    if fmt == "srt":
        try:
            subs = pysrt.from_string(raw)
            raw = "\n".join(item.text for item in subs)
        except Exception:
            pass  # fall back to raw text if pysrt can't parse it
    text = _TAG_RE.sub(" ", raw)
    return text[:_MAX_CHARS]


def detect_language(path: Path, fmt: str) -> str | None:
    """Best-effort BCP-47 language code for the subtitle at `path`, or None
    if the file is missing, unreadable, or its text is too sparse to
    classify."""
    try:
        text = extract_text(path, fmt)
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        code = detect(text)
    except LangDetectException:
        return None
    return _CODE_MAP.get(code, code)
