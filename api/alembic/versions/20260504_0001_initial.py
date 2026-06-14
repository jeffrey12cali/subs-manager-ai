"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-04

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "libraryroot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sqlmodel.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.AutoString(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("path"),
    )
    op.create_index("ix_libraryroot_path", "libraryroot", ["path"])

    op.create_table(
        "movie",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("folder_path", sqlmodel.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.AutoString(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("folder_path"),
    )
    op.create_index("ix_movie_folder_path", "movie", ["folder_path"])

    op.create_table(
        "videofile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movie.id"), nullable=False),
        sa.Column("path", sqlmodel.AutoString(), nullable=False),
        sa.Column("real_path", sqlmodel.AutoString(), nullable=False),
        sa.Column("is_symlink", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("filename", sqlmodel.AutoString(), nullable=False),
        sa.Column("variant", sqlmodel.AutoString(), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("mtime", sa.DateTime(), nullable=True),
        sa.Column("hash", sqlmodel.AutoString(), nullable=True),
        sa.Column("container", sqlmodel.AutoString(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("video_codec", sqlmodel.AutoString(), nullable=True),
        sa.Column("audio_tracks", sa.JSON(), nullable=True),
    )
    op.create_index("ix_videofile_movie_id", "videofile", ["movie_id"])
    op.create_index("ix_videofile_path", "videofile", ["path"])
    op.create_index("ix_videofile_real_path", "videofile", ["real_path"])
    op.create_index("ix_videofile_hash", "videofile", ["hash"])

    op.create_table(
        "externalsubtitle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movie.id"), nullable=False),
        sa.Column("path", sqlmodel.AutoString(), nullable=False),
        sa.Column("real_path", sqlmodel.AutoString(), nullable=False),
        sa.Column("is_symlink", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("filename", sqlmodel.AutoString(), nullable=False),
        sa.Column("rel_dir", sqlmodel.AutoString(), nullable=False, server_default=""),
        sa.Column("language", sqlmodel.AutoString(), nullable=True),
        sa.Column("language_source", sqlmodel.AutoString(), nullable=False, server_default="unknown"),
        sa.Column("format", sqlmodel.AutoString(), nullable=False, server_default="srt"),
        sa.Column("forced", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sdh", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("custom_tag", sqlmodel.AutoString(), nullable=True),
        sa.Column("source", sqlmodel.AutoString(), nullable=False, server_default="preexisting"),
        sa.Column("linked_video_file_id", sa.Integer(), sa.ForeignKey("videofile.id"), nullable=True),
        sa.Column("parent_sub_id", sa.Integer(), sa.ForeignKey("externalsubtitle.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_externalsubtitle_movie_id", "externalsubtitle", ["movie_id"])
    op.create_index("ix_externalsubtitle_path", "externalsubtitle", ["path"])
    op.create_index("ix_externalsubtitle_real_path", "externalsubtitle", ["real_path"])

    op.create_table(
        "embeddedsubtitle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_file_id", sa.Integer(), sa.ForeignKey("videofile.id"), nullable=False),
        sa.Column("track_index", sa.Integer(), nullable=False),
        sa.Column("codec", sqlmodel.AutoString(), nullable=False),
        sa.Column("language", sqlmodel.AutoString(), nullable=True),
        sa.Column("title", sqlmodel.AutoString(), nullable=True),
        sa.Column("default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("forced", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_embeddedsubtitle_video_file_id", "embeddedsubtitle", ["video_file_id"])

    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sqlmodel.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.AutoString(), nullable=False, server_default="queued"),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movie.id"), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("log", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_job_movie_id", "job", ["movie_id"])

    op.create_table(
        "setting",
        sa.Column("key", sqlmodel.AutoString(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("setting")
    op.drop_index("ix_job_movie_id", table_name="job")
    op.drop_table("job")
    op.drop_index("ix_embeddedsubtitle_video_file_id", table_name="embeddedsubtitle")
    op.drop_table("embeddedsubtitle")
    op.drop_index("ix_externalsubtitle_real_path", table_name="externalsubtitle")
    op.drop_index("ix_externalsubtitle_path", table_name="externalsubtitle")
    op.drop_index("ix_externalsubtitle_movie_id", table_name="externalsubtitle")
    op.drop_table("externalsubtitle")
    op.drop_index("ix_videofile_hash", table_name="videofile")
    op.drop_index("ix_videofile_real_path", table_name="videofile")
    op.drop_index("ix_videofile_path", table_name="videofile")
    op.drop_index("ix_videofile_movie_id", table_name="videofile")
    op.drop_table("videofile")
    op.drop_index("ix_movie_folder_path", table_name="movie")
    op.drop_table("movie")
    op.drop_index("ix_libraryroot_path", table_name="libraryroot")
    op.drop_table("libraryroot")
