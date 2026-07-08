"""Pydantic v2 schemas.

Phase 1: shared enums + the health payload only. Request/response models
are added per-router as each phase lands (one schema per new route, per the
working agreement).
"""
from datetime import date, datetime
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


class TaskStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    complete = "complete"
    not_applicable = "not_applicable"


class UnitStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    complete = "complete"


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


# --- Placements -----------------------------------------------------------


class PlacementCreateRequest(BaseModel):
    """Body for POST /v1/placements (tutor/admin only).

    Weekly + cumulative targets are the fixed spreadsheet values stored as
    column defaults on the table, so they are not part of the request.
    """

    learner_id: str
    facility_name: str = Field(min_length=1, max_length=200)
    route: LearnerRoute = LearnerRoute.route_a
    start_date: date
    planned_weeks: int = Field(default=18, ge=1, le=52)
    tutor_id: Optional[str] = None
    supervisor_id: Optional[str] = None
    expected_end_date: Optional[date] = None
    notes: Optional[str] = None


class PlacementResponse(BaseModel):
    id: str
    learner_id: str
    tutor_id: Optional[str] = None
    supervisor_id: Optional[str] = None
    facility_name: str
    route: LearnerRoute
    status: PlacementStatus
    start_date: date
    expected_end_date: Optional[date] = None
    actual_end_date: Optional[date] = None
    planned_weeks: int
    # Derived: current week of the placement (1-based), not stored.
    current_week_number: int

    # Fixed weekly targets
    wk_target_placement_hours: float
    wk_target_study_hours: float
    wk_target_member_conversations: int
    wk_target_ex_member_contacts: int
    wk_target_retention_saves: int
    wk_target_campaign_touches: int
    wk_target_tasters_booked: int
    wk_target_consultations: int
    wk_target_conversions: int

    # Cumulative placement targets
    total_target_placement_hours: int
    total_target_study_hours: int
    total_target_member_conversations: int
    total_target_ex_member_contacts: int
    total_target_retention_saves: int
    total_target_campaign_touches: int
    total_target_tasters_booked: int
    total_target_consultations: int
    total_target_conversions: int

    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# --- KPI totals -----------------------------------------------------------


class KpiTotalLine(BaseModel):
    """One cumulative metric: actual-to-date vs the placement total target."""

    key: str
    label: str
    actual: float
    target: float


class KpiTotalsResponse(BaseModel):
    placement_id: str
    weeks_logged: int
    lines: list[KpiTotalLine]


# --- Weekly KPI entry -----------------------------------------------------


class KpiWeekSubmitRequest(BaseModel):
    """Body for POST /v1/kpi/placement/{id}/week/{n} — a week's actuals."""

    actual_placement_hours: float = Field(default=0, ge=0)
    actual_study_hours: float = Field(default=0, ge=0)
    actual_member_conversations: int = Field(default=0, ge=0)
    actual_ex_member_contacts: int = Field(default=0, ge=0)
    actual_retention_saves: int = Field(default=0, ge=0)
    actual_campaign_touches: int = Field(default=0, ge=0)
    actual_tasters_booked: int = Field(default=0, ge=0)
    actual_consultations: int = Field(default=0, ge=0)
    actual_conversions: int = Field(default=0, ge=0)
    reflection: Optional[str] = None
    key_issue: Optional[str] = None
    # Defaults to start_date + (n-1) weeks when omitted.
    week_commencing: Optional[date] = None


class KpiEntryResponse(BaseModel):
    id: str
    placement_id: str
    week_number: int
    week_commencing: date
    actual_placement_hours: float
    actual_study_hours: float
    actual_member_conversations: int
    actual_ex_member_contacts: int
    actual_retention_saves: int
    actual_campaign_touches: int
    actual_tasters_booked: int
    actual_consultations: int
    actual_conversions: int
    reflection: Optional[str] = None
    key_issue: Optional[str] = None
    overall_status: RAGStatus
    ai_coach_message: Optional[str] = None
    ai_coach_generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# --- Units & tasks --------------------------------------------------------


class UnitTaskOut(BaseModel):
    id: str
    unit_id: str
    task_order: int
    description: str
    is_mandatory: bool
    requires_evidence: bool
    requires_supervisor_sign: bool


class UnitOut(BaseModel):
    id: str
    unit_number: int
    title: str
    aim: str
    is_mandatory: bool
    suggested_hours_min: Optional[int] = None
    suggested_hours_max: Optional[int] = None
    route_applicability: str
    tasks: list[UnitTaskOut]


class UnitProgressOut(BaseModel):
    unit_id: str
    status: UnitStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tutor_signed_at: Optional[datetime] = None
    supervisor_signed_at: Optional[datetime] = None
    notes: Optional[str] = None


class TaskProgressOut(BaseModel):
    unit_task_id: str
    placement_id: str
    status: TaskStatus
    completed_at: Optional[datetime] = None
    supervisor_initials: Optional[str] = None
    supervisor_signed_at: Optional[datetime] = None
    notes: Optional[str] = None


class PlacementProgressResponse(BaseModel):
    placement_id: str
    units: list[UnitProgressOut]
    tasks: list[TaskProgressOut]


class TaskStatusUpdateRequest(BaseModel):
    """Body for PATCH /v1/progress/task/{task_id}."""

    placement_id: str
    status: TaskStatus


# --- Evidence -------------------------------------------------------------


class EvidenceUploadUrlRequest(BaseModel):
    placement_id: str
    filename: str = Field(min_length=1, max_length=255)
    content_type: Optional[str] = None


class EvidenceUploadUrlResponse(BaseModel):
    bucket: str
    path: str
    token: str
    signed_url: str


class EvidenceCreateRequest(BaseModel):
    """Record an evidence item after the file has been uploaded."""

    placement_id: str
    path: str  # storage object path returned by the upload-url step
    title: str = Field(min_length=1, max_length=200)
    file_type: str
    file_size_bytes: Optional[int] = None
    unit_task_id: Optional[str] = None
    description: Optional[str] = None


class EvidenceItemResponse(BaseModel):
    id: str
    placement_id: str
    unit_task_id: Optional[str] = None
    kpi_entry_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    file_url: str  # storage object path
    file_type: str
    file_size_bytes: Optional[int] = None
    uploaded_by: str
    supervisor_approved: Optional[bool] = None
    supervisor_approved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    # Short-lived signed URL for display/download (computed on read).
    download_url: Optional[str] = None


# --- Business milestones --------------------------------------------------


class BusinessMilestoneResponse(BaseModel):
    id: str
    placement_id: str
    milestone_key: str
    title: str
    status: TaskStatus
    target_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    evidence_notes: Optional[str] = None
    blocking_issue: Optional[str] = None
    next_action: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BusinessMilestoneUpdateRequest(BaseModel):
    """Partial update — only provided fields are written."""

    status: Optional[TaskStatus] = None
    evidence_notes: Optional[str] = None
    target_date: Optional[date] = None
    next_action: Optional[str] = None


# --- Coach chat -----------------------------------------------------------


class CoachMessageOut(BaseModel):
    id: str
    placement_id: str
    role: str  # 'user' | 'assistant'
    content: str
    created_at: Optional[datetime] = None


class CoachChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class CoachChatResponse(BaseModel):
    user_message: CoachMessageOut
    assistant_message: CoachMessageOut


# --- Web push -------------------------------------------------------------


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    """The browser PushSubscription JSON (endpoint + keys)."""

    endpoint: str
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


class SimpleStatusResponse(BaseModel):
    ok: bool
    detail: Optional[str] = None


class ReminderRunResponse(BaseModel):
    """Summary of an /internal/reminders/run pass."""

    active_placements: int
    nudged: int
    skipped: int
    failed: int
