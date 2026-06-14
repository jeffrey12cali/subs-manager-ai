"""Tests for Whisper transcription — pure functions and core logic."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from app.models import (
    ExternalSubtitle,
    Job,
    JobStatus,
    JobType,
    Movie,
    SubSource,
    VideoFile,
)
from app.workers.transcribe import _fmt_ts, do_transcribe, segments_to_srt

# ---- _fmt_ts ----

def test_fmt_ts_zero():
    assert _fmt_ts(0.0) == "00:00:00,000"


def test_fmt_ts_minutes():
    assert _fmt_ts(90.5) == "00:01:30,500"


def test_fmt_ts_hours():
    assert _fmt_ts(3661.25) == "01:01:01,250"


def test_fmt_ts_sub_second():
    assert _fmt_ts(1.001) == "00:00:01,001"


# ---- segments_to_srt ----

def _seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def test_segments_to_srt_basic():
    segs = [_seg(0.0, 2.0, "Hello"), _seg(3.0, 5.5, "  World  ")]
    result = segments_to_srt(segs)
    assert "1\n" in result
    assert "00:00:00,000 --> 00:00:02,000" in result
    assert "Hello" in result
    assert "2\n" in result
    assert "00:00:03,000 --> 00:00:05,500" in result
    assert "World" in result  # strip applied


def test_segments_to_srt_empty():
    assert segments_to_srt([]) == ""


def test_segments_to_srt_whitespace_stripped():
    segs = [_seg(0.0, 1.0, "  trailing  ")]
    result = segments_to_srt(segs)
    assert "trailing" in result
    assert "  trailing  " not in result


# ---- do_transcribe helpers ----

def _make_movie(session: Session, folder: Path) -> Movie:
    m = Movie(folder_path=str(folder), title="Test Film", year=2021,
               scanned_at=datetime.utcnow())
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _make_vf(session: Session, movie: Movie, path: Path, duration: float = 120.0) -> VideoFile:
    vf = VideoFile(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, container="mkv", duration=duration,
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)
    return vf


def _make_job(session: Session, vf: VideoFile, movie: Movie, language=None) -> Job:
    job = Job(
        type=JobType.transcribe,
        status=JobStatus.queued,
        movie_id=movie.id,
        target_id=vf.id,
        params={"video_file_id": vf.id, "language": language},
        created_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _fake_transcribe(segs, detected_lang):
    """Return a transcribe_fn that yields segs and reports detected_lang."""
    def _fn(video_path, *, model_size, compute_type, vad, language):  # noqa: ARG001
        return iter(segs), detected_lang
    return _fn


# ---- do_transcribe happy path ----

def test_do_transcribe_creates_sub(tmp_data, session):
    folder = tmp_data / "library" / "Test Film (2021)"
    folder.mkdir(parents=True)
    video = folder / "Test Film (2021).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)
    job = _make_job(session, vf, movie)

    segs = [_seg(0.0, 2.0, "Hello"), _seg(2.5, 4.0, "World")]
    result = do_transcribe(job.id, session=session,
                           transcribe_fn=_fake_transcribe(segs, "en"))

    assert result["language"] == "en"
    assert "Test Film (2021).en.whisper.srt" in result["path"]
    assert result["sub_id"] is not None

    sub = session.get(ExternalSubtitle, result["sub_id"])
    assert sub is not None
    assert sub.source == SubSource.whisper
    assert sub.language == "en"
    assert sub.custom_tag == "whisper"
    assert sub.language_source.value == "content"

    out = Path(result["path"])
    assert out.exists()
    content = out.read_text()
    assert "Hello" in content
    assert "World" in content
    assert "00:00:00,000 --> 00:00:02,000" in content

    session.refresh(job)
    assert job.status == JobStatus.done
    assert job.progress == 100


def test_do_transcribe_with_explicit_language(tmp_data, session):
    """Explicit language param overrides auto-detection."""
    folder = tmp_data / "library" / "Test Film (2021)"
    folder.mkdir(parents=True)
    video = folder / "Test Film (2021).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)
    job = _make_job(session, vf, movie, language="es")

    segs = [_seg(0.0, 1.0, "Hola")]
    result = do_transcribe(job.id, session=session,
                           transcribe_fn=_fake_transcribe(segs, "en"))  # detected="en" ignored

    assert result["language"] == "es"
    assert "es.whisper" in result["path"]


def test_do_transcribe_unknown_language_falls_back_to_und(tmp_data, session):
    """If whisper detects nothing and no language given → 'und' in path."""
    folder = tmp_data / "library" / "Test Film (2021)"
    folder.mkdir(parents=True)
    video = folder / "Test Film (2021).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)
    job = _make_job(session, vf, movie)

    segs = [_seg(0.0, 1.0, "?")]
    result = do_transcribe(job.id, session=session,
                           transcribe_fn=_fake_transcribe(segs, ""))

    assert result["language"] == "und"
    assert ".und.whisper" in result["path"]
    sub = session.get(ExternalSubtitle, result["sub_id"])
    assert sub is not None
    assert sub.language is None  # "und" stored as None in DB


def test_do_transcribe_progress_updates(tmp_data, session):
    """Progress is written to job as segments arrive."""
    folder = tmp_data / "library" / "Test Film (2021)"
    folder.mkdir(parents=True)
    video = folder / "Test Film (2021).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    # duration=100s; segment at 60s → 60% progress written
    vf = _make_vf(session, movie, video, duration=100.0)
    job = _make_job(session, vf, movie)

    # One segment at 60s to trigger the 5% threshold
    segs = [_seg(0.0, 60.0, "Progress test")]
    do_transcribe(job.id, session=session,
                  transcribe_fn=_fake_transcribe(segs, "en"))

    session.refresh(job)
    assert job.status == JobStatus.done
    # Progress log should mention the intermediate timestamp
    assert "60.0s" in job.log


def test_do_transcribe_overwrites_existing_whisper_sub(tmp_data, session):
    """Re-transcribing same language replaces old ExternalSubtitle row."""
    folder = tmp_data / "library" / "Test Film (2021)"
    folder.mkdir(parents=True)
    video = folder / "Test Film (2021).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)

    # Pre-existing whisper sub (different path simulates old naming convention).
    old_path = str(folder / "old.en.whisper.srt")
    old_sub = ExternalSubtitle(
        movie_id=movie.id, path=old_path, real_path=old_path,
        filename="old.en.whisper.srt", language="en",
        language_source="content", format="srt",
        source=SubSource.whisper, custom_tag="whisper",
        created_at=datetime.utcnow(),
    )
    session.add(old_sub)
    session.commit()

    from sqlmodel import select as _select

    job = _make_job(session, vf, movie)
    segs = [_seg(0.0, 1.0, "New")]
    result = do_transcribe(job.id, session=session,
                           transcribe_fn=_fake_transcribe(segs, "en"))

    # Only one whisper sub for "en" should remain.
    rows = session.exec(
        _select(ExternalSubtitle)
        .where(ExternalSubtitle.movie_id == movie.id)
        .where(ExternalSubtitle.source == SubSource.whisper)
        .where(ExternalSubtitle.language == "en")
    ).all()
    assert len(rows) == 1
    assert rows[0].id == result["sub_id"]
    assert "New" in Path(result["path"]).read_text()


# ---- do_transcribe error paths ----

def test_do_transcribe_missing_vf(tmp_data, session):
    """Job with nonexistent video_file_id → job fails."""
    folder = tmp_data / "library" / "Test Film (2021)"
    folder.mkdir(parents=True)
    movie = _make_movie(session, folder)

    job = Job(
        type=JobType.transcribe, status=JobStatus.queued,
        movie_id=movie.id, target_id=9999,
        params={"video_file_id": 9999, "language": None},
        created_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    with pytest.raises(RuntimeError, match="VideoFile 9999 not found"):
        do_transcribe(job.id, session=session,
                      transcribe_fn=_fake_transcribe([], "en"))

    session.refresh(job)
    assert job.status == JobStatus.failed


def test_do_transcribe_transcribe_fn_raises(tmp_data, session):
    """If transcribe_fn raises, job is marked failed."""
    folder = tmp_data / "library" / "Test Film (2021)"
    folder.mkdir(parents=True)
    video = folder / "Test Film (2021).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_vf(session, movie, video)
    job = _make_job(session, vf, movie)

    def bad_fn(video_path, *, model_size, compute_type, vad, language):  # noqa: ARG001
        raise RuntimeError("CUDA out of memory")

    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        do_transcribe(job.id, session=session, transcribe_fn=bad_fn)

    session.refresh(job)
    assert job.status == JobStatus.failed
    assert "CUDA out of memory" in (job.error or "")
