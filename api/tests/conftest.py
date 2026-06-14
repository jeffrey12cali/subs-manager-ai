"""Shared pytest fixtures.

Every test gets:
- a fresh SQLite DB on disk (so WAL pragmas behave like prod)
- an isolated DATA_DIR + LIBRARY_ROOTS pointing at tmp dirs
- a TestClient with the session dependency overridden to the test engine
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture()
def tmp_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp data dir + library root, plus matching env vars."""
    data = tmp_path / "data"
    library = tmp_path / "library"
    data.mkdir()
    library.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("LIBRARY_ROOTS", str(library))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 'test.db'}")
    # Force config reload by clearing any cached singletons.
    import app.core.config as config_mod

    config_mod.settings = config_mod.Settings()
    return tmp_path


@pytest.fixture()
def engine(tmp_data: Path):
    db_path = tmp_data / "data" / "test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine) -> Generator[Session, None, None]:
    with Session(engine) as s:
        yield s


@pytest.fixture()
def client(engine) -> Generator[TestClient, None, None]:
    """TestClient wired to the per-test engine.

    Also replaces app.core.db.engine so lifespan's init_db() and any code
    that imported the global engine directly both use the test database.
    """
    from app.core import db as db_mod
    from app.main import app

    _real_engine = db_mod.engine
    db_mod.engine = engine  # patch global so init_db() hits test DB

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[db_mod.get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    db_mod.engine = _real_engine  # restore


@pytest.fixture()
def library_root(tmp_data: Path) -> Path:
    return tmp_data / "library"


@pytest.fixture()
def make_movie_folder(library_root: Path):
    """Factory: build a `Title (Year)/` folder with given files inside.

    Files entries: list of (relpath, bytes). Relpath supports subdirs.
    """

    def _make(name: str, files: list[tuple[str, bytes]] | None = None) -> Path:
        folder = library_root / name
        folder.mkdir(parents=True, exist_ok=True)
        for rel, data in files or []:
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return folder

    return _make


@pytest.fixture()
def fake_arq(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple]]:
    """Patch `arq.create_pool` so enqueue endpoints take the async/Redis path.

    Returns the list of (job_name, args) tuples passed to `enqueue_job`.
    Without this, `create_pool` fails to connect (no Redis in tests) and
    every endpoint falls back to running the job synchronously in-process.
    """
    calls: list[tuple[str, tuple]] = []

    class _FakePool:
        async def enqueue_job(self, name, *args, **kwargs):  # noqa: ANN001
            calls.append((name, args))

        async def aclose(self) -> None:
            calls.append(("aclose", ()))

    async def _fake_create_pool(*args, **kwargs):  # noqa: ANN001
        return _FakePool()

    monkeypatch.setattr("arq.create_pool", _fake_create_pool)
    return calls


@pytest.fixture(autouse=True)
def _ensure_clean_env(monkeypatch: pytest.MonkeyPatch):
    """Block accidental writes to real /data or /library during tests."""
    for var in ("DEEPSEEK_API_KEY",):
        monkeypatch.setenv(var, "")
    yield
    # No-op cleanup; tmp_path handles disk.
    _ = os  # silence unused import in some toolchains
