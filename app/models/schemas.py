"""Pydantic v2 schemas.

Phase 1: shared enums + the health payload only. Request/response models
are added per-router as each phase lands (one schema per new route, per the
working agreement).
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    learner = "learner"
    tutor = "tutor"
    supervisor = "supervisor"
    admin = "admin"


class LearnerRoute(str, Enum):
    route_a = "route_a"
    route_b = "route_b"


class PlacementStatus(str, Enum):
    active = "active"
    referred = "referred"
    complete = "complete"
    withdrawn = "withdrawn"


class RAGStatus(str, Enum):
    green = "green"
    amber = "amber"
    red = "red"
    no_entry = "no_entry"


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


# --- Auth / profile -------------------------------------------------------


class ProfileUpsertRequest(BaseModel):
    """Body for POST /v1/auth/profile — sent by the web app on first login.

    `email` and the user id come from the verified JWT, never the client.
    """

    full_name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = None


class ProfileResponse(BaseModel):
    id: str
    full_name: str
    email: str
    role: UserRole
    phone: Optional[str] = None
    whatsapp_opt_in: bool = False
    push_opt_in: bool = False
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
