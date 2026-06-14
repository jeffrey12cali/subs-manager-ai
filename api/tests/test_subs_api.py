"""Tests for sub upload, delete, patch, and rename endpoints."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pytest

from app.models import ExternalSubtitle, LanguageSource, Movie, SubSource

VALID_SRT = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nWorld\n"
NOT_SRT = b"This is not an SRT file."


def _make_movie(session, folder_path: str, title: str, year: int) -> Movie:
    m = Movie(folder_path=folder_path, title=title, year=year)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _make_sub(
    session,
    movie: Movie,
    filename: str,
    source: SubSource = SubSource.preexisting,
    language: str | None = "en",
    language_source: LanguageSource = LanguageSource.filename,
) -> ExternalSubtitle:
    path = str(Path(movie.folder_path) / filename)
    sub = ExternalSubtitle(
        movie_id=movie.id,
        path=path,
        real_path=path,
        filename=filename,
        language=language,
        language_source=language_source,
        source=source,
        created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


# ================================================================
# LIST
# ================================================================

def test_list_subs_empty(client):
    assert client.get("/subs/").json() == []


def test_list_subs_filtered_by_movie(client, session, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    _make_sub(session, m, "Foo (2024).en.srt")
    _make_sub(session, m, "Foo (2024).es.srt", language="es")

    subs = client.get(f"/subs/?movie_id={m.id}").json()
    assert len(subs) == 2


# ================================================================
# UPLOAD
# ================================================================

def _upload(client, movie_id: int, data: bytes, language: str = "en", **kwargs):
    return client.post(
        f"/movies/{movie_id}/subs/upload",
        data={"language": language, **kwargs},
        files={"file": ("upload.srt", io.BytesIO(data), "text/plain")},
    )


def test_upload_creates_file_and_db_row(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    r = _upload(client, m.id, VALID_SRT, language="en")
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "en"
    assert body["source"] == "manual"
    assert body["language_source"] == "manual"
    assert (folder / "Stalker (1979).en.srt").exists()


def test_upload_forced_flag(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    r = _upload(client, m.id, VALID_SRT, language="es", forced="true")
    assert r.status_code == 200
    assert r.json()["forced"] is True
    assert (folder / "Stalker (1979).es.forced.srt").exists()


def test_upload_sdh_flag(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    r = _upload(client, m.id, VALID_SRT, language="en", sdh="true")
    assert r.status_code == 200
    assert (folder / "Stalker (1979).en.sdh.srt").exists()


def test_upload_custom_tag(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    r = _upload(client, m.id, VALID_SRT, language="es", custom_tag="ai")
    assert r.status_code == 200
    assert r.json()["custom_tag"] == "ai"
    assert (folder / "Stalker (1979).es.ai.srt").exists()


def test_upload_invalid_srt_returns_422(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    r = _upload(client, m.id, NOT_SRT, language="en")
    assert r.status_code == 422


def test_upload_existing_conflict_returns_409(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    _upload(client, m.id, VALID_SRT, language="en")
    r = _upload(client, m.id, VALID_SRT, language="en")  # second upload, same name
    assert r.status_code == 409


def test_upload_force_overwrite_trashes_old(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    # First upload.
    _upload(client, m.id, VALID_SRT, language="en")
    target = folder / "Stalker (1979).en.srt"
    assert target.exists()

    # Force overwrite — old file should go to trash, new written.
    r = _upload(client, m.id, b"1\n00:00:05,000 --> 00:00:06,000\nNew\n",
                language="en", force_overwrite="true")
    assert r.status_code == 200
    assert target.exists()
    assert b"New" in target.read_bytes()


def test_upload_movie_not_found_returns_404(client):
    r = _upload(client, 9999, VALID_SRT, language="en")
    assert r.status_code == 404


def test_upload_filename_path_traversal_is_contained(client, session, library_root: Path):
    """The uploaded filename only supplies the extension — the target path is
    always derived from the movie's own folder, so `../../evil.srt` cannot
    escape the movie folder."""
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    r = client.post(
        f"/movies/{m.id}/subs/upload",
        data={"language": "en"},
        files={"file": ("../../evil.srt", io.BytesIO(VALID_SRT), "text/plain")},
    )
    assert r.status_code == 200
    target = Path(r.json()["path"])
    assert target.parent == folder
    assert target.name == "Stalker (1979).en.srt"
    assert target.exists()


def test_upload_filename_without_extension_defaults_to_srt(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    r = client.post(
        f"/movies/{m.id}/subs/upload",
        data={"language": "fr"},
        files={"file": ("noext", io.BytesIO(VALID_SRT), "text/plain")},
    )
    assert r.status_code == 200
    assert r.json()["format"] == "srt"
    assert (folder / "Stalker (1979).fr.srt").exists()


# ================================================================
# DELETE
# ================================================================

def test_delete_app_owned_sub(client, session, library_root: Path, tmp_data: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)

    # Create an actual file so trash() has something to move.
    sub_path = folder / "Foo (2024).es.srt"
    sub_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHola\n")
    sub = _make_sub(session, m, "Foo (2024).es.srt", source=SubSource.manual, language="es")
    # Point path to real file.
    sub.path = str(sub_path)
    sub.real_path = str(sub_path)
    session.add(sub)
    session.commit()

    r = client.delete(f"/subs/{sub.id}")
    assert r.status_code == 200
    assert not sub_path.exists()

    # File should be in trash.
    trash_dir = tmp_data / "data" / "trash"
    trash_files = list(trash_dir.iterdir())
    assert any("Foo (2024).es.srt" in f.name for f in trash_files)


def test_delete_preexisting_returns_403(client, session, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    sub = _make_sub(session, m, "Foo (2024).en.srt", source=SubSource.preexisting)

    r = client.delete(f"/subs/{sub.id}")
    assert r.status_code == 403
    assert "preexisting" in r.json()["detail"]


def test_delete_missing_returns_404(client):
    assert client.delete("/subs/9999").status_code == 404


def test_delete_missing_file_still_removes_db_row(client, session, library_root: Path):
    """Sub row pointing to a non-existent file should be removable."""
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    sub = _make_sub(session, m, "Foo (2024).es.srt", source=SubSource.whisper, language="es")

    # File doesn't actually exist on disk.
    r = client.delete(f"/subs/{sub.id}")
    assert r.status_code == 200


# ================================================================
# PATCH
# ================================================================

def test_patch_language(client, session, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    sub = _make_sub(session, m, "Foo (2024).srt", language=None,
                    language_source=LanguageSource.unknown)

    r = client.patch(f"/subs/{sub.id}?language=fr")
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "fr"
    assert body["language_source"] == "manual"


def test_patch_forced_flag(client, session, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    sub = _make_sub(session, m, "Foo (2024).en.srt")

    r = client.patch(f"/subs/{sub.id}?forced=true")
    assert r.status_code == 200
    assert r.json()["forced"] is True


def test_patch_sdh_flag(client, session, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    sub = _make_sub(session, m, "Foo (2024).en.srt")

    r = client.patch(f"/subs/{sub.id}?sdh=true")
    assert r.status_code == 200
    assert r.json()["sdh"] is True


def test_patch_custom_tag(client, session, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    sub = _make_sub(session, m, "Foo (2024).es.srt", language="es")

    r = client.patch(f"/subs/{sub.id}?custom_tag=ai")
    assert r.status_code == 200
    assert r.json()["custom_tag"] == "ai"


def test_patch_missing_returns_404(client):
    assert client.patch("/subs/9999?language=en").status_code == 404


# ================================================================
# RENAME
# ================================================================

def test_rename_to_canonical(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    src = folder / "3_English.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    sub = _make_sub(session, m, "3_English.srt", source=SubSource.extracted, language="en")
    sub.path = str(src)
    sub.real_path = str(src)
    session.add(sub)
    session.commit()

    r = client.post(f"/subs/{sub.id}/rename")
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "Stalker (1979).en.srt"
    assert not src.exists()
    assert (folder / "Stalker (1979).en.srt").exists()


def test_rename_already_canonical_is_noop(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)
    sub = _make_sub(session, m, "Stalker (1979).en.srt")

    r = client.post(f"/subs/{sub.id}/rename")
    assert r.status_code == 200
    assert r.json()["filename"] == "Stalker (1979).en.srt"


def test_rename_without_language_returns_422(client, session, library_root: Path):
    folder = library_root / "Foo (2024)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Foo", 2024)
    sub = _make_sub(session, m, "unknown.srt", language=None,
                    language_source=LanguageSource.unknown)

    r = client.post(f"/subs/{sub.id}/rename")
    assert r.status_code == 422


def test_rename_conflict_returns_409(client, session, library_root: Path):
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    # A file with the canonical name already exists.
    canonical = folder / "Stalker (1979).en.srt"
    canonical.write_text("x")
    other_sub = _make_sub(session, m, "Stalker (1979).en.srt")
    other_sub.path = str(canonical)
    other_sub.real_path = str(canonical)
    session.add(other_sub)

    # The sub we're trying to rename.
    src = folder / "3_English.srt"
    src.write_text("y")
    sub = _make_sub(session, m, "3_English.srt", source=SubSource.extracted, language="en")
    sub.path = str(src)
    sub.real_path = str(src)
    session.add(sub)
    session.commit()

    r = client.post(f"/subs/{sub.id}/rename")
    assert r.status_code == 409


def test_rename_missing_returns_404(client):
    assert client.post("/subs/9999/rename").status_code == 404


def test_rename_movie_not_found_returns_404(client, session, engine, library_root: Path):
    """A sub whose movie row has been deleted out from under it (DB inconsistency)."""
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)
    sub = _make_sub(session, m, "3_English.srt", source=SubSource.extracted, language="en")

    # Delete the movie row directly, bypassing the ORM/FK constraint, to
    # simulate a DB left in an inconsistent state.
    import sqlite3

    raw = sqlite3.connect(engine.url.database)
    raw.execute("PRAGMA foreign_keys=OFF")
    raw.execute("DELETE FROM movie WHERE id=?", (m.id,))
    raw.commit()
    raw.close()

    r = client.post(f"/subs/{sub.id}/rename")
    assert r.status_code == 404


def test_rename_source_file_missing_on_disk_returns_404(client, session, library_root: Path):
    """DB row points at a canonical-looking name, but the file is gone from disk."""
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)
    sub = _make_sub(session, m, "3_English.srt", source=SubSource.extracted, language="en")
    sub.path = str(folder / "3_English.srt")
    sub.real_path = sub.path
    session.add(sub)
    session.commit()
    # Note: file was never written to disk.

    r = client.post(f"/subs/{sub.id}/rename")
    assert r.status_code == 404


def test_rename_os_rename_failure_propagates_without_partial_state(
    client, session, library_root: Path, monkeypatch
):
    """Characterizes current behaviour: a failed os.rename (e.g. cross-device
    link) is not caught by the endpoint, so it surfaces as a 500 — and leaves
    the DB row and source file untouched (no partial rename)."""
    folder = library_root / "Stalker (1979)"
    folder.mkdir()
    m = _make_movie(session, str(folder), "Stalker", 1979)

    src = folder / "3_English.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    sub = _make_sub(session, m, "3_English.srt", source=SubSource.extracted, language="en")
    sub.path = str(src)
    sub.real_path = str(src)
    session.add(sub)
    session.commit()

    def bad_rename(_src, _dst):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr("app.api.subs.os.rename", bad_rename)

    with pytest.raises(OSError):
        client.post(f"/subs/{sub.id}/rename")

    session.refresh(sub)
    assert sub.path == str(src)
    assert src.exists()
