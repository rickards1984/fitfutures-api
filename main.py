"""FitFutures API — FastAPI entrypoint.

Phase 1 (skeleton): boots the app, mounts CORS, exposes /health.
Routers are mounted as they come online in later phases.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

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


# Routers are mounted here as each phase lands, e.g.:
# from app.routers import placements
# app.include_router(placements.router, prefix="/v1")
