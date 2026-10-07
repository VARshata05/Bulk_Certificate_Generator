"""Smoke tests — verify the app boots and models/schemas are valid."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Job, Certificate
from app.schemas import RecipientIn, JobCreate


# --- Fixtures ---

@pytest.fixture()
def db_session():
    """In-memory SQLite so tests never touch the real DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    """TestClient wired to the in-memory DB."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- App tests ---

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- Model tests ---

def test_job_defaults(db_session):
    job = Job(total=5)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert len(job.id) == 36  # UUID format
    assert job.status == "PENDING"
    assert job.succeeded == 0
    assert job.failed == 0
    assert job.created_at is not None


def test_certificate_fk(db_session):
    job = Job(total=1)
    db_session.add(job)
    db_session.commit()

    cert = Certificate(
        job_id=job.id,
        recipient_name="Alice",
        recipient_email="alice@example.com",
        course_name="Python 101",
    )
    db_session.add(cert)
    db_session.commit()
    db_session.refresh(cert)

    assert cert.job_id == job.id
    assert cert.status == "PENDING"
    assert cert.file_path is None
    assert cert.error is None


def test_cascade_delete(db_session):
    job = Job(total=1)
    db_session.add(job)
    db_session.commit()

    cert = Certificate(
        job_id=job.id,
        recipient_name="Bob",
        recipient_email="bob@example.com",
        course_name="FastAPI",
    )
    db_session.add(cert)
    db_session.commit()

    # Deleting the job should cascade-delete its certificates
    db_session.delete(job)
    db_session.commit()
    assert db_session.query(Certificate).count() == 0


# --- Schema validation tests ---

def test_recipient_valid():
    r = RecipientIn(name="Alice", email="alice@example.com", course="Python")
    assert r.name == "Alice"


def test_recipient_empty_name():
    with pytest.raises(Exception):
        RecipientIn(name="", email="alice@example.com", course="Python")


def test_recipient_bad_email():
    with pytest.raises(Exception):
        RecipientIn(name="Alice", email="not-an-email", course="Python")


def test_job_create_empty_list():
    with pytest.raises(Exception):
        JobCreate(recipients=[])


def test_job_create_over_limit():
    # 1001 recipients should fail the max_length=1000 constraint
    recipients = [
        {"name": f"User {i}", "email": f"u{i}@test.com", "course": "X"}
        for i in range(1001)
    ]
    with pytest.raises(Exception):
        JobCreate(recipients=recipients)
