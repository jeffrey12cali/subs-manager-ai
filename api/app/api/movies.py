from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.core.db import get_session
from app.models import EmbeddedSubtitle, ExternalSubtitle, Movie, VideoFile
from app.schemas import (
    EmbeddedSubRead,
    ExternalSubRead,
    MovieDetail,
    MovieSummary,
    VideoFileRead,
)

router = APIRouter()

# Normalize ffmpeg/mkvmerge embedded subtitle codec names to the same format
# labels used for external subs (srt|ass|vtt|...).
_EMBEDDED_CODEC_FORMAT = {
    "subrip": "srt",
    "srt": "srt",
    "ass": "ass",
    "ssa": "ass",
    "webvtt": "vtt",
    "vtt": "vtt",
    "hdmv_pgs_subtitle": "pgs",
    "pgs": "pgs",
    "dvd_subtitle": "vobsub",
    "vobsub": "vobsub",
}


@router.get("/", response_model=list[MovieSummary])
def list_movies(
    missing_subs: bool = Query(False, description="Only movies with no subs"),
    session: Session = Depends(get_session),
):
    movies = session.exec(select(Movie).order_by(Movie.title)).all()
    summaries: list[MovieSummary] = []
    for m in movies:
        vfiles = session.exec(select(VideoFile).where(VideoFile.movie_id == m.id)).all()
        ext_subs = session.exec(
            select(ExternalSubtitle).where(ExternalSubtitle.movie_id == m.id)
        ).all()
        all_emb = []
        for vf in vfiles:
            all_emb.extend(
                session.exec(
                    select(EmbeddedSubtitle).where(EmbeddedSubtitle.video_file_id == vf.id)
                ).all()
            )
        emb_count = len(all_emb)
        langs = sorted({s.language for s in ext_subs if s.language})
        unknown_count = sum(1 for s in ext_subs if not s.language)
        emb_langs = sorted({e.language for e in all_emb if e.language})
        has_subs = bool(ext_subs) or emb_count > 0
        if missing_subs and has_subs:
            continue
        video_formats = sorted({vf.container for vf in vfiles if vf.container})
        subtitle_formats = sorted(
            {s.format for s in ext_subs if s.format}
            | {_EMBEDDED_CODEC_FORMAT.get(e.codec.lower(), e.codec.lower()) for e in all_emb if e.codec}
        )
        summaries.append(MovieSummary(
            id=m.id,
            title=m.title,
            year=m.year,
            folder_path=m.folder_path,
            video_count=len(vfiles),
            external_sub_count=len(ext_subs),
            external_sub_languages=langs,
            unknown_sub_count=unknown_count,
            embedded_sub_count=emb_count,
            embedded_sub_languages=emb_langs,
            has_subs=has_subs,
            video_formats=video_formats,
            subtitle_formats=subtitle_formats,
        ))
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

    return MovieDetail(
        id=movie.id,
        folder_path=movie.folder_path,
        title=movie.title,
        year=movie.year,
        scanned_at=movie.scanned_at,
        video_files=vfile_reads,
        external_subs=[ExternalSubRead.model_validate(s) for s in ext_subs],
    )
