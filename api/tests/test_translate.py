"""Unit tests for subtitle translation — pure functions and do_translate logic."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.models import (
    ExternalSubtitle,
    Job,
    JobStatus,
    JobType,
    Movie,
    SubSource,
)
from app.workers.translate import (
    _NL,
    BATCH_SIZE,
    _call_api,
    _default_translate,
    _parse_numbered_response,
    _translate_batch,
    do_translate,
)

# ---- newline marker round-trip ----

def test_newline_marker_preserved_in_call_api(monkeypatch):
    """Internal newlines (\n) are encoded as _NL before sending and decoded back."""
    captured = {}

    def fake_post(self, url, *, headers, json, **kwargs):  # noqa: ARG001
        captured["body"] = json
        # Echo back: encoded form with _NL intact
        lines_sent = json["messages"][1]["content"].split("\n\n", 1)[1]

        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": lines_sent}}]}

        return FakeResp()

    import httpx
    monkeypatch.setattr(httpx.Client, "post", fake_post)

    lines = ["Hello\nWorld", "Goodbye"]
    result = _call_api(lines, "es", None, api_key="k", base_url="http://x", model="m")
    assert result == lines  # encoded and decoded correctly
    # _NL should appear in the outgoing body
    assert _NL in captured["body"]["messages"][1]["content"]


def test_call_api_line_count_mismatch_raises(monkeypatch):
    """If LLM returns wrong number of lines, RuntimeError is raised."""
    import httpx

    def fake_post(self, url, *, headers, json, **kwargs):  # noqa: ARG001
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": "only one line"}}]}

        return FakeResp()

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    with pytest.raises(RuntimeError, match=r"\[\[N\]\] response missing"):
        _call_api(["a", "b", "c"], "es", None, api_key="k", base_url="http://x", model="m")


def test_default_translate_retries_on_failure(monkeypatch):
    """_default_translate retries up to 3 times before raising."""
    calls = []

    def bad_translate(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("network error")

    monkeypatch.setattr("app.workers.translate._call_api", bad_translate)
    monkeypatch.setattr("app.workers.translate.time.sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="network error"):
        _default_translate(["a"], "es", None, api_key="k", base_url="b", model="m")

    assert len(calls) == 3


def test_default_translate_succeeds_after_one_retry(monkeypatch):
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return ["translated"]

    monkeypatch.setattr("app.workers.translate._call_api", flaky)
    monkeypatch.setattr("app.workers.translate.time.sleep", lambda s: None)

    result = _default_translate(["original"], "es", None, api_key="k", base_url="b", model="m")
    assert result == ["translated"]
    assert len(calls) == 2


# ---- do_translate helpers ----

SRT_CONTENT = """\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:04,000 --> 00:00:06,000
How are you?

"""


def _make_movie(session: Session, folder: Path) -> Movie:
    m = Movie(folder_path=str(folder), title="Test Film", year=2022,
               scanned_at=datetime.utcnow())
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _make_sub(session: Session, movie: Movie, path: Path, lang="en") -> ExternalSubtitle:
    sub = ExternalSubtitle(
        movie_id=movie.id, path=str(path), real_path=str(path),
        filename=path.name, language=lang, language_source="manual",
        format="srt", source=SubSource.manual, created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


def _make_job(session: Session, movie: Movie, sub: ExternalSubtitle, target: str, source=None) -> Job:
    job = Job(
        type=JobType.translate,
        status=JobStatus.queued,
        movie_id=movie.id,
        target_id=sub.id,
        params={"sub_id": sub.id, "target_language": target, "source_language": source},
        created_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _prefix_fn(prefix: str):
    """Fake translate_fn that prepends a prefix to every line."""
    def _fn(lines, target_lang, source_lang_hint, *, api_key, base_url, model):  # noqa: ARG001
        return [f"{prefix}{line}" for line in lines]
    return _fn


# ---- do_translate happy path ----

def test_do_translate_creates_translated_sub(tmp_data, session):
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    src_srt = folder / "Test Film (2022).en.srt"
    src_srt.write_text(SRT_CONTENT)

    movie = _make_movie(session, folder)
    sub = _make_sub(session, movie, src_srt, lang="en")
    job = _make_job(session, movie, sub, target="es", source="en")

    result = do_translate(job.id, session=session, translate_fn=_prefix_fn("[ES] "))

    assert result["language"] == "es"
    assert "Test Film (2022).es.ai.srt" in result["path"]

    new_sub = session.get(ExternalSubtitle, result["sub_id"])
    assert new_sub is not None
    assert new_sub.source == SubSource.translated
    assert new_sub.language == "es"
    assert new_sub.custom_tag == "ai"
    assert new_sub.parent_sub_id == sub.id

    content = Path(result["path"]).read_text()
    assert "[ES] Hello world" in content
    assert "[ES] How are you?" in content

    session.refresh(job)
    assert job.status == JobStatus.done
    assert job.progress == 100


def test_do_translate_preserves_timing(tmp_data, session):
    """Timestamps must be unchanged after translation."""
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    src_srt = folder / "Test Film (2022).en.srt"
    src_srt.write_text(SRT_CONTENT)

    movie = _make_movie(session, folder)
    sub = _make_sub(session, movie, src_srt, lang="en")
    job = _make_job(session, movie, sub, target="fr")

    result = do_translate(job.id, session=session, translate_fn=_prefix_fn("[FR] "))

    content = Path(result["path"]).read_text()
    assert "00:00:01,000 --> 00:00:03,000" in content
    assert "00:00:04,000 --> 00:00:06,000" in content


def test_do_translate_batches_large_srt(tmp_data, session):
    """Files larger than BATCH_SIZE are split into multiple batches."""
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)

    # Build an SRT with BATCH_SIZE + 5 entries
    lines = []
    for i in range(BATCH_SIZE + 5):
        s = i * 3
        e = s + 2
        lines.append(f"{i + 1}")
        lines.append(f"00:00:{s:02d},000 --> 00:00:{e:02d},000")
        lines.append(f"Line {i + 1}")
        lines.append("")
    src_srt = folder / "Test Film (2022).en.srt"
    src_srt.write_text("\n".join(lines))

    movie = _make_movie(session, folder)
    sub = _make_sub(session, movie, src_srt, lang="en")
    job = _make_job(session, movie, sub, target="de")

    batch_calls = []

    def counting_fn(batch_lines, target, source_hint, *, api_key, base_url, model):  # noqa: ARG001
        batch_calls.append(len(batch_lines))
        return [f"[DE] {line}" for line in batch_lines]

    do_translate(job.id, session=session, translate_fn=counting_fn)

    assert len(batch_calls) == 2  # two batches
    assert batch_calls[0] == BATCH_SIZE
    assert batch_calls[1] == 5


def test_do_translate_replaces_existing_translated_sub(tmp_data, session):
    """Re-translating to the same target language replaces the old row."""
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    src_srt = folder / "Test Film (2022).en.srt"
    src_srt.write_text(SRT_CONTENT)

    movie = _make_movie(session, folder)
    sub = _make_sub(session, movie, src_srt, lang="en")

    # Stale translated sub
    stale_path = str(folder / "stale.es.ai.srt")
    stale = ExternalSubtitle(
        movie_id=movie.id, path=stale_path, real_path=stale_path,
        filename="stale.es.ai.srt", language="es", language_source="manual",
        format="srt", source=SubSource.translated, custom_tag="ai",
        created_at=datetime.utcnow(),
    )
    session.add(stale)
    session.commit()

    job = _make_job(session, movie, sub, target="es")
    result = do_translate(job.id, session=session, translate_fn=_prefix_fn("[ES]"))

    rows = session.exec(
        select(ExternalSubtitle)
        .where(ExternalSubtitle.movie_id == movie.id)
        .where(ExternalSubtitle.source == SubSource.translated)
        .where(ExternalSubtitle.language == "es")
    ).all()
    assert len(rows) == 1
    assert rows[0].id == result["sub_id"]


def test_do_translate_inherits_forced_flag(tmp_data, session):
    """Translated sub inherits forced=True from source sub."""
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    src_srt = folder / "Test Film (2022).en.forced.srt"
    src_srt.write_text(SRT_CONTENT)

    movie = _make_movie(session, folder)
    sub = ExternalSubtitle(
        movie_id=movie.id, path=str(src_srt), real_path=str(src_srt),
        filename=src_srt.name, language="en", language_source="manual",
        format="srt", source=SubSource.manual, forced=True,
        created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)

    job = _make_job(session, movie, sub, target="es")
    result = do_translate(job.id, session=session, translate_fn=_prefix_fn("[ES]"))

    new_sub = session.get(ExternalSubtitle, result["sub_id"])
    assert new_sub is not None
    assert new_sub.forced is True
    assert ".forced." in result["path"]


# ---- do_translate error paths ----

def test_do_translate_missing_sub(tmp_data, session):
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    movie = _make_movie(session, folder)

    job = Job(
        type=JobType.translate, status=JobStatus.queued,
        movie_id=movie.id, target_id=9999,
        params={"sub_id": 9999, "target_language": "es", "source_language": None},
        created_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    with pytest.raises(RuntimeError, match="ExternalSubtitle 9999 not found"):
        do_translate(job.id, session=session, translate_fn=_prefix_fn(""))

    session.refresh(job)
    assert job.status == JobStatus.failed


def test_do_translate_missing_file_on_disk(tmp_data, session):
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    ghost = folder / "ghost.en.srt"  # Does NOT exist on disk

    movie = _make_movie(session, folder)
    sub = ExternalSubtitle(
        movie_id=movie.id, path=str(ghost), real_path=str(ghost),
        filename=ghost.name, language="en", language_source="manual",
        format="srt", source=SubSource.manual, created_at=datetime.utcnow(),
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)

    job = _make_job(session, movie, sub, target="de")

    with pytest.raises(RuntimeError, match="not found"):
        do_translate(job.id, session=session, translate_fn=_prefix_fn(""))

    session.refresh(job)
    assert job.status == JobStatus.failed


def test_do_translate_no_api_key(tmp_data, session, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    import app.core.config as cfg_mod
    cfg_mod.settings = cfg_mod.Settings()

    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    src_srt = folder / "Test Film (2022).en.srt"
    src_srt.write_text(SRT_CONTENT)

    movie = _make_movie(session, folder)
    sub = _make_sub(session, movie, src_srt)
    job = _make_job(session, movie, sub, target="es")

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        do_translate(job.id, session=session)  # no translate_fn → hits config check

    session.refresh(job)
    assert job.status == JobStatus.failed


def test_do_translate_fn_raises_marks_job_failed(tmp_data, session):
    folder = tmp_data / "library" / "Test Film (2022)"
    folder.mkdir(parents=True)
    src_srt = folder / "Test Film (2022).en.srt"
    src_srt.write_text(SRT_CONTENT)

    movie = _make_movie(session, folder)
    sub = _make_sub(session, movie, src_srt)
    job = _make_job(session, movie, sub, target="zh")

    def bad_fn(lines, *a, **kw):
        raise RuntimeError("context window exceeded")

    with pytest.raises(RuntimeError, match="context window exceeded"):
        do_translate(job.id, session=session, translate_fn=bad_fn)

    session.refresh(job)
    assert job.status == JobStatus.failed
    assert "context window exceeded" in (job.error or "")


# ---- _parse_numbered_response ----

def test_parse_numbered_response_clean():
    """Extracts all lines from a well-formed [[N]] response."""
    n = 5
    text = "\n".join(f"[[{i}]] Line {i}" for i in range(1, n + 1))
    result = _parse_numbered_response(text, n)
    assert result == [f"Line {i}" for i in range(1, n + 1)]


def test_parse_numbered_response_tolerates_commentary():
    """Stray non-[[N]] lines (e.g. 'Here is the translation:') are skipped."""
    text = "Here is the translation:\n[[1]] Hello\n[[2]] World"
    result = _parse_numbered_response(text, 2)
    assert result == ["Hello", "World"]


def test_parse_numbered_response_missing_one_line():
    """A single missing index returns empty string for that slot."""
    text = "[[1]] First\n[[3]] Third"  # [[2]] is absent
    result = _parse_numbered_response(text, 3)
    assert result == ["First", "", "Third"]


def test_parse_numbered_response_raises_when_too_many_missing():
    """Raises RuntimeError when more than 10 % of indices are absent."""
    text = "[[1]] Only one"
    with pytest.raises(RuntimeError, match=r"\[\[N\]\] response missing"):
        _parse_numbered_response(text, 25)  # 24/25 = 96 % missing


# ---- halving fallback in _translate_batch ----

def test_translate_batch_halves_on_mismatch():
    """If fn fails for the full batch, _translate_batch tries each half."""
    call_log: list[int] = []

    def flaky_fn(lines, target_lang, source_lang_hint, *, api_key, base_url, model):  # noqa: ARG001
        call_log.append(len(lines))
        if len(lines) > 2:
            raise RuntimeError("batch too large")
        return [f"[T] {line}" for line in lines]

    batch = ["a", "b", "c", "d"]
    result = _translate_batch(batch, flaky_fn, "es", None,
                              api_key="k", base_url="b", model="m")
    assert result == ["[T] a", "[T] b", "[T] c", "[T] d"]
    assert call_log[0] == 4   # first attempt (fails)
    assert call_log[1] == 2   # left half
    assert call_log[2] == 2   # right half
