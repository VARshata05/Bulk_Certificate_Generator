"""SQLAlchemy ORM models for jobs and certificates."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    """Generate a UUID string — keeps IDs portable across DBs."""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp — avoids naive datetime pitfalls."""
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    total: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Cascade delete so removing a job cleans up its certificates
    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(100))
    recipient_email: Mapped[str] = mapped_column(String(255))
    course_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    job: Mapped["Job"] = relationship(back_populates="certificates")
