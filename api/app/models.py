from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


class SubSource(StrEnum):
    manual = "manual"
    whisper = "whisper"
    translated = "translated"
    extracted = "extracted"
    preexisting = "preexisting"


class LanguageSource(StrEnum):
    filename = "filename"
    content = "content"
    manual = "manual"
    unknown = "unknown"


class JobType(StrEnum):
    scan = "scan"
    transcribe = "transcribe"
    translate = "translate"
    translate_embedded = "translate_embedded"
    extract = "extract"
    embed = "embed"
    upload = "upload"
    rename = "rename"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class LibraryRoot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(index=True, unique=True)
    name: str
    enabled: bool = True


class Movie(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    folder_path: str = Field(index=True, unique=True)
    title: str
    year: int | None = None
    scanned_at: datetime | None = None

    video_files: list["VideoFile"] = Relationship(back_populates="movie")
    external_subs: list["ExternalSubtitle"] = Relationship(back_populates="movie")


class VideoFile(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movie.id", index=True)
    path: str = Field(index=True)
    real_path: str = Field(index=True)
    is_symlink: bool = False
    filename: str
    variant: str | None = None  # "ESP", "LAT", "EN", or None
    size: int | None = None
    mtime: datetime | None = None
    hash: str | None = Field(default=None, index=True)
    container: str | None = None  # mkv|mp4|avi
    duration: float | None = None
    video_codec: str | None = None
    audio_tracks: list[dict] | None = Field(default=None, sa_column=Column(JSON))

    movie: Movie | None = Relationship(back_populates="video_files")
    embedded_subs: list["EmbeddedSubtitle"] = Relationship(back_populates="video_file")


class ExternalSubtitle(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movie.id", index=True)
    path: str = Field(index=True)
    real_path: str = Field(index=True)
    is_symlink: bool = False
    filename: str
    rel_dir: str = ""  # ""|"subs"|"alt"
    language: str | None = None  # BCP-47, e.g. "en", "es", "es-419"
    language_source: LanguageSource = LanguageSource.unknown
    format: str = "srt"  # srt|ass|vtt
    forced: bool = False
    sdh: bool = False
    custom_tag: str | None = None
    source: SubSource = SubSource.preexisting
    linked_video_file_id: int | None = Field(default=None, foreign_key="videofile.id")
    parent_sub_id: int | None = Field(default=None, foreign_key="externalsubtitle.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    movie: Movie | None = Relationship(back_populates="external_subs")


class EmbeddedSubtitle(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    video_file_id: int = Field(foreign_key="videofile.id", index=True)
    track_index: int
    codec: str  # srt|ass|pgs|vobsub
    language: str | None = None
    title: str | None = None
    default: bool = False
    forced: bool = False

    video_file: VideoFile | None = Relationship(back_populates="embedded_subs")


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: JobType
    status: JobStatus = JobStatus.queued
    movie_id: int | None = Field(default=None, foreign_key="movie.id", index=True)
    target_id: int | None = None  # video_file or sub id, depends on type
    params: dict | None = Field(default=None, sa_column=Column(JSON))
    progress: int = 0
    log: str = ""
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
