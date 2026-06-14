"""Cover the ARQ async-enqueue path (Redis available).

Every endpoint that creates a Job tries `arq.create_pool` first and only
falls back to running the job synchronously if that raises. The rest of the
suite exercises the sync fallback (no Redis in the test sandbox); this file
uses the `fake_arq` fixture to make `create_pool` succeed so we exercise the
enqueue branch instead — the Job should stay `queued` and the right task
name/args should be handed to `enqueue_job`.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.models import EmbeddedSubtitle, ExternalSubtitle, Movie, SubSource, VideoFile


def _make_movie(session, folder: Path) -> Movie:
    m = Movie(folder_path=str(folder), title="Film", year=2020, scanned_at=datetime.utcnow())
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _make_vf(session, movie: Movie, path: Path, container="mkv") -> VideoFile:
    vf = VideoFile(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, container=container,
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)
    return vf


def _make_embedded(session, vf: VideoFile, track_index=2, codec="subrip", lang="en") -> EmbeddedSubtitle:
    em = EmbeddedSubtitle(video_file_id=vf.id, track_index=track_index, codec=codec, language=lang)
    session.add(em)
    session.commit()
    session.refresh(em)
    return em


def _make_ext_sub(session, movie: Movie, path: Path, language="en") -> ExternalSubtitle:
    sub = ExternalSubtitle(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, language=language, language_source="manual",
        format="srt", source=SubSource.manual, created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


# ---- library scan ----


def test_scan_enqueues_run_scan_and_stays_queued(client, fake_arq, library_root: Path):
    r = client.post("/library/scan")
    assert r.status_code == 200
    job_ids = r.json()["job_ids"]
    assert len(job_ids) == 1

    job_name, args = fake_arq[0]
    assert job_name == "run_scan"
    assert args == (job_ids[0], str(library_root))
    assert ("aclose", ()) in fake_arq

    job = client.get(f"/jobs/{job_ids[0]}").json()
    assert job["status"] == "queued"


# ---- subs translate ----


def test_translate_enqueues_run_translate(client, session, fake_arq, library_root: Path):
    folder = library_root / "Film (2020)"
    folder.mkdir(parents=True)
    movie = _make_movie(session, folder)
    sub = _make_ext_sub(session, movie, folder / "Film (2020).en.srt", language="en")

    r = client.post(f"/subs/{sub.id}/translate", json={"target_language": "es"})
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == "queued"

    assert ("run_translate", (job["id"],)) in fake_arq


# ---- video-files: extract / embed / transcribe / translate-embedded ----


def test_extract_enqueues_run_extract(client, session, fake_arq, library_root: Path):
    folder = library_root / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake mkv")
    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)
    _make_embedded(session, vf, track_index=2)

    r = client.post(f"/video-files/{vf.id}/extract/2")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert ("run_extract", (job["id"],)) in fake_arq


def test_embed_enqueues_run_embed(client, session, fake_arq, library_root: Path):
    folder = library_root / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"original")
    srt = folder / "Film (2020).en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")
    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)
    sub = _make_ext_sub(session, movie, srt)

    r = client.post(f"/video-files/{vf.id}/embed", json={"sub_id": sub.id})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert ("run_embed", (job["id"],)) in fake_arq
    # Sync path didn't run — video untouched.
    assert video.read_bytes() == b"original"


def test_transcribe_enqueues_run_transcribe(client, session, fake_arq, library_root: Path):
    folder = library_root / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake mkv")
    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)

    r = client.post(f"/video-files/{vf.id}/transcribe")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert ("run_transcribe", (job["id"],)) in fake_arq


def test_translate_embedded_enqueues_run_translate_embedded(
    client, session, fake_arq, library_root: Path
):
    folder = library_root / "Film (2020)"
    folder.mkdir(parents=True)
    video = folder / "Film (2020).mkv"
    video.write_bytes(b"fake mkv")
    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)
    _make_embedded(session, vf, track_index=2, codec="subrip", lang="en")

    r = client.post(
        f"/video-files/{vf.id}/translate-embedded/2",
        json={"target_language": "es"},
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert ("run_translate_embedded", (job["id"],)) in fake_arq
