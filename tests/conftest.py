"""Shared test fixtures — file-based SQLite, deterministic job processing."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.services import process_job


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """File-based SQLite in tmp_path so process_job's own session can access it."""
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # Route process_job's SessionLocal to the same test DB
    monkeypatch.setattr("app.services.SessionLocal", TestSession)

    # Redirect PDF output into tmp_path so tests don't pollute generated/
    monkeypatch.setattr("app.services.OUTPUT_DIR", tmp_path / "certs")

    # Make the background thread a no-op so tests stay deterministic —
    # tests call process_job() directly when they need processing.
    # (Can't monkeypatch threading.Thread itself; anyio subclasses it.)
    monkeypatch.setattr("app.routes.process_job", lambda job_id: None)


    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(test_db):
    """TestClient wired to the test DB."""
    app.dependency_overrides[get_db] = lambda: test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def create_job(client):
    """Helper: POST a job with the given recipients, return the job_id."""
    def _create(recipients):
        resp = client.post("/api/jobs", json={"recipients": recipients})
        assert resp.status_code == 202
        return resp.json()["job_id"]
    return _create


# Default test recipients
RECIPIENTS = [
    {"name": "Alice", "email": "alice@example.com", "course": "Python"},
    {"name": "Bob", "email": "bob@example.com", "course": "FastAPI"},
    {"name": "Carol", "email": "carol@example.com", "course": "SQLAlchemy"},
]
