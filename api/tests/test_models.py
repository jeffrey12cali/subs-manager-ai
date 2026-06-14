from datetime import datetime

from sqlmodel import select

from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    Job,
    JobStatus,
    JobType,
    LanguageSource,
    Movie,
    SubSource,
    VideoFile,
)


def test_movie_with_video_and_subs(session):
    m = Movie(folder_path="/library/Foo (2024)", title="Foo", year=2024)
    session.add(m)
    session.commit()
    session.refresh(m)

    vf = VideoFile(
        movie_id=m.id,
        path="/library/Foo (2024)/Foo (2024).mkv",
        real_path="/library/Foo (2024)/Foo (2024).mkv",
        is_symlink=False,
        filename="Foo (2024).mkv",
        container="mkv",
    )
    session.add(vf)
    sub = ExternalSubtitle(
        movie_id=m.id,
        path="/library/Foo (2024)/Foo (2024).en.srt",
        real_path="/library/Foo (2024)/Foo (2024).en.srt",
        filename="Foo (2024).en.srt",
        language="en",
        language_source=LanguageSource.filename,
        source=SubSource.preexisting,
        created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()

    fetched = session.exec(select(Movie).where(Movie.id == m.id)).one()
    assert len(fetched.video_files) == 1
    assert len(fetched.external_subs) == 1
    assert fetched.external_subs[0].language == "en"


def test_embedded_sub_belongs_to_video_file(session):
    m = Movie(folder_path="/library/Bar (2024)", title="Bar", year=2024)
    session.add(m)
    session.commit()
    session.refresh(m)
    vf = VideoFile(
        movie_id=m.id,
        path="/library/Bar (2024)/Bar (2024).mkv",
        real_path="/library/Bar (2024)/Bar (2024).mkv",
        filename="Bar (2024).mkv",
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)

    emb = EmbeddedSubtitle(
        video_file_id=vf.id, track_index=0, codec="srt", language="es"
    )
    session.add(emb)
    session.commit()
    session.refresh(vf)
    assert vf.embedded_subs[0].language == "es"


def test_job_enums_persist(session):
    j = Job(type=JobType.scan, status=JobStatus.queued, progress=0)
    session.add(j)
    session.commit()
    session.refresh(j)
    assert j.type == JobType.scan
    assert j.status == JobStatus.queued
