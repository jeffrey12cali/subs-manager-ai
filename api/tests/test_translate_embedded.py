"""Unit tests for do_translate_embedded."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    Job,
    JobStatus,
    JobType,
    Movie,
    SubSource,
    VideoFile,
)
from app.workers.translate_embedded import do_translate_embedded

SRT_CONTENT = """\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:04,000 --> 00:00:06,000
How are you?

"""


def _setup(session: Session, folder: Path, codec: str = "subrip", lang: str = "en"):
    """Create movie + video file + embedded sub + job; write a fake MKV."""
    (folder / "Film (2020).mkv").write_bytes(b"fake")

    movie = Movie(folder_path=str(folder), title="Film", year=2020,
                  scanned_at=datetime.now(timezone.utc))
    session.add(movie)
    session.commit()
    session.refresh(movie)

    vf = VideoFile(
        movie_id=movie.id,
        path=str(folder / "Film (2020).mkv"),
        real_path=str(folder / "Film (2020).mkv"),
        filename="Film (2020).mkv",
        container="mkv",
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)

    emb = EmbeddedSubtitle(
        video_file_id=vf.id, track_index=2, codec=codec, language=lang,
    )
    session.add(emb)
    session.commit()

    job = Job(
        type=JobType.translate_embedded,
        status=JobStatus.queued,
        movie_id=movie.id,
        target_id=vf.id,
        params={
            "video_file_id": vf.id,
            "track_index": 2,
            "target_language": "es",
            "source_language": None,
        },
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return movie, vf, job


def _fake_extract(srt_content: str):
    def _fn(video_path, track_index, out_path, runner=None):  # noqa: ARG001
        out_path.write_text(srt_content)
    return _fn


def _prefix_fn(prefix: str):
    def _fn(lines, target, source_hint, *, api_key, base_url, model):  # noqa: ARG001
        return [f"{prefix}{line}" for line in lines]
    return _fn


# ---- happy path ----

def test_do_translate_embedded_happy_path(tmp_data, session, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    movie, vf, job = _setup(session, folder)

    monkeypatch.setattr("app.workers.translate_embedded.extract_sub_track",
                        _fake_extract(SRT_CONTENT))

    result = do_translate_embedded(
        job.id, session=session,
        translate_fn=_prefix_fn("[ES] "),
    )

    assert result["language"] == "es"
    assert "Film (2020).es.ai.srt" in result["path"]

    new_sub = session.get(ExternalSubtitle, result["sub_id"])
    assert new_sub is not None
    assert new_sub.source == SubSource.translated
    assert new_sub.language == "es"
    assert new_sub.custom_tag == "ai"

    content = Path(result["path"]).read_text()
    assert "[ES] Hello world" in content

    session.refresh(job)
    assert job.status == JobStatus.done
    assert job.progress == 100


def test_do_translate_embedded_creates_extracted_sub_row(tmp_data, session, monkeypatch):
    """An ExternalSubtitle row for the extracted sidecar is created."""
    from sqlmodel import select

    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    movie, vf, job = _setup(session, folder)

    monkeypatch.setattr("app.workers.translate_embedded.extract_sub_track",
                        _fake_extract(SRT_CONTENT))

    do_translate_embedded(job.id, session=session, translate_fn=_prefix_fn(""))

    extracted = session.exec(
        select(ExternalSubtitle).where(ExternalSubtitle.source == SubSource.extracted)
    ).all()
    assert len(extracted) == 1
    assert extracted[0].custom_tag == "extracted"


# ---- error paths ----

def test_do_translate_embedded_missing_track_marks_failed(tmp_data, session):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    (folder / "Film (2020).mkv").write_bytes(b"fake")

    movie = Movie(folder_path=str(folder), title="Film", year=2020)
    session.add(movie)
    session.commit()
    session.refresh(movie)

    vf = VideoFile(
        movie_id=movie.id,
        path=str(folder / "Film (2020).mkv"),
        real_path=str(folder / "Film (2020).mkv"),
        filename="Film (2020).mkv",
        container="mkv",
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)

    job = Job(
        type=JobType.translate_embedded, status=JobStatus.queued,
        movie_id=movie.id, target_id=vf.id,
        params={"video_file_id": vf.id, "track_index": 99,
                "target_language": "es", "source_language": None},
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    with pytest.raises(RuntimeError, match="not found"):
        do_translate_embedded(job.id, session=session, translate_fn=_prefix_fn(""))

    session.refresh(job)
    assert job.status == JobStatus.failed


def test_do_translate_embedded_pgs_codec_marks_failed(tmp_data, session):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)

    movie, vf, _ = _setup(session, folder, codec="hdmv_pgs_subtitle")

    job = Job(
        type=JobType.translate_embedded, status=JobStatus.queued,
        movie_id=movie.id, target_id=vf.id,
        params={"video_file_id": vf.id, "track_index": 2,
                "target_language": "es", "source_language": None},
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    with pytest.raises(RuntimeError, match="not text-based"):
        do_translate_embedded(job.id, session=session, translate_fn=_prefix_fn(""))

    session.refresh(job)
    assert job.status == JobStatus.failed


def test_do_translate_embedded_runner_error_marks_failed(tmp_data, session, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    movie, vf, job = _setup(session, folder)

    def bad_extract(video_path, track_index, out_path, runner=None):  # noqa: ARG001
        raise RuntimeError("mkvextract: disk full")

    monkeypatch.setattr("app.workers.translate_embedded.extract_sub_track", bad_extract)

    with pytest.raises(RuntimeError, match="disk full"):
        do_translate_embedded(job.id, session=session, translate_fn=_prefix_fn(""))

    session.refresh(job)
    assert job.status == JobStatus.failed
    assert "disk full" in (job.error or "")
