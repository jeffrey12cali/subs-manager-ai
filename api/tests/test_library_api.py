def test_roots_crud(client):
    assert client.get("/library/roots").json() == []

    r = client.post(
        "/library/roots", json={"path": "/library", "name": "Movies", "enabled": True}
    )
    assert r.status_code == 200
    rid = r.json()["id"]

    listed = client.get("/library/roots").json()
    assert len(listed) == 1
    assert listed[0]["path"] == "/library"

    d = client.delete(f"/library/roots/{rid}")
    assert d.status_code == 200
    assert client.get("/library/roots").json() == []


def test_delete_missing_root_404(client):
    assert client.delete("/library/roots/9999").status_code == 404


def test_scan_returns_job_ids(client):
    """Scan falls back to synchronous execution when Redis is unavailable
    (test environment). Should return job_ids list and roots."""
    r = client.post("/library/scan")
    assert r.status_code == 200
    body = r.json()
    assert "job_ids" in body
    assert "roots" in body
    assert isinstance(body["job_ids"], list)


def test_scan_one_configured_library(client, library_root, monkeypatch):
    import app.core.config as config_mod

    series_root = library_root.parent / "series-library"
    series_root.mkdir()
    monkeypatch.setattr(
        config_mod.settings,
        "libraries",
        f"Movies|movies|{library_root};Series|series|{series_root}",
    )

    r = client.post("/library/scan?library=series")
    assert r.status_code == 200
    assert r.json()["roots"] == [str(series_root)]


def test_scan_all_configured_libraries(client, library_root, monkeypatch):
    import app.core.config as config_mod

    series_root = library_root.parent / "series-library"
    series_root.mkdir()
    monkeypatch.setattr(
        config_mod.settings,
        "libraries",
        f"Movies|movies|{library_root};Series|series|{series_root}",
    )

    r = client.post("/library/scan")
    assert r.status_code == 200
    assert r.json()["roots"] == [str(library_root), str(series_root)]


def test_scan_unknown_library_404(client):
    assert client.post("/library/scan?library=missing").status_code == 404


def test_scan_failure_does_not_block_other_library(
    client, library_root, monkeypatch
):
    import app.core.config as config_mod
    import app.scanner.scanner as scanner_mod

    good = library_root
    bad = library_root.parent / "bad-library"
    bad.mkdir()
    monkeypatch.setattr(
        config_mod.settings,
        "libraries",
        f"Bad|movies|{bad};Good|movies|{good}",
    )

    real_scan = scanner_mod.scan_library

    def selective_scan(root, session, **kwargs):
        if str(root) == str(bad):
            raise RuntimeError("boom")
        return real_scan(root, session, **kwargs)

    monkeypatch.setattr(scanner_mod, "scan_library", selective_scan)

    r = client.post("/library/scan")
    assert r.status_code == 200
    assert len(r.json()["job_ids"]) == 2
