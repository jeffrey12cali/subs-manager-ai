from datetime import datetime, timezone

from app.models import (
    EmbeddedSubtitle,
    ExternalSubtitle,
    Movie,
    SubSource,
    VideoFile,
)


def test_list_empty(client):
    assert client.get("/movies/").json() == []


def test_list_returns_summary(client, session):
    m = Movie(folder_path="/library/X (2024)", title="X", year=2024)
    session.add(m)
    session.commit()
    session.refresh(m)

    listed = client.get("/movies/").json()
    assert len(listed) == 1
    s = listed[0]
    assert s["title"] == "X"
    assert s["video_count"] == 0
    assert s["external_sub_count"] == 0
    assert s["has_subs"] is False


def test_get_returns_detail(client, session):
    m = Movie(folder_path="/library/Y (2025)", title="Y", year=2025)
    session.add(m)
    session.commit()
    session.refresh(m)

    got = client.get(f"/movies/{m.id}").json()
    assert got["folder_path"] == "/library/Y (2025)"
    assert got["video_files"] == []
    assert got["external_subs"] == []


def test_get_missing_404(client):
    assert client.get("/movies/9999").status_code == 404


def test_missing_subs_filter(client, session):
    """missing_subs=true only returns movies with no subs."""
    m1 = Movie(folder_path="/library/A (2024)", title="A", year=2024)
    m2 = Movie(folder_path="/library/B (2024)", title="B", year=2024)
    session.add(m1)
    session.add(m2)
    session.commit()

    # Both have no subs → both returned when filter is true.
    listed = client.get("/movies/?missing_subs=true").json()
    assert len(listed) == 2


def test_unknown_sub_count_for_language_less_external_sub(client, session):
    """An external sub with language=None contributes to unknown_sub_count, not languages list."""
    m = Movie(folder_path="/library/Z (2020)", title="Z", year=2020)
    session.add(m)
    session.commit()
    session.refresh(m)

    unlabelled = ExternalSubtitle(
        movie_id=m.id,
        path="/library/Z (2020)/Z (2020).srt",
        real_path="/library/Z (2020)/Z (2020).srt",
        filename="Z (2020).srt",
        language=None,
        language_source="unknown",
        format="srt",
        source=SubSource.preexisting,
        created_at=datetime.now(timezone.utc),
    )
    session.add(unlabelled)
    session.commit()

    listed = client.get("/movies/").json()
    assert len(listed) == 1
    s = listed[0]
    assert s["unknown_sub_count"] == 1
    assert s["external_sub_languages"] == []
    assert s["has_subs"] is True


def test_missing_subs_filter_excludes_movies_with_subs(client, session):
    """missing_subs=true excludes movies that already have external subs."""
    has_subs = Movie(folder_path="/library/Has (2024)", title="Has", year=2024)
    no_subs = Movie(folder_path="/library/None (2024)", title="None", year=2024)
    session.add(has_subs)
    session.add(no_subs)
    session.commit()
    session.refresh(has_subs)

    sub = ExternalSubtitle(
        movie_id=has_subs.id,
        path="/library/Has (2024)/Has (2024).en.srt",
        real_path="/library/Has (2024)/Has (2024).en.srt",
        filename="Has (2024).en.srt",
        language="en",
        language_source="manual",
        format="srt",
        source=SubSource.manual,
        created_at=datetime.now(timezone.utc),
    )
    session.add(sub)
    session.commit()

    listed = client.get("/movies/?missing_subs=true").json()
    titles = {m["title"] for m in listed}
    assert titles == {"None"}


def test_get_detail_includes_embedded_subs_per_video_file(client, session):
    m = Movie(folder_path="/library/V (2021)", title="V", year=2021)
    session.add(m)
    session.commit()
    session.refresh(m)

    vf = VideoFile(
        movie_id=m.id,
        path="/library/V (2021)/V (2021).mkv",
        real_path="/library/V (2021)/V (2021).mkv",
        filename="V (2021).mkv",
        container="mkv",
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)

    emb = EmbeddedSubtitle(video_file_id=vf.id, track_index=2, codec="subrip", language="en")
    session.add(emb)
    session.commit()

    detail = client.get(f"/movies/{m.id}").json()
    assert len(detail["video_files"]) == 1
    embedded = detail["video_files"][0]["embedded_subs"]
    assert len(embedded) == 1
    assert embedded[0]["track_index"] == 2
    assert embedded[0]["language"] == "en"


def test_embedded_sub_languages_in_summary(client, session):
    """embedded_sub_languages lists individual languages of embedded tracks."""
    m = Movie(folder_path="/library/W (2019)", title="W", year=2019)
    session.add(m)
    session.commit()
    session.refresh(m)

    vf = VideoFile(
        movie_id=m.id,
        path="/library/W (2019)/W (2019).mkv",
        real_path="/library/W (2019)/W (2019).mkv",
        filename="W (2019).mkv",
        container="mkv",
    )
    session.add(vf)
    session.commit()
    session.refresh(vf)

    for lang in ("en", "de"):
        emb = EmbeddedSubtitle(
            video_file_id=vf.id,
            track_index=1 if lang == "en" else 2,
            codec="subrip",
            language=lang,
        )
        session.add(emb)
    session.commit()

    listed = client.get("/movies/").json()
    assert len(listed) == 1
    s = listed[0]
    assert s["embedded_sub_languages"] == ["de", "en"]
    assert s["embedded_sub_count"] == 2
