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
