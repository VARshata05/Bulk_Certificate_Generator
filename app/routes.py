"""API route definitions."""

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, Certificate
from app.schemas import (
    JobCreate,
    JobStatusOut,
    FailureDetail,
    CertificateListItem,
)
from app.services import process_job

router = APIRouter(prefix="/api", tags=["certificates"])


# --- Helpers ---

def _get_job_or_404(job_id: str, db: Session) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# --- Endpoints ---

@router.post("/jobs", status_code=202)
def create_job(body: JobCreate, db: Session = Depends(get_db)):
    """Accept a batch of recipients, persist them, and kick off generation."""
    job = Job(total=len(body.recipients))

    # Build all certificate rows upfront for a single bulk insert
    for r in body.recipients:
        job.certificates.append(
            Certificate(
                recipient_name=r.name,
                recipient_email=r.email,
                course_name=r.course,
            )
        )

    db.add(job)
    db.commit()
    db.refresh(job)

    # Thread instead of BackgroundTasks: avoids SQLite deadlock where
    # the get_db dependency's session stays open until after the background
    # task finishes, holding a read lock that blocks process_job's writes.
    threading.Thread(target=process_job, args=(job.id,), daemon=True).start()

    return {"job_id": job.id, "status": job.status, "total": job.total}


@router.get("/jobs/{job_id}", response_model=JobStatusOut)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """Return job progress with a list of failures (if any)."""
    job = _get_job_or_404(job_id, db)

    pending = job.total - job.succeeded - job.failed
    progress = round((job.succeeded + job.failed) / job.total * 100, 1) if job.total else 0

    failures = [
        FailureDetail(
            certificate_id=c.id,
            recipient_email=c.recipient_email,
            error=c.error,
        )
        for c in job.certificates if c.status == "FAILED"
    ]

    return JobStatusOut(
        job_id=job.id,
        status=job.status,
        total=job.total,
        succeeded=job.succeeded,
        failed=job.failed,
        pending=pending,
        progress_percent=progress,
        failures=failures,
    )


@router.get("/jobs/{job_id}/certificates", response_model=list[CertificateListItem])
def list_certificates(job_id: str, db: Session = Depends(get_db)):
    """Return all certificates for a job with download URLs where available."""
    job = _get_job_or_404(job_id, db)

    return [
        CertificateListItem(
            certificate_id=c.id,
            recipient_name=c.recipient_name,
            recipient_email=c.recipient_email,
            status=c.status,
            error=c.error,
            # Only provide a download link for successfully generated certs
            download_url=f"/api/certificates/{c.id}/download" if c.status == "SUCCESS" else None,
        )
        for c in job.certificates
    ]


@router.get("/certificates/{certificate_id}/download")
def download_certificate(certificate_id: int, db: Session = Depends(get_db)):
    """Serve the generated PDF file."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if cert.status != "SUCCESS":
        raise HTTPException(status_code=409, detail="Certificate not ready or generation failed")

    path = Path(cert.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="PDF file missing on disk")

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=f"certificate_{cert.id}.pdf",
    )
