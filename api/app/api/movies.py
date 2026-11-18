from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api._summaries import summarize_items
from app.api.libraries import path_in_library, resolve_library
from app.core.db import get_session
from app.models import EmbeddedSubtitle, ExternalSubtitle, MediaKind, Movie, Series, VideoFile
from app.schemas import (
    EmbeddedSubRead,
    ExternalSubRead,
    MovieDetail,
    MovieSummary,
    VideoFileRead,
)

router = APIRouter()


@router.get("/", response_model=list[MovieSummary])
def list_movies(
    missing_subs: bool = Query(False, description="Only movies with no subs"),
    library: str | None = Query(None, description="Configured movies library ID"),
    session: Session = Depends(get_session),
):
    selected = resolve_library(library, "movies") if library else None
    movies = session.exec(
        select(Movie).where(Movie.kind == MediaKind.movie).order_by(Movie.title)
    ).all()
    if selected is not None:
        movies = [
            movie
            for movie in movies
            if movie.library_id == selected.id
            or (movie.library_id is None and path_in_library(selected, movie.folder_path))
        ]

    stats = summarize_items(session, movies)
    summaries: list[MovieSummary] = []
    for movie in movies:
        item_stats = stats.get(movie.id or -1, {})
        if missing_subs and item_stats.get("has_subs"):
            continue
        summaries.append(
            MovieSummary(
                id=movie.id,
                title=movie.title,
                year=movie.year,
                folder_path=movie.folder_path,
                kind=movie.kind,
                library_id=movie.library_id,
                season_number=movie.season_number,
                episode_number=movie.episode_number,
                episode_label=movie.episode_label,
                **item_stats,
            )
        )
    return summaries


@router.get("/{movie_id}", response_model=MovieDetail)
def get_movie(movie_id: int, session: Session = Depends(get_session)):
    movie = session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(404)

    vfiles = session.exec(select(VideoFile).where(VideoFile.movie_id == movie_id)).all()
    vfile_reads: list[VideoFileRead] = []
    for vf in vfiles:
        emb = session.exec(
            select(EmbeddedSubtitle).where(EmbeddedSubtitle.video_file_id == vf.id)
        ).all()
        vr = VideoFileRead.model_validate(vf)
        vr.embedded_subs = [EmbeddedSubRead.model_validate(e) for e in emb]
        vfile_reads.append(vr)

    ext_subs = session.exec(
        select(ExternalSubtitle).where(ExternalSubtitle.movie_id == movie_id)
    ).all()

    series_title = None
    if movie.series_id is not None:
        series = session.get(Series, movie.series_id)
        series_title = series.title if series else None

    return MovieDetail(
        id=movie.id,
        folder_path=movie.folder_path,
        title=movie.title,
        year=movie.year,
        kind=movie.kind,
        library_id=movie.library_id,
        series_id=movie.series_id,
        series_title=series_title,
        season_number=movie.season_number,
        episode_number=movie.episode_number,
        episode_label=movie.episode_label,
        scanned_at=movie.scanned_at,
        video_files=vfile_reads,
        external_subs=[ExternalSubRead.model_validate(s) for s in ext_subs],
    )
