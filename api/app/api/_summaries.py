from __future__ import annotations

from sqlmodel import Session, select

from app.models import EmbeddedSubtitle, ExternalSubtitle, Movie, VideoFile

EMBEDDED_CODEC_FORMAT = {
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


def summarize_items(
    session: Session, items: list[Movie]
) -> dict[int, dict]:
    """Return sub/video counts for many items with four batched queries."""
    ids = [item.id for item in items if item.id is not None]
    if not ids:
        return {}

    videos = session.exec(
        select(VideoFile).where(VideoFile.movie_id.in_(ids))
    ).all()
    videos_by_movie: dict[int, list[VideoFile]] = {i: [] for i in ids}
    for video in videos:
        videos_by_movie.setdefault(video.movie_id, []).append(video)

    video_ids = [video.id for video in videos if video.id is not None]
    embedded_by_video: dict[int, list[EmbeddedSubtitle]] = {i: [] for i in video_ids}
    if video_ids:
        for embedded in session.exec(
            select(EmbeddedSubtitle).where(
                EmbeddedSubtitle.video_file_id.in_(video_ids)
            )
        ).all():
            embedded_by_video.setdefault(embedded.video_file_id, []).append(
                embedded
            )

    ext_by_movie: dict[int, list[ExternalSubtitle]] = {i: [] for i in ids}
    for sub in session.exec(
        select(ExternalSubtitle).where(ExternalSubtitle.movie_id.in_(ids))
    ).all():
        ext_by_movie.setdefault(sub.movie_id, []).append(sub)

    result: dict[int, dict] = {}
    for item in items:
        if item.id is None:
            continue
        item_videos = videos_by_movie.get(item.id, [])
        ext_subs = ext_by_movie.get(item.id, [])
        all_emb = [
            emb
            for video in item_videos
            for emb in embedded_by_video.get(video.id, [])
        ]
        langs = sorted({s.language for s in ext_subs if s.language})
        unknown_count = sum(1 for s in ext_subs if not s.language)
        emb_langs = sorted({e.language for e in all_emb if e.language})
        has_subs = bool(ext_subs) or bool(all_emb)
        video_formats = sorted({vf.container for vf in item_videos if vf.container})
        subtitle_formats = sorted(
            {s.format for s in ext_subs if s.format}
            | {
                EMBEDDED_CODEC_FORMAT.get(e.codec.lower(), e.codec.lower())
                for e in all_emb
                if e.codec
            }
        )
        result[item.id] = {
            "video_count": len(item_videos),
            "external_sub_count": len(ext_subs),
            "external_sub_languages": langs,
            "unknown_sub_count": unknown_count,
            "embedded_sub_count": len(all_emb),
            "embedded_sub_languages": emb_langs,
            "has_subs": has_subs,
            "video_formats": video_formats,
            "subtitle_formats": subtitle_formats,
        }
    return result
