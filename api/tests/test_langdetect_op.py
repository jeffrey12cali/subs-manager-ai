"""Tests for content-based subtitle language detection."""
from __future__ import annotations

from pathlib import Path

from app.scanner.langdetect_op import detect_language, extract_text

SPANISH_SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\n"
    "Buenos días, ¿cómo estás hoy? Espero que todo vaya bien contigo.\n\n"
    "2\n00:00:04,000 --> 00:00:06,000\n"
    "No puedo creer lo que acaba de suceder en esta habitación tan extraña.\n"
)

ENGLISH_SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\n"
    "Good morning, how are you doing today? I hope everything is fine with you.\n\n"
    "2\n00:00:04,000 --> 00:00:06,000\n"
    "I cannot believe what just happened in this strange room over there.\n"
)

JAPANESE_SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\n"
    "おはようございます、今日の調子はいかがですか。すべて順調であることを願っています。\n"
)


def test_detect_spanish(tmp_path: Path):
    p = tmp_path / "unknown.srt"
    p.write_text(SPANISH_SRT, encoding="utf-8")
    assert detect_language(p, "srt") == "es"


def test_detect_english(tmp_path: Path):
    p = tmp_path / "unknown.srt"
    p.write_text(ENGLISH_SRT, encoding="utf-8")
    assert detect_language(p, "srt") == "en"


def test_detect_japanese(tmp_path: Path):
    p = tmp_path / "unknown.srt"
    p.write_text(JAPANESE_SRT, encoding="utf-8")
    assert detect_language(p, "srt") == "ja"


def test_detect_is_deterministic(tmp_path: Path):
    p = tmp_path / "unknown.srt"
    p.write_text(SPANISH_SRT, encoding="utf-8")
    assert detect_language(p, "srt") == detect_language(p, "srt")


def test_detect_empty_file_returns_none(tmp_path: Path):
    p = tmp_path / "empty.srt"
    p.write_text("", encoding="utf-8")
    assert detect_language(p, "srt") is None


def test_detect_missing_file_returns_none(tmp_path: Path):
    assert detect_language(tmp_path / "does-not-exist.srt", "srt") is None


def test_extract_text_strips_srt_timestamps(tmp_path: Path):
    p = tmp_path / "x.srt"
    p.write_text(SPANISH_SRT, encoding="utf-8")
    text = extract_text(p, "srt")
    assert "00:00:01,000" not in text
    assert "días" in text
