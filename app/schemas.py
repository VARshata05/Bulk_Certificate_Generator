"""Pydantic v2 schemas for request validation and response serialization."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# --- Request schemas ---

class RecipientIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    course: str = Field(..., min_length=1)


class JobCreate(BaseModel):
    recipients: list[RecipientIn] = Field(..., min_length=1, max_length=1000)


# --- Response schemas ---

class CertificateOut(BaseModel):
    id: int
    job_id: str
    recipient_name: str
    recipient_email: str
    course_name: str
    status: str
    file_path: str | None
    error: str | None

    # Pydantic v2 way to read ORM objects directly
    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: str
    status: str
    total: int
    succeeded: int
    failed: int
    created_at: datetime
    certificates: list[CertificateOut] = []

    model_config = {"from_attributes": True}


# --- Endpoint-specific response schemas ---

class FailureDetail(BaseModel):
    certificate_id: int
    recipient_email: str
    error: str | None


class JobStatusOut(BaseModel):
    job_id: str
    status: str
    total: int
    succeeded: int
    failed: int
    pending: int
    progress_percent: float
    failures: list[FailureDetail]


class CertificateListItem(BaseModel):
    certificate_id: int
    recipient_name: str
    recipient_email: str
    status: str
    error: str | None
    download_url: str | None
