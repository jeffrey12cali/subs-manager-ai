from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlmodel import Session, SQLModel, create_engine

import app.core.config as config_mod
from alembic import command
from app.core.migrate import _alembic_config, ensure_schema
from app.models import Movie

HEAD = "0002_typed_libraries_series"


def _use_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(config_mod.settings, "database_url", url)
    monkeypatch.setattr(config_mod.settings, "data_dir", str(data_dir))
    return url


def _version(url: str) -> str | None:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            tables = set(sa.inspect(connection).get_table_names())
            if "alembic_version" not in tables:
                return None
            row = connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).first()
            return row[0] if row else None
    finally:
        engine.dispose()


def _movie_columns(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            return {
                column["name"]
                for column in sa.inspect(connection).get_columns("movie")
            }
    finally:
        engine.dispose()


def test_ensure_schema_fresh_database(tmp_path, monkeypatch):
    url = _use_db(tmp_path, monkeypatch)
    ensure_schema()
    assert _version(url) == HEAD
    assert {"movie", "series"}.issubset(
        set(sa.inspect(sa.create_engine(url)).get_table_names())
    )
    assert "kind" in _movie_columns(url)


def test_ensure_schema_stamps_create_all_database(tmp_path, monkeypatch):
    url = _use_db(tmp_path, monkeypatch)
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Movie(folder_path="/library/Stalker (1979)", title="Stalker", year=1979)
        )
        session.commit()
    engine.dispose()

    ensure_schema()
    assert _version(url) == HEAD

    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                sa.text(
                    "SELECT kind, subtitle_dir, subtitle_stem "
                    "FROM movie WHERE title = 'Stalker'"
                )
            ).one()
            assert tuple(row) == (
                "movie",
                "/library/Stalker (1979)",
                "Stalker (1979)",
            )
    finally:
        engine.dispose()


def test_ensure_schema_upgrades_0001_database(tmp_path, monkeypatch):
    url = _use_db(tmp_path, monkeypatch)
    command.upgrade(_alembic_config(), "0001_initial")

    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO movie (folder_path, title, year, scanned_at) "
                "VALUES (:path, :title, :year, NULL)"
            ),
            {"path": "/library/Foo (2024)", "title": "Foo", "year": 2024},
        )
    engine.dispose()

    ensure_schema()
    assert _version(url) == HEAD
    assert {"kind", "series_id", "subtitle_stem"}.issubset(
        _movie_columns(url)
    )


def test_ensure_schema_handles_partial_new_schema(tmp_path, monkeypatch):
    url = _use_db(tmp_path, monkeypatch)
    command.upgrade(_alembic_config(), "0001_initial")

    # Simulate an old image start: create_all created the missing `series`
    # table, but did not add the new `movie` columns.
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    engine.dispose()

    ensure_schema()
    assert _version(url) == HEAD
    assert "kind" in _movie_columns(url)
