"""Pydantic v2 schemas.

Phase 1: shared enums + the health payload only. Request/response models
are added per-router as each phase lands (one schema per new route, per the
working agreement).
"""
from enum import Enum

from pydantic import BaseModel


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
