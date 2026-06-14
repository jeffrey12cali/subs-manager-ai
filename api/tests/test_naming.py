"""Tests for canonical subtitle filename generation."""
from pathlib import PurePath

import pytest

from app.scanner.naming import canonical_sub_filename, canonical_sub_path, is_canonical

# ---- basic generation ----

def test_basic_en():
    assert canonical_sub_filename("Stalker", 1979, "en") == "Stalker (1979).en.srt"

def test_basic_es():
    assert canonical_sub_filename("Stalker", 1979, "es") == "Stalker (1979).es.srt"

def test_forced():
    assert canonical_sub_filename("Stalker", 1979, "en", forced=True) == "Stalker (1979).en.forced.srt"

def test_sdh():
    assert canonical_sub_filename("Stalker", 1979, "en", sdh=True) == "Stalker (1979).en.sdh.srt"

def test_forced_and_sdh_order():
    """forced must come before sdh."""
    name = canonical_sub_filename("Foo", 2024, "en", forced=True, sdh=True)
    assert name == "Foo (2024).en.forced.sdh.srt"

def test_custom_tag():
    name = canonical_sub_filename("Shutter", 2004, "es", custom_tag="ai")
    assert name == "Shutter (2004).es.ai.srt"

def test_custom_tag_with_forced():
    name = canonical_sub_filename("Foo", 2024, "es", forced=True, custom_tag="ai")
    assert name == "Foo (2024).es.forced.ai.srt"

def test_custom_tag_sanitised_slashes():
    name = canonical_sub_filename("Foo", 2024, "en", custom_tag="foo/bar")
    assert "/" not in name
    assert "foo-bar" in name

def test_custom_tag_strips_dots():
    name = canonical_sub_filename("Foo", 2024, "en", custom_tag=".hidden.")
    assert "..hidden.." not in name

def test_no_year():
    assert canonical_sub_filename("Foo", None, "en") == "Foo.en.srt"

def test_ext_override():
    assert canonical_sub_filename("Foo", 2024, "en", ext="ass") == "Foo (2024).en.ass"
    assert canonical_sub_filename("Foo", 2024, "en", ext=".vtt") == "Foo (2024).en.vtt"

def test_title_with_punctuation():
    name = canonical_sub_filename("Scent of a Woman", 1992, "en")
    assert name == "Scent of a Woman (1992).en.srt"

def test_bcp47_regional():
    name = canonical_sub_filename("Foo", 2024, "es-419")
    assert name == "Foo (2024).es-419.srt"


# ---- canonical_sub_path ----

def test_canonical_sub_path():
    p = canonical_sub_path("/library/Stalker (1979)", "Stalker", 1979, "en")
    assert p == PurePath("/library/Stalker (1979)/Stalker (1979).en.srt")

def test_canonical_sub_path_forced():
    p = canonical_sub_path("/library/Foo (2024)", "Foo", 2024, "es", forced=True)
    assert p == PurePath("/library/Foo (2024)/Foo (2024).es.forced.srt")


# ---- is_canonical ----

def test_is_canonical_true():
    assert is_canonical("Stalker (1979).en.srt", "Stalker", 1979) is True

def test_is_canonical_false():
    assert is_canonical("3_English.srt", "Stalker", 1979) is False

def test_is_canonical_no_year():
    assert is_canonical("Foo.en.srt", "Foo", None) is True


# ---- parametrised round-trip ----

@pytest.mark.parametrize("title,year,lang,forced,sdh,tag,expected", [
    ("Taxi Driver", 1976, "es", False, False, "ai", "Taxi Driver (1976).es.ai.srt"),
    ("Suicide Club", 2001, "en", False, False, None, "Suicide Club (2001).en.srt"),
    ("Superman", 2025, "es-419", True, False, None, "Superman (2025).es-419.forced.srt"),
    ("Foo", 2024, "zh-Hans", False, True, None, "Foo (2024).zh-Hans.sdh.srt"),
])
def test_parametrised(title, year, lang, forced, sdh, tag, expected):
    assert canonical_sub_filename(title, year, lang, forced=forced, sdh=sdh, custom_tag=tag) == expected
