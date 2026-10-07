"""Database engine, session factory, and FastAPI dependency."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# SQLite for simplicity — single file, zero config
DATABASE_URL = "sqlite:///./certificates.db"

engine = create_engine(
    DATABASE_URL,
    # Required for SQLite to work correctly with FastAPI's threading model
    connect_args={"check_same_thread": False},
)


# Enable WAL mode so background threads can write while requests read
@event.listens_for(engine, "connect")
def _set_sqlite_wal(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# Modern SQLAlchemy 2.x base — replaces the legacy declarative_base()
class Base(DeclarativeBase):
    pass


def get_db():
    """Yield a DB session per request, ensuring cleanup on completion."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
