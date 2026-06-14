"""Pydantic read-models for API responses.

SQLModel table classes carry SQLAlchemy `Mapped[...]` relationship annotations
that Pydantic cannot serialise. These plain BaseModel classes mirror the data
we want to expose without inheriting from the table models.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator

from app.models import JobStatus, JobType, LanguageSource, SubSource


def _ensure_utc(v: Any) -> Any:
    """Attach UTC tzinfo to naive datetimes coming back from SQLite."""
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


AwareDatetime = Annotated[datetime, BeforeValidator(_ensure_utc)]


class EmbeddedSubRead(BaseModel):
    id: int | None = None
    video_file_id: int
    track_index: int
    codec: str
    language: str | None = None
    title: str | None = None
    default: bool = False
    forced: bool = False

    model_config = {"from_attributes": True}


class ExternalSubRead(BaseModel):
    id: int | None = None
    movie_id: int
    path: str
    filename: str
    rel_dir: str = ""
    language: str | None = None
    language_source: LanguageSource = LanguageSource.unknown
    format: str = "srt"
    forced: bool = False
    sdh: bool = False
    custom_tag: str | None = None
    source: SubSource = SubSource.preexisting
    linked_video_file_id: int | None = None
    parent_sub_id: int | None = None
    created_at: AwareDatetime

    model_config = {"from_attributes": True}


class VideoFileRead(BaseModel):
    id: int | None = None
    movie_id: int
    path: str
    real_path: str
    is_symlink: bool = False
    filename: str
    variant: str | None = None
    size: int | None = None
    mtime: AwareDatetime | None = None
    hash: str | None = None
    container: str | None = None
    duration: float | None = None
    video_codec: str | None = None
    audio_tracks: list[dict[str, Any]] | None = None
    embedded_subs: list[EmbeddedSubRead] = []

    model_config = {"from_attributes": True}


class MovieDetail(BaseModel):
    id: int | None = None
    folder_path: str
    title: str
    year: int | None = None
    scanned_at: AwareDatetime | None = None
    video_files: list[VideoFileRead] = []
    external_subs: list[ExternalSubRead] = []

    model_config = {"from_attributes": True}


class MovieSummary(BaseModel):
    id: int
    title: str
    year: int | None
    folder_path: str
    video_count: int
    external_sub_count: int
    external_sub_languages: list[str]
    unknown_sub_count: int
    embedded_sub_count: int
    embedded_sub_languages: list[str]
    has_subs: bool

    model_config = {"from_attributes": True}


class JobRead(BaseModel):
    id: int | None = None
    type: JobType
    status: JobStatus
    movie_id: int | None = None
    target_id: int | None = None
    params: dict[str, Any] | None = None
    progress: int = 0
    log: str = ""
    error: str | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    created_at: AwareDatetime

    model_config = {"from_attributes": True}
