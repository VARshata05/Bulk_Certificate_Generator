"""Certificate generation and job processing logic."""

import os
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from app.database import SessionLocal
from app.models import Job, Certificate

OUTPUT_DIR = Path("generated")


def generate_certificate_pdf(cert: Certificate, output_dir: Path) -> str:
    """Render a single certificate as a landscape A4 PDF.

    Uses certificate.id for the filename to avoid filesystem issues
    with special characters in recipient names.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{cert.id}.pdf"

    width, height = landscape(A4)
    c = canvas.Canvas(str(filepath), pagesize=landscape(A4))

    # Title
    c.setFont("Helvetica-Bold", 36)
    c.drawCentredString(width / 2, height - 6 * cm, "Certificate of Completion")

    # Recipient
    c.setFont("Helvetica", 24)
    c.drawCentredString(width / 2, height - 10 * cm, "This certifies that")
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 12 * cm, cert.recipient_name)

    # Course
    c.setFont("Helvetica", 24)
    c.drawCentredString(width / 2, height - 15 * cm, "has successfully completed")
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 17 * cm, cert.course_name)

    # Date
    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 20 * cm, date.today().strftime("%B %d, %Y"))

    c.save()
    return str(filepath)


# BackgroundTasks is the right choice here: certificate generation is
# short-lived CPU work (a few seconds per batch), not long-running enough
# to justify the operational overhead of Celery + Redis.
def process_job(job_id: str) -> None:
    """Generate all certificates for a job, updating progress after each one.

    Opens its own DB session so it's fully independent of the HTTP request
    lifecycle — the request's session is already closed by the time this runs.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        job.status = "PROCESSING"
        db.commit()

        for cert in job.certificates:
            try:
                path = generate_certificate_pdf(cert, OUTPUT_DIR)
                cert.status = "SUCCESS"
                cert.file_path = path
                job.succeeded += 1
            except Exception as e:
                cert.status = "FAILED"
                cert.error = str(e)
                job.failed += 1

            # Commit per certificate so progress is visible mid-run
            db.commit()
        

        job.status = "COMPLETED" if job.failed == 0 else "COMPLETED_WITH_ERRORS"
        db.commit()
    finally:
        db.close()
