"""Tests for job creation, processing, status, and certificate retrieval."""

from pathlib import Path

import pytest

from app.models import Job, Certificate
from app.services import process_job
from tests.conftest import RECIPIENTS


# --- 1. Job creation ---

def test_create_job(client, create_job, test_db):
    job_id = create_job(RECIPIENTS)

    job = test_db.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    assert job.status == "PENDING"
    assert job.total == 3
    assert test_db.query(Certificate).filter(Certificate.job_id == job_id).count() == 3


# --- 2. Validation ---

@pytest.mark.parametrize("payload,reason", [
    # Invalid email
    (
        {"recipients": [{"name": "X", "email": "bad", "course": "C"}]},
        "invalid email",
    ),
    # Empty name
    (
        {"recipients": [{"name": "", "email": "a@b.com", "course": "C"}]},
        "empty name",
    ),
    # Empty recipients list
    (
        {"recipients": []},
        "empty list",
    ),
    # Missing field
    (
        {"recipients": [{"name": "X", "email": "a@b.com"}]},
        "missing course",
    ),
], ids=["invalid_email", "empty_name", "empty_list", "missing_field"])
def test_validation_rejects_bad_input(client, test_db, payload, reason):
    resp = client.post("/api/jobs", json=payload)
    assert resp.status_code == 422, f"Expected 422 for {reason}"
    # No job should have been created
    assert test_db.query(Job).count() == 0


# --- 3. Certificate generation ---

def test_certificate_generation(client, create_job, test_db):
    job_id = create_job(RECIPIENTS)
    process_job(job_id)

    # Refresh to pick up changes from process_job's session
    test_db.expire_all()
    certs = test_db.query(Certificate).filter(Certificate.job_id == job_id).all()

    for cert in certs:
        assert cert.status == "SUCCESS"
        assert cert.file_path is not None
        pdf_path = Path(cert.file_path)
        assert pdf_path.is_file(), f"PDF missing: {pdf_path}"
        assert pdf_path.read_bytes()[:5] == b"%PDF-"


# --- 4. Job status and progress ---

def test_job_status_and_progress(client, create_job, test_db):
    job_id = create_job(RECIPIENTS)

    # Before processing: all pending, 0% progress
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "PENDING"
    assert data["pending"] == 3
    assert data["progress_percent"] == 0

    # Process and re-check
    process_job(job_id)
    test_db.expire_all()

    resp = client.get(f"/api/jobs/{job_id}")
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert data["succeeded"] == 3
    assert data["failed"] == 0
    assert data["pending"] == 0
    assert data["progress_percent"] == 100


# --- 5. Isolated failure ---

def test_single_failure_is_isolated(client, create_job, test_db, monkeypatch):
    job_id = create_job(RECIPIENTS)

    original_gen = __import__("app.services", fromlist=["generate_certificate_pdf"]).generate_certificate_pdf

    def _failing_gen(cert, output_dir):
        """Fail only for Bob, succeed for everyone else."""
        if cert.recipient_name == "Bob":
            raise RuntimeError("Printer on fire")
        return original_gen(cert, output_dir)

    monkeypatch.setattr("app.services.generate_certificate_pdf", _failing_gen)

    process_job(job_id)
    test_db.expire_all()

    job = test_db.query(Job).filter(Job.id == job_id).first()
    assert job.status == "COMPLETED_WITH_ERRORS"
    assert job.succeeded == 2
    assert job.failed == 1

    # The failed cert should have the error message
    failed = test_db.query(Certificate).filter(
        Certificate.job_id == job_id, Certificate.status == "FAILED"
    ).all()
    assert len(failed) == 1
    assert failed[0].recipient_name == "Bob"
    assert "Printer on fire" in failed[0].error

    # The others should be SUCCESS
    ok = test_db.query(Certificate).filter(
        Certificate.job_id == job_id, Certificate.status == "SUCCESS"
    ).all()
    assert len(ok) == 2

    # GET /jobs/{id} should list the failure
    resp = client.get(f"/api/jobs/{job_id}")
    data = resp.json()
    assert len(data["failures"]) == 1
    assert data["failures"][0]["recipient_email"] == "bob@example.com"
    assert "Printer on fire" in data["failures"][0]["error"]


# --- 6. Certificate retrieval and download ---

def test_retrieve_certificates(client, create_job, test_db):
    job_id = create_job(RECIPIENTS)
    process_job(job_id)
    test_db.expire_all()

    # List all certificates
    resp = client.get(f"/api/jobs/{job_id}/certificates")
    assert resp.status_code == 200
    certs = resp.json()
    assert len(certs) == 3

    # Every SUCCESS cert should have a download_url
    for c in certs:
        assert c["status"] == "SUCCESS"
        assert c["download_url"] is not None

    # Download the first cert — should return a PDF
    url = certs[0]["download_url"]
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"

    # 404 for unknown certificate
    resp = client.get("/api/certificates/9999/download")
    assert resp.status_code == 404

    # 404 for unknown job
    resp = client.get("/api/jobs/nonexistent/certificates")
    assert resp.status_code == 404


def test_download_pending_certificate_returns_409(client, create_job, test_db):
    """Downloading a certificate that hasn't been processed yet gives 409."""
    job_id = create_job(RECIPIENTS)
    # Don't call process_job — certs stay PENDING

    cert = test_db.query(Certificate).filter(Certificate.job_id == job_id).first()
    resp = client.get(f"/api/certificates/{cert.id}/download")
    assert resp.status_code == 409
