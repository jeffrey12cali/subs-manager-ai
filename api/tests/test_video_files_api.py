"""API tests for /video-files extract and embed endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    Movie,
    SubSource,
    VideoFile,
)

# ---- helpers ----

def _movie(session, folder: Path) -> Movie:
    m = Movie(folder_path=str(folder), title="Film", year=2020,
               scanned_at=datetime.utcnow())
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _vf(session, movie: Movie, path: Path, container="mkv") -> VideoFile:
    vf = VideoFile(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, container=container,
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)
    return vf


def _embedded(session, vf: VideoFile, track_index=2, codec="subrip", lang="en") -> EmbeddedSubtitle:
    em = EmbeddedSubtitle(
        video_file_id=vf.id, track_index=track_index,
        codec=codec, language=lang,
    )
    session.add(em)
    session.commit()
    session.refresh(em)
    return em


def _ext_sub(session, movie: Movie, path: Path) -> ExternalSubtitle:
    sub = ExternalSubtitle(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, language="en", language_source="manual",
        format="srt", source=SubSource.manual, created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


# ---- extract endpoint ----

def test_extract_returns_job(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake mkv")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)
    _embedded(session, vf, track_index=2, codec="subrip", lang="en")

    def fake_extract(video_path, track_index, out_path, runner=None):  # noqa: ARG001
        out_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")

    monkeypatch.setattr("app.workers.mkv.extract_sub_track", fake_extract)

    r = client.post(f"/video-files/{vf.id}/extract/2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "extract"
    assert body["status"] == "done"


def test_extract_404_on_missing_vf(client):
    r = client.post("/video-files/9999/extract/0")
    assert r.status_code == 404


def test_extract_422_non_mkv(client, session, tmp_data):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mp4"
    video.write_bytes(b"mp4")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video, container="mp4")

    r = client.post(f"/video-files/{vf.id}/extract/0")
    assert r.status_code == 422


def test_extract_404_on_missing_track(client, session, tmp_data):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)
    # No embedded sub created → track 5 doesn't exist

    r = client.post(f"/video-files/{vf.id}/extract/5")
    assert r.status_code == 404


def test_extract_job_failed_stored_on_runner_error(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)
    _embedded(session, vf, track_index=0, codec="subrip", lang="de")

    def bad_extract(video_path, track_index, out_path, runner=None):  # noqa: ARG001
        raise RuntimeError("mkvextract failed (rc=1): disk full")

    monkeypatch.setattr("app.workers.mkv.extract_sub_track", bad_extract)

    r = client.post(f"/video-files/{vf.id}/extract/0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert "mkvextract failed" in (body["error"] or "")


# ---- embed endpoint ----

def test_embed_returns_job(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"original")
    srt = folder / "Film (2020).en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)
    sub = _ext_sub(session, movie, srt)

    def fake_embed(video_path, sub_path, out_path, language, forced, runner=None):  # noqa: ARG001
        out_path.write_bytes(b"merged")

    monkeypatch.setattr("app.workers.mkv.embed_sub_track", fake_embed)

    r = client.post(f"/video-files/{vf.id}/embed", json={"sub_id": sub.id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "embed"
    assert body["status"] == "done"
    # Original replaced with "merged" content
    assert video.read_bytes() == b"merged"


def test_embed_404_on_missing_vf(client):
    r = client.post("/video-files/9999/embed", json={"sub_id": 1})
    assert r.status_code == 404


def test_embed_422_non_mkv(client, session, tmp_data):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mp4"
    video.write_bytes(b"mp4")
    srt = folder / "Film (2020).en.srt"
    srt.write_text("hello")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video, container="mp4")
    sub = _ext_sub(session, movie, srt)

    r = client.post(f"/video-files/{vf.id}/embed", json={"sub_id": sub.id})
    assert r.status_code == 422


def test_embed_404_on_missing_sub(client, session, tmp_data):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)

    r = client.post(f"/video-files/{vf.id}/embed", json={"sub_id": 9999})
    assert r.status_code == 404


def test_embed_422_sub_different_movie(client, session, tmp_data):
    folder1 = tmp_data / "library" / "Film A (2020)"
    folder1.mkdir(parents=True)
    folder2 = tmp_data / "library" / "Film B (2021)"
    folder2.mkdir(parents=True)
    video = folder1 / "Film A (2020).mkv"
    video.write_bytes(b"fake")
    srt = folder2 / "Film B (2021).en.srt"
    srt.write_text("hello")

    movie1 = _movie(session, folder1)
    movie2 = Movie(folder_path=str(folder2), title="Film B", year=2021,
                   scanned_at=datetime.utcnow())
    session.add(movie2)
    session.commit()
    session.refresh(movie2)

    vf = _vf(session, movie1, video)
    sub = _ext_sub(session, movie2, srt)

    r = client.post(f"/video-files/{vf.id}/embed", json={"sub_id": sub.id})
    assert r.status_code == 422


def test_embed_job_failed_on_runner_error(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"original")
    srt = folder / "Film (2020).en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)
    sub = _ext_sub(session, movie, srt)

    def bad_embed(video_path, sub_path, out_path, language, forced, runner=None):  # noqa: ARG001
        raise RuntimeError("mkvmerge failed (rc=2): codec not supported")

    monkeypatch.setattr("app.workers.mkv.embed_sub_track", bad_embed)

    r = client.post(f"/video-files/{vf.id}/embed", json={"sub_id": sub.id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert "mkvmerge failed" in (body["error"] or "")
    assert video.read_bytes() == b"original"


# ---- translate-embedded endpoint ----

SRT_CONTENT = "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n"


def test_translate_embedded_returns_job(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake mkv")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)
    _embedded(session, vf, track_index=2, codec="subrip", lang="en")

    def fake_extract(video_path, track_index, out_path, runner=None):  # noqa: ARG001
        out_path.write_text(SRT_CONTENT)

    def fake_translate(lines, target, source_hint, *, api_key, base_url, model):  # noqa: ARG001
        return [f"[ES] {line}" for line in lines]

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import app.core.config as cfg
    cfg.settings = cfg.Settings()
    monkeypatch.setattr("app.workers.translate_embedded.extract_sub_track", fake_extract)
    monkeypatch.setattr("app.workers.translate_embedded._default_translate", fake_translate)

    r = client.post(
        f"/video-files/{vf.id}/translate-embedded/2",
        json={"target_language": "es"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "translate_embedded"
    assert body["status"] == "done"


def test_translate_embedded_404_missing_track(client, session, tmp_data):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)

    r = client.post(
        f"/video-files/{vf.id}/translate-embedded/99",
        json={"target_language": "es"},
    )
    assert r.status_code == 404


def test_translate_embedded_422_pgs_codec(client, session, tmp_data):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake")

    movie = _movie(session, folder)
    vf = _vf(session, movie, video)
    _embedded(session, vf, track_index=1, codec="hdmv_pgs_subtitle", lang="en")

    r = client.post(
        f"/video-files/{vf.id}/translate-embedded/1",
        json={"target_language": "es"},
    )
    assert r.status_code == 422
