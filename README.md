# Bulk Certificate Generator

Asynchronous batch certificate generation API built with FastAPI, SQLite, and ReportLab.

Topics: `fastapi`, `sqlalchemy`, `reportlab`

## 1. Overview

Bulk Certificate Generator is a lightweight backend service that accepts batches of certificate recipients via a REST API, generates individual PDF certificates asynchronously in the background, and tracks progress per job. Each certificate is rendered using ReportLab from a standard landscape template, and users can monitor job status or download individual generated PDFs once completed.

## 2. Setup

Requires Python 3.10+ (developed and verified on Python 3.13).

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 3. Run

Start the development server with uvicorn:

```bash
uvicorn app.main:app --reload
```

The server starts at `http://127.0.0.1:8000`. Interactive OpenAPI documentation and API testing are available at `http://127.0.0.1:8000/docs`.

## 4. Run Tests

Run the test suite using pytest:

```bash
pytest
```

Or with verbose output:

```bash
python -m pytest tests/ -v
```

## 5. API Usage

### End-to-End Walkthrough
1. **Create a Job**: Submit a list of recipients via `POST /api/jobs`. The API validates input, stores rows as `PENDING`, triggers a background worker thread, and returns HTTP 202 with a `job_id`.
2. **Poll Status**: Periodically check `GET /api/jobs/{job_id}` to inspect `progress_percent`, `status`, and any failures.
3. **Download Certificates**: Inspect the certificate list at `GET /api/jobs/{job_id}/certificates` and download successful certificates via `GET /api/certificates/{certificate_id}/download`.

---

### POST /api/jobs
Accepts a list of recipients (1 to 1000 items) and queues the generation.

**Sample Request:**
```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "recipients": [
      {"name": "Alice Johnson", "email": "alice@example.com", "course": "Python Core"},
      {"name": "Bob Smith", "email": "bob@example.com", "course": "FastAPI Web Apps"}
    ]
  }'
```

**Sample Response (HTTP 202 Accepted):**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "PENDING",
  "total": 2
}
```

**Validation Error Example (HTTP 422 Unprocessable Entity):**
If any recipient has an invalid email, empty name, or missing course, the entire batch is rejected:
```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "recipients": [
      {"name": "", "email": "invalid-email", "course": "Python"}
    ]
  }'
```

**Response (HTTP 422):**
```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "recipients", 0, "name"],
      "msg": "String should have at least 1 character",
      "input": ""
    },
    {
      "type": "value_error",
      "loc": ["body", "recipients", 0, "email"],
      "msg": "value is not a valid email address: An email address must have an @-sign.",
      "input": "invalid-email"
    }
  ]
}
```

---

### GET /api/jobs/{job_id}
Returns job status, completion counts, percentage progress, and a list of any failed certificates.

**Sample Request:**
```bash
curl http://127.0.0.1:8000/api/jobs/f47ac10b-58cc-4372-a567-0e02b2c3d479
```

**Sample Response (Job Completed With Errors — failure message is an illustrative example):**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "COMPLETED_WITH_ERRORS",
  "total": 2,
  "succeeded": 1,
  "failed": 1,
  "pending": 0,
  "progress_percent": 100.0,
  "failures": [
    {
      "certificate_id": 2,
      "recipient_email": "bob@example.com",
      "error": "Disk write failure (example)"
    }
  ]
}
```

---

### GET /api/jobs/{job_id}/certificates
Returns all certificates associated with the job. `download_url` is populated only when `status` is `SUCCESS`.

**Sample Request:**
```bash
curl http://127.0.0.1:8000/api/jobs/f47ac10b-58cc-4372-a567-0e02b2c3d479/certificates
```

**Sample Response:**
```json
[
  {
    "certificate_id": 1,
    "recipient_name": "Alice Johnson",
    "recipient_email": "alice@example.com",
    "status": "SUCCESS",
    "error": null,
    "download_url": "/api/certificates/1/download"
  },
  {
    "certificate_id": 2,
    "recipient_name": "Bob Smith",
    "recipient_email": "bob@example.com",
    "status": "FAILED",
    "error": "Disk write failure (example)",
    "download_url": null
  }
]
```

---

### GET /api/certificates/{certificate_id}/download
Downloads the generated PDF file. Returns HTTP 409 if the certificate is not yet processed or failed, and HTTP 404 if the certificate or file does not exist.

**Sample Request:**
```bash
curl -o certificate_1.pdf http://127.0.0.1:8000/api/certificates/1/download
```

---

## 6. Architecture

### File Structure
```
app/
  database.py     # SQLAlchemy engine, sessionmaker, WAL mode listener, get_db dependency
  main.py         # FastAPI app creation, startup table creation, health check endpoint
  models.py       # SQLAlchemy ORM models: Job and Certificate
  routes.py       # API endpoints (/api/jobs, /api/certificates)
  schemas.py      # Pydantic v2 validation models and response serializers
  services.py     # PDF generation with ReportLab and background process_job loop
tests/
  conftest.py     # Pytest fixtures: file-based SQLite, mocked worker thread, client
  test_foundation.py # Smoke tests for DB models, constraints, and validation
  test_jobs.py    # Integration tests for job flow, error isolation, and downloads
requirements.txt
```

### Request Flow
1. Client sends `POST /api/jobs` with an array of recipients.
2. Pydantic validates the request body. If any record is invalid, FastAPI halts and returns HTTP 422.
3. The route handler opens a database session, saves the `Job` row and related `Certificate` rows (all initialized to `PENDING`), commits the transaction, and starts a daemon `threading.Thread(target=process_job, args=(job.id,))`.
4. The client immediately receives HTTP 202 with the `job_id`.

### Processing Flow
1. `process_job` receives only the `job_id` string and opens its own isolated `SessionLocal()` session.
2. The job status transitions to `PROCESSING` and commits.
3. `process_job` iterates sequentially through the job certificates:
   - Within a `try...except` block, it calls `generate_certificate_pdf` using ReportLab.
   - On success: marks the certificate `SUCCESS`, records `file_path`, increments `job.succeeded`.
   - On exception: marks the certificate `FAILED`, records `error`, increments `job.failed`.
   - Commits after each certificate so that intermediate progress is immediately visible to polling clients.
4. When all certificates are evaluated, the job status is set to `COMPLETED` (if 0 failed) or `COMPLETED_WITH_ERRORS`, commits, and closes the session.

### Status Values

**Job Statuses:**
- `PENDING`: Record created, background thread has not yet begun processing.
- `PROCESSING`: Worker thread has picked up the job and is actively generating certificates.
- `COMPLETED`: All certificates generated successfully with zero errors.
- `COMPLETED_WITH_ERRORS`: All certificates processed, but at least one encountered an error.

**Certificate Statuses:**
- `PENDING`: Initial state awaiting generation.
- `SUCCESS`: PDF generated and stored on disk.
- `FAILED`: Generation failed; the error string is captured in the database record.

## 7. Design Decisions

- **Daemon thread instead of Celery / Redis:**
  * *Reason:* For a focused, assignment-scale application, running Redis and Celery adds unnecessary infrastructure overhead.
  * *Context:* I tried BackgroundTasks first, and the server hung: the request's DB session was still open when the task tried to write, so SQLite's lock blocked it. Spawning a plain `threading.Thread` right after `db.commit()` and passing only the primitive `job.id` allows the request's DB session to close cleanly, letting `process_job` open and close its own independent session.
  * *Alternative considered:* Celery with Redis, or RQ.

- **SQLite with WAL mode and `check_same_thread=False`:**
  * *Reason:* Because the request thread and the background worker thread run concurrently, SQLite requires `check_same_thread=False` so connections can be utilized across threads. We enable Write-Ahead Logging (`PRAGMA journal_mode=WAL`) on connection so readers (status checks) do not block writers (the background generator).
  * *Alternative considered:* Default rollback journal mode (caused database lock timeouts during concurrent writes).

- **Strict request rejection (422) vs. per-certificate generation isolation:**
  * *Reason:* Syntactic or schema validation errors (malformed email, missing fields) indicate a bad request payload and fail the entire HTTP request upfront with a standard 422 error. In contrast, runtime generation issues (corrupt font, rendering error, or disk failure) are treated as transient item failures and isolated per certificate so one recipient's error never stops the remaining batch.
  * *Alternative considered:* Accepting partial batches on validation error, which complicates client error tracking.

- **PDF filenames use `certificate.id` rather than recipient names:**
  * *Reason:* Recipient names often contain spaces, accents, special punctuation, or duplicate names. Naming files `<certificate.id>.pdf` prevents directory traversal risks, character encoding problems, and file overwrites.
  * *Alternative considered:* Sanitized recipient names (vulnerable to collisions for duplicate names).

- **Progress tracking stored on the Job row:**
  * *Reason:* Tracking `succeeded` and `failed` counters directly on the `Job` row and updating after each certificate generation avoids expensive `COUNT(*)` aggregate queries on the `certificates` table during client polling.
  * *Alternative considered:* Dynamically querying `COUNT(*)` grouped by status on every poll.

- **Maximum 1000 recipients limit:**
  * *Reason:* Enforcing `max_length=1000` in Pydantic's `JobCreate` schema protects the thread and SQLite database from unbound resource exhaustion and memory bloat.
  * *Alternative considered:* Unlimited batch sizes or streaming file uploads.

## 8. Limitations and Future Scope

- **Process failure resilience:** Because background generation runs in an in-process daemon thread, restarting or crashing the server during a run terminates the thread, leaving the job in `PROCESSING`. In production, this should be handled either with a distributed queue (Celery/RQ) with worker persistence or a startup recovery hook that inspects and marks stale `PROCESSING` jobs as failed.
- **Retry endpoint:** An endpoint such as `POST /api/jobs/{job_id}/retry` to retry only certificates in `FAILED` status.
- **Pagination:** Adding cursor- or limit/offset-based pagination to `GET /api/jobs/{job_id}/certificates` for large batch sizes.
- **Bulk download:** A zip archive download endpoint (`GET /api/jobs/{job_id}/download-all`) to retrieve all generated PDFs in a single archive.
- **Production database and auth:** Migration from SQLite to PostgreSQL with Alembic migrations, alongside API key or JWT-based authentication.
- **Email delivery:** Asynchronous dispatch of the generated PDF directly to the recipient's email address upon generation.

## 9. Learning

I tried `BackgroundTasks` first, and the server hung because the request's DB session was still open when the task tried to write, so SQLite's lock blocked it. Switching to a plain daemon thread with its own `SessionLocal()` fixed that immediately.

In tests, trying to monkeypatch `threading.Thread` failed with a `TypeError` from AnyIO's internal subclassing, so making the route worker a no-op and calling `process_job()` directly gave fast, deterministic tests without sleeps or threads. Testing also showed why file-based SQLite (`tmp_path`) was necessary over `:memory:`, since in-memory SQLite creates a separate empty database whenever a new session opens.

Finally, breaking the error handling on purpose and watching `test_single_failure_is_isolated` fail proved the test suite was actually catching what mattered.

