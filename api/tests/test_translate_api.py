"""API tests for POST /subs/{id}/translate."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.models import ExternalSubtitle, Movie, SubSource

SRT_CONTENT = """\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:04,000 --> 00:00:06,000
How are you?

"""


def _movie(session, folder: Path) -> Movie:
    m = Movie(folder_path=str(folder), title="Film", year=2020,
               scanned_at=datetime.utcnow())
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _sub(session, movie: Movie, path: Path, lang="en") -> ExternalSubtitle:
    sub = ExternalSubtitle(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, language=lang, language_source="manual",
        format="srt", source=SubSource.manual, created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


def _fake_translate(prefix: str):
    def _fn(lines, target, source_hint, *, api_key, base_url, model):  # noqa: ARG001
        return [f"{prefix}{line}" for line in lines]
    return _fn


# ---- happy path ----

def test_translate_returns_done_job(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    srt = folder / "Film (2020).en.srt"
    srt.write_text(SRT_CONTENT)

    movie = _movie(session, folder)
    sub = _sub(session, movie, srt)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import app.core.config as cfg
    cfg.settings = cfg.Settings()
    monkeypatch.setattr("app.workers.translate._default_translate", _fake_translate("[ES] "))

    r = client.post(f"/subs/{sub.id}/translate",
                    json={"target_language": "es", "source_language": "en"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "translate"
    assert body["status"] == "done"


def test_translate_creates_srt_file(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    srt = folder / "Film (2020).en.srt"
    srt.write_text(SRT_CONTENT)

    movie = _movie(session, folder)
    sub = _sub(session, movie, srt)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import app.core.config as cfg
    cfg.settings = cfg.Settings()
    monkeypatch.setattr("app.workers.translate._default_translate", _fake_translate("[FR] "))

    r = client.post(f"/subs/{sub.id}/translate",
                    json={"target_language": "fr"})
    assert r.status_code == 200

    out = folder / "Film (2020).fr.ai.srt"
    assert out.exists()
    content = out.read_text()
    assert "[FR] Hello world" in content
    assert "00:00:01,000 --> 00:00:03,000" in content


def test_translate_source_language_optional(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    srt = folder / "Film (2020).en.srt"
    srt.write_text(SRT_CONTENT)

    movie = _movie(session, folder)
    sub = _sub(session, movie, srt)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import app.core.config as cfg
    cfg.settings = cfg.Settings()
    monkeypatch.setattr("app.workers.translate._default_translate", _fake_translate(""))

    r = client.post(f"/subs/{sub.id}/translate", json={"target_language": "de"})
    assert r.status_code == 200, r.text


# ---- validation ----

def test_translate_404_on_missing_sub(client):
    r = client.post("/subs/9999/translate", json={"target_language": "es"})
    assert r.status_code == 404


def test_translate_422_same_language(client, session, tmp_data):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    srt = folder / "Film (2020).en.srt"
    srt.write_text(SRT_CONTENT)

    movie = _movie(session, folder)
    sub = _sub(session, movie, srt, lang="en")

    r = client.post(f"/subs/{sub.id}/translate",
                    json={"target_language": "en"})
    assert r.status_code == 422


# ---- failure path ----

def test_translate_job_failed_on_error(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    srt = folder / "Film (2020).en.srt"
    srt.write_text(SRT_CONTENT)

    movie = _movie(session, folder)
    sub = _sub(session, movie, srt)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import app.core.config as cfg
    cfg.settings = cfg.Settings()

    def bad_fn(lines, *a, **kw):
        raise RuntimeError("rate limit exceeded")

    monkeypatch.setattr("app.workers.translate._default_translate", bad_fn)

    r = client.post(f"/subs/{sub.id}/translate", json={"target_language": "ja"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert "rate limit exceeded" in (body["error"] or "")


def test_translate_no_api_key_fails(client, session, tmp_data, monkeypatch):
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    srt = folder / "Film (2020).en.srt"
    srt.write_text(SRT_CONTENT)

    movie = _movie(session, folder)
    sub = _sub(session, movie, srt)

    # Ensure key is empty (default is already "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    import app.core.config as cfg
    cfg.settings = cfg.Settings()

    r = client.post(f"/subs/{sub.id}/translate", json={"target_language": "pt"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert "DEEPSEEK_API_KEY" in (body["error"] or "")


def test_translate_idempotent_second_run(client, session, tmp_data, monkeypatch):
    """Translating same language twice keeps only one translated sub row."""
    folder = tmp_data / "library" / "Film (2020)"
    folder.mkdir(parents=True)
    srt = folder / "Film (2020).en.srt"
    srt.write_text(SRT_CONTENT)

    movie = _movie(session, folder)
    sub = _sub(session, movie, srt)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import app.core.config as cfg
    cfg.settings = cfg.Settings()

    monkeypatch.setattr("app.workers.translate._default_translate",
                        _fake_translate("[v1] "))
    client.post(f"/subs/{sub.id}/translate", json={"target_language": "es"})

    monkeypatch.setattr("app.workers.translate._default_translate",
                        _fake_translate("[v2] "))
    r = client.post(f"/subs/{sub.id}/translate", json={"target_language": "es"})
    assert r.status_code == 200

    out = folder / "Film (2020).es.ai.srt"
    assert "[v2] " in out.read_text()

    from sqlmodel import Session as S
    from sqlmodel import select

    from app.core import db as db_mod
    with S(db_mod.engine) as s:
        rows = s.exec(
            select(ExternalSubtitle)
            .where(ExternalSubtitle.movie_id == movie.id)
            .where(ExternalSubtitle.source == SubSource.translated)
        ).all()
    assert len(rows) == 1
