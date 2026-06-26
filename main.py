"""FitFutures API — FastAPI entrypoint.

Phase 1 (skeleton): boots the app, mounts CORS, exposes /health.
Routers are mounted as they come online in later phases.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import (
    auth,
    business,
    evidence,
    kpi,
    placements,
    progress,
    units,
)

app = FastAPI(
    title="FitFutures API",
    version="0.1.0",
    description="UKFI FitFutures placement programme API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness probe. Returns 200 with basic service metadata."""
    return {"status": "ok", "service": "fitfutures-api", "version": app.version}


# Routers are mounted under /v1 as each phase lands.
app.include_router(auth.router, prefix="/v1")
app.include_router(placements.router, prefix="/v1")
app.include_router(kpi.router, prefix="/v1")
app.include_router(units.router, prefix="/v1")
app.include_router(progress.router, prefix="/v1")
app.include_router(evidence.router, prefix="/v1")
app.include_router(business.router, prefix="/v1")
