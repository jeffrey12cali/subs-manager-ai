"""Parse subtitle filenames into (language, flags, custom_tag).

Implements the patterns documented in PLAN.md §A. Pure module, no IO —
content-based language detection lives in `langdetect_op` and is invoked
only when this parser returns `language=None`.

Resolver order (per PLAN §A):
  1. Strip the leading `<stem>` if filename starts with it, else strip a
     numeric prefix like `3_` (track-number prefix from extraction tools).
  2. Tokenize remainder on `.`, `_`, `-`.
  3. For each token, try to resolve to a language code or a flag.
  4. Unknown tokens collected into `custom_tag` (joined by `.`).
  5. If no language token resolved, return language=None — caller can
     fall back to content detection.

Manual overrides (set via the API) bypass this entirely; the parser is
only consulted on first-scan or when `language_source != manual`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

from app.models import LanguageSource

# --------------------------------------------------------------------------
# Language tables. Hand-curated — the user's library is mostly EN/ES/ZH/JA;
# easy to extend, but no need to pull in `babel` for this.

# BCP-47 tags we emit. Keep keys lowercase.
_LANG_ALIASES: dict[str, str] = {
    # English
    "en": "en", "eng": "en", "english": "en",
    # Spanish (general + regional dialects encountered in jellyfin libs)
    "es": "es", "spa": "es", "spanish": "es", "esp": "es", "español": "es",
    "espanol": "es", "castellano": "es-ES",
    "lat": "es-419", "latino": "es-419", "latam": "es-419",
    # French
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr", "francais": "fr",
    "français": "fr",
    # German
    "de": "de", "deu": "de", "ger": "de", "german": "de", "deutsch": "de",
    # Italian
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    # Portuguese
    "pt": "pt", "por": "pt", "portuguese": "pt", "português": "pt",
    "portugues": "pt", "ptbr": "pt-BR", "pt-br": "pt-BR", "br": "pt-BR",
    "brasileiro": "pt-BR",
    # Japanese
    "ja": "ja", "jpn": "ja", "japanese": "ja", "日本語": "ja",
    # Chinese (simplified vs traditional disambiguation only when explicit)
    "zh": "zh", "chi": "zh", "zho": "zh", "chinese": "zh",
    "zhs": "zh-Hans", "zh-cn": "zh-Hans", "zhcn": "zh-Hans", "simplified": "zh-Hans",
    "zht": "zh-Hant", "zh-tw": "zh-Hant", "zhtw": "zh-Hant", "traditional": "zh-Hant",
    # Korean
    "ko": "ko", "kor": "ko", "korean": "ko",
    # Russian
    "ru": "ru", "rus": "ru", "russian": "ru",
    # Arabic
    "ar": "ar", "ara": "ar", "arabic": "ar",
    # Dutch
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl", "nederlands": "nl",
    # Polish
    "pl": "pl", "pol": "pl", "polish": "pl",
    # Turkish
    "tr": "tr", "tur": "tr", "turkish": "tr",
    # Hindi
    "hi": "hi", "hin": "hi", "hindi": "hi",
    # Swedish, Norwegian, Danish, Finnish
    "sv": "sv", "swe": "sv", "swedish": "sv",
    "no": "no", "nor": "no", "norwegian": "no",
    "da": "da", "dan": "da", "danish": "da",
    "fi": "fi", "fin": "fi", "finnish": "fi",
    # Czech, Greek, Hungarian, Romanian
    "cs": "cs", "cze": "cs", "ces": "cs", "czech": "cs",
    "el": "el", "gre": "el", "ell": "el", "greek": "el",
    "hu": "hu", "hun": "hu", "hungarian": "hu",
    "ro": "ro", "rum": "ro", "ron": "ro", "romanian": "ro",
    # Hebrew
    "he": "he", "heb": "he", "hebrew": "he", "iw": "he",
    # Thai, Vietnamese, Indonesian
    "th": "th", "tha": "th", "thai": "th",
    "vi": "vi", "vie": "vi", "vietnamese": "vi",
    "id": "id", "ind": "id", "indonesian": "id",
}

# Tokens that flag attributes rather than language. Note: `hi` collides with
# Hindi's ISO-639-1 code. We handle the conflict in the parser: a single
# token alone is ambiguous, but `<stem>.hi.srt` is much more likely Hindi
# than "hearing impaired" in practice — so we treat `hi`/`HI` as Hindi by
# default. Use `sdh` or `cc` for hearing-impaired flags (jellyfin standard).
_FLAG_TOKENS: dict[str, str] = {
    "forced": "forced",
    "force": "forced",
    "sdh": "sdh",
    "cc": "sdh",
    "default": "default",
}

_VALID_SUB_EXTS: frozenset[str] = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sub"})

# A "track-number prefix" looks like `3_` or `04_` at the very start of the
# filename. Used by mkvextract output (e.g. `3_English.srt`).
_TRACK_PREFIX_RE = re.compile(r"^(\d+)_")


@dataclass
class ParsedSub:
    language: str | None
    language_source: LanguageSource
    forced: bool = False
    sdh: bool = False
    default: bool = False
    custom_tag: str | None = None
    format: str = "srt"


def parse_subtitle_filename(filename: str, movie_stem: str) -> ParsedSub:
    """Extract metadata from a subtitle filename.

    Args:
      filename: basename only (e.g. "Shutter (2004).spanish.ai.srt").
      movie_stem: the canonical movie name without extension
                  (e.g. "Shutter (2004)"). Case-insensitive match.

    Returns a ParsedSub. `language` is None if no token resolved — caller
    should fall back to content detection.
    """
    name = PurePath(filename).name
    ext = PurePath(name).suffix.lower()
    fmt = ext.lstrip(".") if ext in _VALID_SUB_EXTS else "srt"
    stem = name[: -len(ext)] if ext else name

    # Step 1: strip movie stem prefix or numeric track prefix.
    remainder = _strip_prefix(stem, movie_stem)
    if remainder == stem:  # stem prefix didn't match; try track-number prefix
        m = _TRACK_PREFIX_RE.match(stem)
        if m:
            remainder = stem[m.end() :]

    # Step 2: tokenize on `.`, `_`, whitespace. Keep `-` inside tokens so
    # `pt-br` and `zh-cn` survive; we'll re-split them only if the whole
    # token doesn't resolve to an alias.
    tokens = _tokenize(remainder)
    tokens = _expand_hyphenated(tokens)

    # Step 3 + 4: classify each token.
    language: str | None = None
    forced = False
    sdh = False
    default = False
    custom_tokens: list[str] = []

    for tok in tokens:
        low = tok.lower()
        if low in _FLAG_TOKENS:
            flag = _FLAG_TOKENS[low]
            if flag == "forced":
                forced = True
            elif flag == "sdh":
                sdh = True
            elif flag == "default":
                default = True
            continue

        # Numeric tail like `_1` `_2` from `Title_es_1.srt` → preserve as
        # `alt-N` in custom_tag so multiple subs of the same lang are
        # distinguishable in UI.
        if tok.isdigit():
            custom_tokens.append(f"alt-{tok}")
            continue

        if language is None:
            resolved = _LANG_ALIASES.get(low)
            if resolved is not None:
                language = resolved
                continue

        # Unknown / extra descriptor — keep verbatim (lowercase) so the user
        # sees the same label they wrote.
        custom_tokens.append(low)

    custom_tag = ".".join(custom_tokens) or None
    language_source = (
        LanguageSource.filename if language is not None else LanguageSource.unknown
    )

    return ParsedSub(
        language=language,
        language_source=language_source,
        forced=forced,
        sdh=sdh,
        default=default,
        custom_tag=custom_tag,
        format=fmt,
    )


# ----- helpers -----


def _strip_prefix(stem: str, movie_stem: str) -> str:
    """Remove a leading `<movie_stem>` (case-insensitive) plus a single
    separator character (`.`, `_`, `-`, or space). Returns the unchanged
    stem if no match.
    """
    if not movie_stem:
        return stem
    lower_stem = stem.lower()
    lower_movie = movie_stem.lower()
    if lower_stem == lower_movie:
        return ""
    if lower_stem.startswith(lower_movie):
        sep_idx = len(movie_stem)
        if sep_idx < len(stem) and stem[sep_idx] in "._- ":
            return stem[sep_idx + 1 :]
    return stem


def _tokenize(s: str) -> list[str]:
    if not s:
        return []
    # Split on `.`, `_`, and runs of whitespace. `-` stays inside the token
    # so compound codes like `pt-br` and `zh-tw` survive intact.
    return [t for t in re.split(r"[._\s]+", s) if t]


def _expand_hyphenated(tokens: list[str]) -> list[str]:
    """For each token containing `-`: if the whole token is a known alias,
    keep it as-is; otherwise split it into its parts so each can be
    classified independently. This lets `en-forced` work as `en` + `forced`
    while preserving `pt-br` as `pt-br`."""
    out: list[str] = []
    for t in tokens:
        if "-" in t and t.lower() not in _LANG_ALIASES:
            out.extend(p for p in t.split("-") if p)
        else:
            out.append(t)
    return out
