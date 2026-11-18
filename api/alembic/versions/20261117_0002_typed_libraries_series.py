"""typed libraries and series

Revision ID: 0002_typed_libraries_series
Revises: 0001_initial
Create Date: 2026-11-17

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_typed_libraries_series"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if "series" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "series",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("library_id", sa.String(), nullable=False),
            sa.Column("folder_path", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("scanned_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("folder_path"),
        )

    series_indexes = _indexes(bind, "series")
    if "ix_series_library_id" not in series_indexes:
        op.create_index("ix_series_library_id", "series", ["library_id"])
    if "ix_series_folder_path" not in series_indexes:
        op.create_index("ix_series_folder_path", "series", ["folder_path"])

    movie_columns = _columns(bind, "movie")
    additions: list[sa.Column] = []
    if "kind" not in movie_columns:
        additions.append(
            sa.Column(
                "kind",
                sa.String(),
                nullable=False,
                server_default="movie",
            )
        )
    if "library_id" not in movie_columns:
        additions.append(sa.Column("library_id", sa.String(), nullable=True))
    if "series_id" not in movie_columns:
        additions.append(
            sa.Column(
                "series_id",
                sa.Integer(),
                sa.ForeignKey("series.id", name="fk_movie_series_id"),
                nullable=True,
            )
        )
    if "season_number" not in movie_columns:
        additions.append(sa.Column("season_number", sa.Integer(), nullable=True))
    if "episode_number" not in movie_columns:
        additions.append(sa.Column("episode_number", sa.Integer(), nullable=True))
    if "episode_label" not in movie_columns:
        additions.append(sa.Column("episode_label", sa.String(), nullable=True))
    if "subtitle_dir" not in movie_columns:
        additions.append(sa.Column("subtitle_dir", sa.String(), nullable=True))
    if "subtitle_stem" not in movie_columns:
        additions.append(sa.Column("subtitle_stem", sa.String(), nullable=True))

    if additions:
        with op.batch_alter_table("movie") as batch_op:
            for column in additions:
                batch_op.add_column(column)

    movie_indexes = _indexes(bind, "movie")
    if "ix_movie_kind" not in movie_indexes:
        op.create_index("ix_movie_kind", "movie", ["kind"])
    if "ix_movie_library_id" not in movie_indexes:
        op.create_index("ix_movie_library_id", "movie", ["library_id"])
    if "ix_movie_series_id" not in movie_indexes:
        op.create_index("ix_movie_series_id", "movie", ["series_id"])

    op.execute("UPDATE movie SET kind = 'movie' WHERE kind IS NULL OR kind = ''")
    op.execute(
        "UPDATE movie SET subtitle_dir = folder_path "
        "WHERE subtitle_dir IS NULL"
    )
    op.execute(
        "UPDATE movie SET subtitle_stem = "
        "CASE WHEN year IS NULL THEN title "
        "ELSE title || ' (' || year || ')' END "
        "WHERE subtitle_stem IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("movie") as batch_op:
        batch_op.drop_index("ix_movie_series_id")
        batch_op.drop_index("ix_movie_library_id")
        batch_op.drop_index("ix_movie_kind")
        batch_op.drop_column("subtitle_stem")
        batch_op.drop_column("subtitle_dir")
        batch_op.drop_column("episode_label")
        batch_op.drop_column("episode_number")
        batch_op.drop_column("season_number")
        batch_op.drop_column("series_id")
        batch_op.drop_column("library_id")
        batch_op.drop_column("kind")

    op.drop_index("ix_series_folder_path", table_name="series")
    op.drop_index("ix_series_library_id", table_name="series")
    op.drop_table("series")
