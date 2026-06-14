from app.models import Job, JobStatus, JobType


def test_jobs_empty(client):
    assert client.get("/jobs/").json() == []


def test_job_created_at_is_utc(client, session):
    """created_at must be serialised with a UTC offset so browsers parse it correctly."""
    j = Job(type=JobType.scan, status=JobStatus.queued)
    session.add(j)
    session.commit()
    session.refresh(j)

    data = client.get("/jobs/").json()
    assert len(data) == 1
    ts = data[0]["created_at"]
    assert ts.endswith("+00:00") or ts.endswith("Z"), (
        f"created_at lacks UTC suffix: {ts!r}"
    )


def test_jobs_listed_newest_first(client, session):
    j1 = Job(type=JobType.scan, status=JobStatus.done)
    j2 = Job(type=JobType.transcribe, status=JobStatus.queued)
    session.add(j1)
    session.add(j2)
    session.commit()

    listed = client.get("/jobs/").json()
    assert len(listed) == 2
    # newest first
    assert listed[0]["type"] == "transcribe"


def test_get_job_returns_job(client, session):
    j = Job(type=JobType.scan, status=JobStatus.done, progress=100)
    session.add(j)
    session.commit()
    session.refresh(j)

    r = client.get(f"/jobs/{j.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == j.id
    assert body["type"] == "scan"
    assert body["status"] == "done"
    assert body["progress"] == 100


def test_get_job_missing_returns_404(client):
    assert client.get("/jobs/9999").status_code == 404
