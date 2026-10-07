"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup — avoids needing a separate migration step."""
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
def health_check():
    """Simple liveness probe."""
    return {"status": "ok"}
