"""End-to-end pipeline: scan -> list/detail -> upload -> translate -> embed.

All externals (ffprobe, the translation LLM, mkvmerge) are mocked via the
same injection points unit tests use. This guards the wiring *between*
layers (API -> scanner/workers -> DB -> filesystem) that per-module unit
tests don't exercise.
"""
from __future__ import annotations

from pathlib import Path

VALID_SRT = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nWorld\n"

_FFPROBE_JSON = {
    "format": {"duration": "5400"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "index": 0},
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "index": 1,
            "channels": 2,
            "tags": {"language": "eng"},
        },
        {
            "codec_type": "subtitle",
            "codec_name": "subrip",
            "index": 2,
            "tags": {"language": "eng", "title": "English"},
            "disposition": {"default": 1, "forced": 0},
        },
    ],
}


def _fake_translate(prefix: str):
    def _fn(lines, target, source_hint, *, api_key, base_url, model):  # noqa: ARG001
        return [f"{prefix}{line}" for line in lines]
    return _fn


def test_full_pipeline_scan_upload_translate_embed(
    client, session, library_root: Path, monkeypatch
):
    # No Redis in the test sandbox: make `arq.create_pool` fail immediately so
    # every step falls back to its synchronous in-process path without the
    # multi-second connection-retry delay.
    def _no_redis(*_a, **_kw):
        raise ConnectionError("no redis in tests")

    monkeypatch.setattr("arq.create_pool", _no_redis)

    # ---- 0. lay out a movie folder with one MKV on disk ----
    folder = library_root / "Stalker (1979)"
    folder.mkdir(parents=True)
    video = folder / "Stalker (1979).mkv"
    video.write_bytes(b"ORIGINAL_MKV_BYTES")

    # Register this test's library root via the API (the `settings` object
    # imported at module-load time by app.api.library is process-global and
    # can't be refreshed per-test, so the DB-backed LibraryRoot table is the
    # only reliable way to point /library/scan at our tmp library dir).
    r = client.post(
        "/library/roots", json={"path": str(library_root), "name": "Movies", "enabled": True}
    )
    assert r.status_code == 200, r.text

    # ---- 1. scan: ffprobe mocked to report one embedded English srt track ----
    monkeypatch.setattr("app.scanner.probe._default_runner", lambda _path: _FFPROBE_JSON)

    r = client.post("/library/scan")
    assert r.status_code == 200, r.text
    job_ids = r.json()["job_ids"]
    assert len(job_ids) == 1

    job = client.get(f"/jobs/{job_ids[0]}").json()
    assert job["status"] == "done"

    # ---- 2. list: movie discovered with its embedded subtitle language ----
    listed = client.get("/movies/").json()
    assert len(listed) == 1
    summary = listed[0]
    assert summary["title"] == "Stalker"
    assert summary["year"] == 1979
    assert summary["video_count"] == 1
    assert summary["embedded_sub_languages"] == ["en"]

    movie_id = summary["id"]

    # ---- 3. detail: embedded subtitle track mapped onto the video file ----
    detail = client.get(f"/movies/{movie_id}").json()
    assert len(detail["video_files"]) == 1
    vf = detail["video_files"][0]
    embedded = vf["embedded_subs"]
    assert len(embedded) == 1
    assert embedded[0]["track_index"] == 2
    assert embedded[0]["language"] == "en"
    assert embedded[0]["codec"] == "srt"

    vf_id = vf["id"]

    # ---- 4. upload an external English subtitle ----
    r = client.post(
        f"/movies/{movie_id}/subs/upload",
        files={"file": ("Stalker.en.srt", VALID_SRT, "text/plain")},
        data={"language": "en"},
    )
    assert r.status_code == 200, r.text
    en_sub = r.json()
    assert en_sub["language"] == "en"
    en_path = Path(en_sub["path"])
    assert en_path.exists()
    assert en_path.read_bytes() == VALID_SRT

    # ---- 5. translate the uploaded subtitle to Spanish ----
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    import app.core.config as cfg

    cfg.settings = cfg.Settings()
    monkeypatch.setattr("app.workers.translate._default_translate", _fake_translate("[ES] "))

    r = client.post(f"/subs/{en_sub['id']}/translate", json={"target_language": "es"})
    assert r.status_code == 200, r.text
    translate_job = r.json()
    assert translate_job["status"] == "done"

    subs_after_translate = client.get(f"/subs/?movie_id={movie_id}").json()
    es_subs = [s for s in subs_after_translate if s["language"] == "es"]
    assert len(es_subs) == 1
    es_sub = es_subs[0]
    assert es_sub["custom_tag"] == "ai"

    es_path = Path(es_sub["path"])
    assert es_path.exists()
    assert es_path.read_text().count("[ES] ") == 2  # both subtitle lines translated

    # ---- 6. embed the Spanish subtitle into the MKV (mkvmerge mocked) ----
    def fake_embed(video_path, sub_path, out_path, language, forced, runner=None):  # noqa: ARG001
        out_path.write_bytes(b"MERGED_MKV_BYTES")

    monkeypatch.setattr("app.workers.mkv.embed_sub_track", fake_embed)

    r = client.post(f"/video-files/{vf_id}/embed", json={"sub_id": es_sub["id"]})
    assert r.status_code == 200, r.text
    embed_job = r.json()
    assert embed_job["status"] == "done"

    # Original file replaced with the merged output...
    assert video.read_bytes() == b"MERGED_MKV_BYTES"
    # ...and the pre-embed original was preserved as a timestamped backup.
    backups = list(folder.glob("Stalker (1979).mkv.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"ORIGINAL_MKV_BYTES"
