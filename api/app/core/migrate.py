"""Automatic Alembic migration for container starts.

Both the API and the worker run this before their main process. A file lock in
DATA_DIR serializes the two containers so only one applies the migration.

The database may have been created by an older image that used
``SQLModel.metadata.create_all`` and therefore has no ``alembic_version``
table. For that case we stamp the known baseline revision and let Alembic
upgrade from there. The typed-libraries migration is idempotent so a database
that already has part of the new schema is safe.
"""

from __future__ import annotations

import fcntl
import logging
import os
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.core import config

log = logging.getLogger(__name__)

_BASELINE = "0001_initial"


def _alembic_config() -> Config:
    api_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", config.settings.database_url)
    return cfg


@contextmanager
def _migration_lock():
    data_dir = Path(config.settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".migrate.lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _current_version(engine: sa.Engine) -> str | None:
    with engine.connect() as connection:
        tables = set(sa.inspect(connection).get_table_names())
        if "alembic_version" not in tables:
            return None
        row = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).first()
        return row[0] if row else None


def _tables(engine: sa.Engine) -> set[str]:
    with engine.connect() as connection:
        return set(sa.inspect(connection).get_table_names())


def ensure_schema() -> None:
    """Upgrade an existing or fresh database to the current revision."""
    database_url = config.settings.database_url
    connect_args = (
        {"check_same_thread": False}
        if database_url.startswith("sqlite")
        else {}
    )
    engine = sa.create_engine(database_url, connect_args=connect_args)
    try:
        with _migration_lock():
            version = _current_version(engine)
            tables = _tables(engine)
            cfg = _alembic_config()

            if version is None and "movie" in tables:
                log.warning(
                    "database has tables but no alembic_version; "
                    "stamping baseline %s",
                    _BASELINE,
                )
                command.stamp(cfg, _BASELINE)

            command.upgrade(cfg, "head")
            log.info("database schema is current")
    finally:
        engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s: %(message)s",
    )
    ensure_schema()


if __name__ == "__main__":
    main()
