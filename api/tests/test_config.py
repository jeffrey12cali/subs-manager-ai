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


def test_named_libraries_parse(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "LIBRARIES",
        "Movies|movies|/jefflix/Movies;TV Shows|series|/jefflix/TV Shows",
    )
    s = Settings()
    libs = s.configured_libraries
    assert [(lib.id, lib.name, lib.type, lib.root) for lib in libs] == [
        ("movies", "Movies", "movies", "/jefflix/Movies"),
        ("tv-shows", "TV Shows", "series", "/jefflix/TV Shows"),
    ]
    assert s.get_library("tv-shows").type == "series"


def test_named_libraries_reject_invalid_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "LIBRARIES",
        "Movies|movies|/a;Bad|other|/b;movies|series|/c;NoRoot|series|;NoType||/e",
    )
    s = Settings()
    assert [lib.id for lib in s.configured_libraries] == ["movies"]


def test_legacy_roots_become_movie_libraries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LIBRARIES", raising=False)
    monkeypatch.setenv("LIBRARY_ROOTS", "/media/Movies:/media/Movies:/media/Series")
    s = Settings()
    libs = s.configured_libraries
    assert [(lib.id, lib.name, lib.type) for lib in libs] == [
        ("movies", "Movies", "movies"),
        ("movies-2", "Movies", "movies"),
        ("series", "Series", "movies"),
    ]


def test_writable_roots_include_named_and_legacy(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LIBRARIES", "Movies|movies|/media/Movies")
    monkeypatch.setenv("LIBRARY_ROOTS", "/legacy/Movies")
    s = Settings()
    assert s.writable_roots == ["/media/Movies", "/legacy/Movies"]
