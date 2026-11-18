from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api._summaries import summarize_items
from app.api.libraries import path_in_library, resolve_library
from app.core.db import get_session
from app.models import MediaKind, Movie, Series
from app.schemas import EpisodeSummary, SeasonGroup, SeriesDetail, SeriesSummary

router = APIRouter()


def _episode_summary(movie: Movie, stats: dict) -> EpisodeSummary:
    return EpisodeSummary(
        id=movie.id or 0,
        title=movie.title,
        episode_label=movie.episode_label,
        season_number=movie.season_number,
        episode_number=movie.episode_number,
        **stats,
    )


@router.get("/", response_model=list[SeriesSummary])
def list_series(
    library: str | None = Query(None, description="Configured series library ID"),
    session: Session = Depends(get_session),
):
    selected = resolve_library(library, "series") if library else None
    series_list = session.exec(select(Series)).all()
    if selected is not None:
        series_list = [
            series
            for series in series_list
            if series.library_id == selected.id
            or (not series.library_id and path_in_library(selected, series.folder_path))
        ]
    series_list.sort(
        key=lambda series: (
            series.title.lower(),
            -(series.year or 0),
            series.id or 0,
        )
    )

    series_ids = [series.id for series in series_list if series.id is not None]
    episodes_by_series: dict[int, list[Movie]] = {i: [] for i in series_ids}
    episodes: list[Movie] = []
    if series_ids:
        episodes = session.exec(
            select(Movie)
            .where(Movie.kind == MediaKind.episode)
            .where(Movie.series_id.in_(series_ids))
        ).all()
        for episode in episodes:
            episodes_by_series.setdefault(episode.series_id or 0, []).append(episode)

    stats = summarize_items(session, episodes)
    summaries: list[SeriesSummary] = []
    for series in series_list:
        series_episodes = episodes_by_series.get(series.id or 0, [])
        item_stats = [stats.get(episode.id or -1, {}) for episode in series_episodes]
        summaries.append(
            SeriesSummary(
                id=series.id or 0,
                library_id=series.library_id,
                title=series.title,
                year=series.year,
                folder_path=series.folder_path,
                episode_count=len(series_episodes),
                video_count=sum(s.get("video_count", 0) for s in item_stats),
                external_sub_count=sum(
                    s.get("external_sub_count", 0) for s in item_stats
                ),
                external_sub_languages=sorted(
                    {
                        language
                        for s in item_stats
                        for language in s.get("external_sub_languages", [])
                    }
                ),
                unknown_sub_count=sum(
                    s.get("unknown_sub_count", 0) for s in item_stats
                ),
                embedded_sub_count=sum(
                    s.get("embedded_sub_count", 0) for s in item_stats
                ),
                embedded_sub_languages=sorted(
                    {
                        language
                        for s in item_stats
                        for language in s.get("embedded_sub_languages", [])
                    }
                ),
                has_subs=any(s.get("has_subs") for s in item_stats),
            )
        )
    return summaries


@router.get("/{series_id}", response_model=SeriesDetail)
def get_series(series_id: int, session: Session = Depends(get_session)):
    series = session.get(Series, series_id)
    if not series:
        raise HTTPException(404)

    episodes = session.exec(
        select(Movie)
        .where(Movie.kind == MediaKind.episode)
        .where(Movie.series_id == series_id)
    ).all()
    stats = summarize_items(session, episodes)

    numbered = [episode for episode in episodes if episode.episode_number is not None]
    other = [episode for episode in episodes if episode.episode_number is None]
    numbered.sort(
        key=lambda episode: (
            episode.season_number is None,
            episode.season_number or 0,
            episode.episode_number or 0,
            episode.episode_label or "",
            episode.id or 0,
        )
    )
    other.sort(key=lambda episode: (episode.episode_label or "", episode.id or 0))

    groups: dict[int | None, list[EpisodeSummary]] = {}
    for episode in numbered:
        groups.setdefault(episode.season_number, []).append(
            _episode_summary(episode, stats.get(episode.id or -1, {}))
        )

    season_groups = [
        SeasonGroup(season_number=season, episodes=group)
        for season, group in sorted(
            groups.items(), key=lambda item: (item[0] is None, item[0] or 0)
        )
    ]
    return SeriesDetail(
        id=series.id or 0,
        library_id=series.library_id,
        title=series.title,
        year=series.year,
        folder_path=series.folder_path,
        scanned_at=series.scanned_at,
        season_groups=season_groups,
        other_videos=[
            _episode_summary(episode, stats.get(episode.id or -1, {}))
            for episode in other
        ],
    )
