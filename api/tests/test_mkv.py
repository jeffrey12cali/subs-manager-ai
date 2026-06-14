"""Unit tests for MKV extract/embed pure functions and core logic."""

from __future__ import annotations

from datetime import datetime
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
from app.workers.mkv import (
    _CODEC_TO_EXT,
    do_embed,
    do_extract,
    embed_sub_track,
    extract_sub_track,
)

# ---- pure function tests ----

def test_extract_sub_track_calls_mkvextract():
    calls = []

    def fake_runner(cmd):
        calls.append(cmd)
        return 0, "", ""

    extract_sub_track(Path("/foo/video.mkv"), 2, Path("/foo/out.srt"), runner=fake_runner)
    assert calls == [["mkvextract", "tracks", "/foo/video.mkv", "2:/foo/out.srt"]]


def test_extract_sub_track_raises_on_nonzero():
    def bad_runner(cmd):  # noqa: ARG001
        return 1, "", "bad track"

    with pytest.raises(RuntimeError, match="mkvextract failed"):
        extract_sub_track(Path("/a.mkv"), 0, Path("/out.srt"), runner=bad_runner)


def test_embed_sub_track_calls_mkvmerge():
    calls = []

    def fake_runner(cmd):
        calls.append(cmd)
        return 0, "", ""

    embed_sub_track(
        Path("/v.mkv"), Path("/s.srt"), Path("/out.mkv"),
        language="en", forced=True, runner=fake_runner,
    )
    assert calls[0][:4] == ["mkvmerge", "-o", "/out.mkv", "/v.mkv"]
    assert "--language" in calls[0]
    assert "0:en" in calls[0]
    assert "--forced-track" in calls[0]


def test_embed_sub_track_no_language_no_flag():
    calls = []

    def fake_runner(cmd):
        calls.append(cmd)
        return 0, "", ""

    embed_sub_track(
        Path("/v.mkv"), Path("/s.srt"), Path("/out.mkv"),
        language=None, forced=False, runner=fake_runner,
    )
    assert "--language" not in calls[0]
    assert "--forced-track" not in calls[0]


def test_embed_sub_track_rc1_is_ok():
    """mkvmerge rc=1 means warnings — should not raise."""
    def warn_runner(cmd):  # noqa: ARG001
        return 1, "warnings", ""

    embed_sub_track(
        Path("/v.mkv"), Path("/s.srt"), Path("/out.mkv"),
        language="en", forced=False, runner=warn_runner,
    )


def test_embed_sub_track_rc2_raises():
    def err_runner(cmd):  # noqa: ARG001
        return 2, "", "fatal"

    with pytest.raises(RuntimeError, match="mkvmerge failed"):
        embed_sub_track(
            Path("/v.mkv"), Path("/s.srt"), Path("/out.mkv"),
            language="en", forced=False, runner=err_runner,
        )


def test_codec_to_ext_coverage():
    assert _CODEC_TO_EXT["subrip"] == "srt"
    assert _CODEC_TO_EXT["ass"] == "ass"
    assert _CODEC_TO_EXT["hdmv_pgs_subtitle"] == "sup"


# ---- do_extract logic tests ----

def _make_movie(session: Session, folder: Path) -> Movie:
    movie = Movie(
        folder_path=str(folder),
        title="Test Movie",
        year=2020,
        scanned_at=datetime.utcnow(),
    )
    session.add(movie)
    session.commit()
    session.refresh(movie)
    return movie


def _make_video_file(session: Session, movie: Movie, path: Path) -> VideoFile:
    vf = VideoFile(
        movie_id=movie.id,
        path=str(path),
        real_path=str(path),
        filename=path.name,
        container="mkv",
        duration=7200.0,
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)
    return vf


def _make_embedded(
    session: Session, vf: VideoFile, track_index: int, codec="subrip", lang="en", forced=False
) -> EmbeddedSubtitle:
    em = EmbeddedSubtitle(
        video_file_id=vf.id,
        track_index=track_index,
        codec=codec,
        language=lang,
        forced=forced,
    )
    session.add(em)
    session.commit()
    session.refresh(em)
    return em


def _make_job(session: Session, job_type: JobType, movie_id: int, target_id: int, params: dict) -> Job:
    job = Job(
        type=job_type,
        status=JobStatus.queued,
        movie_id=movie_id,
        target_id=target_id,
        params=params,
        created_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_do_extract_creates_external_sub(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"fake mkv")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)
    _make_embedded(session, vf, track_index=2, codec="subrip", lang="en")

    def fake_runner(cmd):
        # cmd[-1] = "2:/path/to/out.srt" — create the output file
        out_spec = cmd[-1]
        out_path = Path(out_spec.split(":", 1)[1])
        out_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")
        return 0, "", ""

    job = _make_job(session, JobType.extract, movie.id, vf.id,
                    {"video_file_id": vf.id, "track_index": 2})
    result = do_extract(job.id, session=session, runner=fake_runner)

    assert result["sub_id"] is not None
    assert "Test Movie (2020).en.extracted.srt" in result["path"]

    sub = session.get(ExternalSubtitle, result["sub_id"])
    assert sub is not None
    assert sub.source == SubSource.extracted
    assert sub.language == "en"
    assert sub.linked_video_file_id == vf.id

    session.refresh(job)
    assert job.status == JobStatus.done
    assert job.progress == 100


def test_do_extract_fails_on_missing_track(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)

    job = _make_job(session, JobType.extract, movie.id, vf.id,
                    {"video_file_id": vf.id, "track_index": 99})

    with pytest.raises(RuntimeError, match="Embedded track 99 not found"):
        do_extract(job.id, session=session)

    session.refresh(job)
    assert job.status == JobStatus.failed


def test_do_extract_job_failed_on_runner_error(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)
    _make_embedded(session, vf, track_index=0, codec="subrip", lang="en")

    job = _make_job(session, JobType.extract, movie.id, vf.id,
                    {"video_file_id": vf.id, "track_index": 0})

    def bad_runner(cmd):  # noqa: ARG001
        return 1, "", "mkvextract error"

    with pytest.raises(RuntimeError, match="mkvextract failed"):
        do_extract(job.id, session=session, runner=bad_runner)

    session.refresh(job)
    assert job.status == JobStatus.failed
    assert "mkvextract failed" in (job.error or "")


def test_do_extract_forced_track_propagates(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)
    _make_embedded(session, vf, track_index=1, codec="subrip", lang="en", forced=True)

    def fake_runner(cmd):
        out_path = Path(cmd[-1].split(":", 1)[1])
        out_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nForced\n\n")
        return 0, "", ""

    job = _make_job(session, JobType.extract, movie.id, vf.id,
                    {"video_file_id": vf.id, "track_index": 1})
    result = do_extract(job.id, session=session, runner=fake_runner)

    sub = session.get(ExternalSubtitle, result["sub_id"])
    assert sub is not None
    assert sub.forced is True
    assert ".forced." in result["path"]


def test_do_extract_ass_codec(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)
    _make_embedded(session, vf, track_index=0, codec="ass", lang="ja")

    def fake_runner(cmd):
        out_path = Path(cmd[-1].split(":", 1)[1])
        out_path.write_text("[Script Info]\n")
        return 0, "", ""

    job = _make_job(session, JobType.extract, movie.id, vf.id,
                    {"video_file_id": vf.id, "track_index": 0})
    result = do_extract(job.id, session=session, runner=fake_runner)

    assert result["path"].endswith(".ass")
    sub = session.get(ExternalSubtitle, result["sub_id"])
    assert sub is not None
    assert sub.format == "ass"


def test_do_extract_unknown_language(tmp_data, session):
    """Embedded track with no language → 'und' in path, None in DB."""
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"fake")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)
    em = EmbeddedSubtitle(
        video_file_id=vf.id, track_index=3, codec="subrip", language=None,
    )
    session.add(em)
    session.commit()

    def fake_runner(cmd):
        out_path = Path(cmd[-1].split(":", 1)[1])
        out_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nTest\n\n")
        return 0, "", ""

    job = _make_job(session, JobType.extract, movie.id, vf.id,
                    {"video_file_id": vf.id, "track_index": 3})
    result = do_extract(job.id, session=session, runner=fake_runner)

    assert ".und." in result["path"]
    sub = session.get(ExternalSubtitle, result["sub_id"])
    assert sub is not None
    assert sub.language is None


def test_do_embed_runner_error_marks_job_failed(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"original")
    srt = folder / "Test Movie (2020).en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nTest\n\n")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)
    sub = _make_external_sub(session, movie, srt)

    def bad_runner(cmd):  # noqa: ARG001
        return 2, "", "mkvmerge: input file not found"

    job = _make_job(session, JobType.embed, movie.id, vf.id,
                    {"video_file_id": vf.id, "sub_id": sub.id})

    with pytest.raises(RuntimeError, match="mkvmerge failed"):
        do_embed(job.id, session=session, runner=bad_runner)

    session.refresh(job)
    assert job.status == JobStatus.failed
    assert "mkvmerge failed" in (job.error or "")
    assert video.read_bytes() == b"original"


# ---- do_embed logic tests ----

def _make_external_sub(session: Session, movie: Movie, path: Path, vf_id=None) -> ExternalSubtitle:
    sub = ExternalSubtitle(
        movie_id=movie.id,
        path=str(path),
        real_path=str(path),
        filename=path.name,
        language="en",
        language_source="manual",
        format="srt",
        source=SubSource.manual,
        linked_video_file_id=vf_id,
        created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


def test_do_embed_replaces_mkv(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mkv"
    video.write_bytes(b"original mkv content")
    srt = folder / "Test Movie (2020).en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")

    movie = _make_movie(session, folder)
    vf = _make_video_file(session, movie, video)
    sub = _make_external_sub(session, movie, srt)

    def fake_runner(cmd):
        # Write "merged" content to the output path (cmd[2])
        out = Path(cmd[2])
        out.write_bytes(b"merged mkv content")
        return 0, "", ""

    job = _make_job(session, JobType.embed, movie.id, vf.id,
                    {"video_file_id": vf.id, "sub_id": sub.id})
    result = do_embed(job.id, session=session, runner=fake_runner)

    assert "backup" in result
    backup = Path(result["backup"])
    assert backup.exists()
    assert backup.read_bytes() == b"original mkv content"
    assert video.read_bytes() == b"merged mkv content"

    session.refresh(job)
    assert job.status == JobStatus.done


def test_do_embed_fails_non_mkv(tmp_data, session):
    library = tmp_data / "library"
    folder = library / "Test Movie (2020)"
    folder.mkdir(parents=True)
    video = folder / "Test Movie (2020).mp4"
    video.write_bytes(b"mp4")

    movie = _make_movie(session, folder)
    vf = VideoFile(
        movie_id=movie.id,
        path=str(video),
        real_path=str(video),
        filename=video.name,
        container="mp4",
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)

    srt = folder / "Test Movie (2020).en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")
    sub = _make_external_sub(session, movie, srt)

    job = _make_job(session, JobType.embed, movie.id, vf.id,
                    {"video_file_id": vf.id, "sub_id": sub.id})

    with pytest.raises(RuntimeError, match="is not MKV"):
        do_embed(job.id, session=session)

    session.refresh(job)
    assert job.status == JobStatus.failed
