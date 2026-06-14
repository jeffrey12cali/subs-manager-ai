"""Tests for SRT validation."""
import pytest

from app.core.srt_validator import InvalidSRT, validate_srt_bytes

VALID_SRT = b"""\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:04,000 --> 00:00:06,000
Goodbye world
"""

VALID_SRT_BOM = b"\xef\xbb\xbf" + VALID_SRT

VALID_SRT_LATIN1 = "1\n00:00:01,000 --> 00:00:03,000\nCaf\xe9\n".encode("latin-1")

SINGLE_CUE = b"1\n00:00:01,000 --> 00:00:02,000\nHi\n"

EMPTY = b""

NOT_SRT_AT_ALL = b"This is just a text file with no timing."

BINARY_GARBAGE = bytes(range(256))


# ---- valid cases ----

def test_valid_srt_returns_count():
    count = validate_srt_bytes(VALID_SRT)
    assert count == 2

def test_valid_bom_stripped():
    count = validate_srt_bytes(VALID_SRT_BOM)
    assert count == 2

def test_valid_latin1():
    count = validate_srt_bytes(VALID_SRT_LATIN1)
    assert count >= 1

def test_single_cue_accepted():
    assert validate_srt_bytes(SINGLE_CUE) == 1


# ---- invalid cases ----

def test_empty_raises():
    with pytest.raises(InvalidSRT, match="empty"):
        validate_srt_bytes(EMPTY)

def test_no_cues_raises():
    with pytest.raises(InvalidSRT, match="no subtitle entries"):
        validate_srt_bytes(NOT_SRT_AT_ALL)

def test_binary_garbage_raises():
    with pytest.raises(InvalidSRT):
        validate_srt_bytes(BINARY_GARBAGE)

def test_wrong_type_raises():
    with pytest.raises((InvalidSRT, TypeError)):
        validate_srt_bytes(None)  # type: ignore[arg-type]


# ---- edge cases ----

def test_windows_line_endings():
    crlf = VALID_SRT.replace(b"\n", b"\r\n")
    count = validate_srt_bytes(crlf)
    assert count >= 1

def test_html_tags_in_cue_accepted():
    srt = b"1\n00:00:01,000 --> 00:00:02,000\n<i>Italic text</i>\n"
    assert validate_srt_bytes(srt) >= 1

def test_large_srt_accepted():
    cues = []
    for i in range(1, 201):
        start = f"00:00:{i:02d},000"
        end = f"00:00:{i:02d},900"
        cues.append(f"{i}\n{start} --> {end}\nLine {i}\n")
    big = "\n".join(cues).encode("utf-8")
    count = validate_srt_bytes(big)
    assert count == 200
