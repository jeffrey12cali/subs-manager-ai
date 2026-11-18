from __future__ import annotations

import app.core.config as config_mod


def test_lists_legacy_movie_library(client):
    body = client.get("/libraries").json()
    assert len(body) == 1
    assert body[0]["type"] == "movies"
    assert body[0]["root"].endswith("/library")


def test_lists_named_libraries(client, monkeypatch):
    monkeypatch.setattr(
        config_mod.settings,
        "libraries",
        "Movies|movies|/media/Movies;TV Shows|series|/media/TV Shows",
    )
    body = client.get("/libraries").json()
    assert [(lib["id"], lib["name"], lib["type"]) for lib in body] == [
        ("movies", "Movies", "movies"),
        ("tv-shows", "TV Shows", "series"),
    ]


def test_invalid_library_entries_are_hidden(client, monkeypatch):
    monkeypatch.setattr(
        config_mod.settings,
        "libraries",
        "Good|series|/media/Series;Bad|unknown|/media/Bad;good|movies|/x",
    )
    body = client.get("/libraries").json()
    assert [lib["id"] for lib in body] == ["good"]
    assert body[0]["type"] == "series"
