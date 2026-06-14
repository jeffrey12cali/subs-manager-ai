import pytest

from app.core.config import Settings


def test_library_root_paths_splits_on_colon(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIBRARY_ROOTS", "/a:/b:/c")
    s = Settings()
    assert s.library_root_paths == ["/a", "/b", "/c"]


def test_library_root_paths_drops_empties(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIBRARY_ROOTS", "/a::/b")
    s = Settings()
    assert s.library_root_paths == ["/a", "/b"]


def test_defaults_present():
    s = Settings()
    assert s.whisper_compute_type == "int8"
    assert s.openai_base_url.endswith("/v1")
    assert s.translate_model == "deepseek-chat"
