"""Test every pattern documented in PLAN.md §A using filenames pulled
verbatim from the user's actual library tree."""

from __future__ import annotations

import pytest

from app.models import LanguageSource
from app.scanner.sub_name_parser import parse_subtitle_filename

# ----- case 1: bare `<stem>.srt` (unknown language) -----


def test_bare_stem_srt_returns_unknown():
    p = parse_subtitle_filename("Shutter (2004).srt", "Shutter (2004)")
    assert p.language is None
    assert p.language_source == LanguageSource.unknown
    assert p.forced is False
    assert p.sdh is False
    assert p.custom_tag is None
    assert p.format == "srt"


# ----- case 2: canonical `<stem>.<lang>.srt` -----


def test_canonical_lang_suffix():
    p = parse_subtitle_filename("Foo (2024).en.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.language_source == LanguageSource.filename
    assert p.custom_tag is None


def test_canonical_lang_suffix_es():
    p = parse_subtitle_filename("Foo (2024).es.srt", "Foo (2024)")
    assert p.language == "es"


# ----- case 3: forced flag -----


def test_forced_flag():
    p = parse_subtitle_filename("Foo (2024).en.forced.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.forced is True
    assert p.custom_tag is None


def test_sdh_flag_via_sdh_token():
    p = parse_subtitle_filename("Foo (2024).en.sdh.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.sdh is True


def test_sdh_flag_via_cc_token():
    p = parse_subtitle_filename("Foo (2024).en.cc.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.sdh is True


# ----- case 4: free-form `.spanish.ai.srt` -----


def test_spanish_ai_suffix():
    """Real example: `Shutter (2004).spanish.ai.srt`. First token resolves
    to a language (Spanish → es), the rest become a custom_tag."""
    p = parse_subtitle_filename("Shutter (2004).spanish.ai.srt", "Shutter (2004)")
    assert p.language == "es"
    assert p.language_source == LanguageSource.filename
    assert p.custom_tag == "ai"


def test_spanish_ai_underscore_separator():
    p = parse_subtitle_filename("Shutter (2004).spanish_ai.srt", "Shutter (2004)")
    assert p.language == "es"
    assert p.custom_tag == "ai"


# ----- case 5: `_es_1` underscore + index -----


def test_es_index_one():
    p = parse_subtitle_filename(
        "Suicide Club (2001)_es_1.srt", "Suicide Club (2001)"
    )
    assert p.language == "es"
    assert p.custom_tag == "alt-1"


def test_es_index_two():
    p = parse_subtitle_filename(
        "Suicide Club (2001)_es_2.srt", "Suicide Club (2001)"
    )
    assert p.language == "es"
    assert p.custom_tag == "alt-2"


# ----- case 6: track-number prefix `3_English.srt` -----


def test_track_prefix_english():
    p = parse_subtitle_filename("3_English.srt", "Suicide Club (2001)")
    assert p.language == "en"
    assert p.language_source == LanguageSource.filename
    assert p.custom_tag is None


def test_track_prefix_chinese():
    p = parse_subtitle_filename("4_Chinese.srt", "Suicide Club (2001)")
    assert p.language == "zh"


def test_track_prefix_two_digit():
    p = parse_subtitle_filename("12_Spanish.srt", "Whatever")
    assert p.language == "es"


# ----- case 7: language aliases -----


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("english", "en"),
        ("eng", "en"),
        ("EN", "en"),
        ("spanish", "es"),
        ("español", "es"),
        ("espanol", "es"),
        ("castellano", "es-ES"),
        ("latino", "es-419"),
        ("lat", "es-419"),
        ("french", "fr"),
        ("fra", "fr"),
        ("german", "de"),
        ("portuguese", "pt"),
        ("pt-br", "pt-BR"),
        ("ptbr", "pt-BR"),
        ("brasileiro", "pt-BR"),
        ("japanese", "ja"),
        ("jpn", "ja"),
        ("zh-cn", "zh-Hans"),
        ("zh-tw", "zh-Hant"),
        ("simplified", "zh-Hans"),
        ("traditional", "zh-Hant"),
        ("korean", "ko"),
        ("russian", "ru"),
    ],
)
def test_language_alias_resolution(token: str, expected: str):
    p = parse_subtitle_filename(f"Foo (2024).{token}.srt", "Foo (2024)")
    assert p.language == expected, f"{token!r} should resolve to {expected!r}"


# ----- format detection -----


def test_format_ass():
    p = parse_subtitle_filename("Foo (2024).en.ass", "Foo (2024)")
    assert p.format == "ass"


def test_format_vtt():
    p = parse_subtitle_filename("Foo (2024).en.vtt", "Foo (2024)")
    assert p.format == "vtt"


# ----- edge cases -----


def test_unknown_token_collected_as_custom_tag():
    p = parse_subtitle_filename("Foo (2024).bonus.srt", "Foo (2024)")
    assert p.language is None
    assert p.custom_tag == "bonus"


def test_multiple_unknowns_joined():
    p = parse_subtitle_filename("Foo (2024).director.cut.srt", "Foo (2024)")
    assert p.language is None
    assert p.custom_tag == "director.cut"


def test_lang_plus_unknown_plus_forced():
    p = parse_subtitle_filename("Foo (2024).en.directors.forced.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.forced is True
    assert p.custom_tag == "directors"


def test_case_insensitive_stem_match():
    p = parse_subtitle_filename("FOO (2024).en.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.custom_tag is None


def test_ignores_extra_extension_in_stem():
    """`Foo (2024).bak.en.srt` — `bak` is not a language; should be in
    custom_tag and `en` resolves to the language."""
    p = parse_subtitle_filename("Foo (2024).bak.en.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.custom_tag == "bak"


def test_only_first_recognized_lang_token_wins():
    """If two language tokens appear, the first wins; the second is a
    descriptor."""
    p = parse_subtitle_filename("Foo (2024).en.es.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.custom_tag == "es"


def test_no_stem_match_falls_back_to_full_tokenization():
    """Filename doesn't start with movie stem at all — still parse what we can."""
    p = parse_subtitle_filename("randomname.en.srt", "Foo (2024)")
    assert p.language == "en"


def test_dash_separator_supported():
    p = parse_subtitle_filename("Foo (2024)-en-forced.srt", "Foo (2024)")
    assert p.language == "en"
    assert p.forced is True


def test_chinese_full_word():
    p = parse_subtitle_filename("Foo (2024).chinese.srt", "Foo (2024)")
    assert p.language == "zh"


def test_invalid_extension_defaults_format_srt():
    """If somehow we receive a non-sub extension, format falls back to srt
    (the parser should not be the gatekeeper for filtering — that's the
    walker's job)."""
    p = parse_subtitle_filename("Foo (2024).en.txt", "Foo (2024)")
    assert p.format == "srt"


def test_empty_remainder_returns_unknown():
    p = parse_subtitle_filename("Foo (2024).srt", "Foo (2024)")
    assert p.language is None
    assert p.custom_tag is None
