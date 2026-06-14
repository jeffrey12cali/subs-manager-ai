"""API tests for POST /video-files/{id}/transcribe."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.models import Movie, SubSource, VideoFile


def _movie(session, folder: Path) -> Movie:
    m = Movie(folder_path=str(folder), title="Film", year=2020,
               scanned_at=datetime.utcnow())
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _vf(session, movie: Movie, path: Path, container="mkv", duration=120.0) -> VideoFile:
    vf = VideoFile(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, container=container, duration=duration,
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)
    return vf


def _seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def _fake_transcribe(segs, detected_lang):
    def _fn(video_path, *, model_size, compute_type, vad, language):  # noqa: ARG001
        return iter(segs), detected_lang
    return _fn


# ---- happy path ----

def test_transcribe_returns_done_job(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)

    monkeypatch.setattr(
        "app.workers.transcribe._default_transcribe",
        _fake_transcribe([_seg(0.0, 2.0, "Hello")], "en"),
    )

    r = client.post(f"/video-files/{vf.id}/transcribe")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "transcribe"
    assert body["status"] == "done"


def test_transcribe_creates_srt_file(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)

    segs = [_seg(0.0, 1.5, "Subtitle text")]
    monkeypatch.setattr(
        "app.workers.transcribe._default_transcribe",
        _fake_transcribe(segs, "fr"),
    )

    r = client.post(f"/video-files/{vf.id}/transcribe")
    assert r.status_code == 200
    srt = folder / "Film (2020).fr.whisper.srt"
    assert srt.exists()
    assert "Subtitle text" in srt.read_text()


def test_transcribe_with_explicit_language(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)

    monkeypatch.setattr(
        "app.workers.transcribe._default_transcribe",
        _fake_transcribe([_seg(0.0, 1.0, "Hola")], "en"),  # detected "en" but overridden
    )

    r = client.post(f"/video-files/{vf.id}/transcribe?language=es")
    assert r.status_code == 200
    srt = folder / "Film (2020).es.whisper.srt"
    assert srt.exists()


# ---- validation ----

def test_transcribe_404_on_missing_vf(client):
    r = client.post("/video-files/9999/transcribe")
    assert r.status_code == 404


def test_transcribe_any_container_accepted(client, session, tmp_data, monkeypatch):
    """Unlike extract/embed, transcribe works on mp4, avi, etc."""
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mp4"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video, container="mp4")

    monkeypatch.setattr(
        "app.workers.transcribe._default_transcribe",
        _fake_transcribe([_seg(0.0, 1.0, "Hello")], "en"),
    )

    r = client.post(f"/video-files/{vf.id}/transcribe")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done"


# ---- failure path ----

def test_transcribe_job_failed_on_error(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)

    def bad_transcribe(video_path, *, model_size, compute_type, vad, language):  # noqa: ARG001
        raise RuntimeError("model load failed")

    monkeypatch.setattr("app.workers.transcribe._default_transcribe", bad_transcribe)

    r = client.post(f"/video-files/{vf.id}/transcribe")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert "model load failed" in (body["error"] or "")


def test_transcribe_idempotent_second_run(client, session, tmp_data, monkeypatch):
    """Running transcribe twice replaces the old sub row."""
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)

    monkeypatch.setattr(
        "app.workers.transcribe._default_transcribe",
        _fake_transcribe([_seg(0.0, 1.0, "First run")], "en"),
    )
    client.post(f"/video-files/{vf.id}/transcribe")

    monkeypatch.setattr(
        "app.workers.transcribe._default_transcribe",
        _fake_transcribe([_seg(0.0, 1.0, "Second run")], "en"),
    )
    r = client.post(f"/video-files/{vf.id}/transcribe")
    assert r.status_code == 200

    srt = folder / "Film (2020).en.whisper.srt"
    assert "Second run" in srt.read_text()

    from sqlmodel import Session as S
    from sqlmodel import select

    from app.core import db as db_mod
    from app.models import ExternalSubtitle

    with S(db_mod.engine) as s:
        rows = s.exec(
            select(ExternalSubtitle)
            .where(ExternalSubtitle.movie_id == movie.id)
            .where(ExternalSubtitle.source == SubSource.whisper)
        ).all()
    assert len(rows) == 1  # no duplicate
