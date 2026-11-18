from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlmodel import select

import app.core.config as config_mod
from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    MediaKind,
    Movie,
    Series,
    SubSource,
    VideoFile,
)


def _setup_series(session, library_root: Path) -> Series:
    season = library_root / "Pluribus (2025)" / "Season 01"
    season.mkdir(parents=True)
    series = Series(
        library_id="series",
        folder_path=str(library_root / "Pluribus (2025)"),
        title="Pluribus",
        year=2025,
        scanned_at=datetime.utcnow(),
    )
    session.add(series)
    session.commit()
    session.refresh(series)

    episode = Movie(
        folder_path=f"{series.folder_path}#Season 01S01E01",
        title="Pluribus",
        year=2025,
        kind=MediaKind.episode,
        library_id="series",
        series_id=series.id,
        season_number=1,
        episode_number=1,
        episode_label="S01E01",
        subtitle_dir=str(season),
        subtitle_stem="Pluribus S01E01",
        scanned_at=datetime.utcnow(),
    )
    other = Movie(
        folder_path=f"{series.folder_path}#extras/Behind the scenes.mkv",
        title="Pluribus",
        year=2025,
        kind=MediaKind.episode,
        library_id="series",
        series_id=series.id,
        episode_label="Behind the scenes",
        subtitle_dir=str(library_root / "Pluribus (2025)" / "extras"),
        subtitle_stem="Behind the scenes",
        scanned_at=datetime.utcnow(),
    )
    session.add(episode)
    session.add(other)
    session.commit()
    session.refresh(episode)
    session.refresh(other)

    video = VideoFile(
        movie_id=episode.id,
        path=str(season / "Pluribus S01E01.mkv"),
        real_path=str(season / "Pluribus S01E01.mkv"),
        filename="Pluribus S01E01.mkv",
        container="mkv",
    )
    session.add(video)
    session.commit()
    session.refresh(video)

    session.add(
        ExternalSubtitle(
            movie_id=episode.id,
            path=str(season / "Pluribus S01E01.en.srt"),
            real_path=str(season / "Pluribus S01E01.en.srt"),
            filename="Pluribus S01E01.en.srt",
            language="en",
            language_source="filename",
            source=SubSource.preexisting,
            created_at=datetime.utcnow(),
        )
    )
    session.add(
        EmbeddedSubtitle(
            video_file_id=video.id,
            track_index=2,
            codec="subrip",
            language="es",
        )
    )
    session.commit()
    return series


def test_list_series(client, session, library_root: Path, monkeypatch):
    monkeypatch.setattr(
        config_mod.settings, "libraries", "Series|series|" + str(library_root)
    )
    series = _setup_series(session, library_root)

    body = client.get("/series/?library=series").json()
    assert len(body) == 1
    assert body[0]["id"] == series.id
    assert body[0]["episode_count"] == 2
    assert body[0]["video_count"] == 1
    assert body[0]["external_sub_languages"] == ["en"]
    assert body[0]["embedded_sub_languages"] == ["es"]
    assert body[0]["has_subs"] is True


def test_series_library_type_mismatch(client, session, library_root: Path, monkeypatch):
    monkeypatch.setattr(
        config_mod.settings, "libraries", "Movies|movies|" + str(library_root)
    )
    assert client.get("/series/?library=movies").status_code == 422


def test_unknown_library_404(client):
    assert client.get("/series/?library=missing").status_code == 404


def test_series_detail_groups_seasons_and_other_videos(
    client, session, library_root: Path
):
    series = _setup_series(session, library_root)
    body = client.get(f"/series/{series.id}").json()

    assert body["title"] == "Pluribus"
    assert body["year"] == 2025
    assert len(body["season_groups"]) == 1
    group = body["season_groups"][0]
    assert group["season_number"] == 1
    assert [ep["episode_label"] for ep in group["episodes"]] == ["S01E01"]
    assert [ep["episode_label"] for ep in body["other_videos"]] == [
        "Behind the scenes"
    ]


def test_missing_series_404(client):
    assert client.get("/series/9999").status_code == 404


def test_episode_detail_returns_series_identity(
    client, session, library_root: Path
):
    series = _setup_series(session, library_root)
    episode = session.exec(
        select(Movie).where(Movie.episode_number == 1)
    ).one()

    body = client.get(f"/movies/{episode.id}").json()
    assert body["kind"] == "episode"
    assert body["series_id"] == series.id
    assert body["series_title"] == "Pluribus"
    assert body["episode_label"] == "S01E01"
    assert len(body["video_files"]) == 1
    assert len(body["external_subs"]) == 1
