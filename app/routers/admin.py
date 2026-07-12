"""Admin router (Phase 9a — enrolment + roster).

Staff-only (tutor/admin) views for the placement coordinator:

- GET /v1/admin/learners              all learners, flagged with whether they
                                      already have an active placement
- GET /v1/admin/placements            the active roster (name, facility, week,
                                      latest RAG)
- GET /v1/admin/learner/{id}/summary  read-only detail for a learner's active
                                      placement (KPI totals + unit progress)

Enrolment itself reuses POST /v1/placements (which seeds milestone rows).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    AdminLearnerItem,
    AdminLearnersResponse,
    AdminLearnerSummary,
    AdminPlacementItem,
    AdminPlacementsResponse,
    AdminUnitProgressItem,
    KpiTotalLine,
)
from app.services.kpi_calc import METRICS
from app.services.placements import current_week_number, require_staff
from app.services.units import derive_unit_status

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/learners", response_model=AdminLearnersResponse)
async def list_learners(
    user: AuthContext = Depends(get_current_user),
) -> AdminLearnersResponse:
    """All learner profiles, newest first, flagged by active-placement status."""
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    profiles = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("id, full_name, email, created_at")
        .eq("role", "learner")
        .order("created_at", desc=True)
        .execute()
    )
    rows = profiles.data or []

    active = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("learner_id")
        .eq("status", "active")
        .execute()
    )
    active_ids = {r["learner_id"] for r in (active.data or [])}

    items = [
        AdminLearnerItem(
            id=r["id"],
            full_name=r.get("full_name") or "Unknown learner",
            email=r.get("email") or "",
            created_at=r.get("created_at"),
            has_active_placement=r["id"] in active_ids,
        )
        for r in rows
    ]
    return AdminLearnersResponse(items=items)


@router.get("/placements", response_model=AdminPlacementsResponse)
async def list_active_placements(
    user: AuthContext = Depends(get_current_user),
) -> AdminPlacementsResponse:
    """Active roster: learner name, facility, week X of Y, latest week's RAG."""
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    placements = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("*")
        .eq("status", "active")
        .order("start_date", desc=True)
        .execute()
    )
    rows = placements.data or []
    if not rows:
        return AdminPlacementsResponse(items=[])

    learner_ids = list({r["learner_id"] for r in rows})
    placement_ids = [r["id"] for r in rows]

    profiles = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("id, full_name")
        .in_("id", learner_ids)
        .execute()
    )
    names = {p["id"]: p.get("full_name") or "Unknown learner" for p in (profiles.data or [])}

    # Latest RAG per placement: fetch all weeks once, keep the highest week_number.
    entries = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select("placement_id, week_number, overall_status")
        .in_("placement_id", placement_ids)
        .order("week_number", desc=True)
        .execute()
    )
    latest_rag: dict[str, str] = {}
    for e in entries.data or []:
        latest_rag.setdefault(e["placement_id"], e.get("overall_status") or "no_entry")

    items = [
        AdminPlacementItem(
            placement_id=r["id"],
            learner_id=r["learner_id"],
            learner_name=names.get(r["learner_id"], "Unknown learner"),
            facility_name=r.get("facility_name") or "—",
            route=r["route"],
            current_week_number=current_week_number(r["start_date"]),
            planned_weeks=r.get("planned_weeks") or 0,
            latest_rag=latest_rag.get(r["id"], "no_entry"),
        )
        for r in rows
    ]
    return AdminPlacementsResponse(items=items)


@router.get("/learner/{learner_id}/summary", response_model=AdminLearnerSummary)
async def learner_summary(
    learner_id: str,
    user: AuthContext = Depends(get_current_user),
) -> AdminLearnerSummary:
    """Read-only detail for a learner's active placement: KPI totals + units."""
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    placement_res = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("*")
        .eq("learner_id", learner_id)
        .eq("status", "active")
        .order("start_date", desc=True)
        .limit(1)
        .execute()
    )
    if not placement_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This learner has no active placement.",
        )
    placement = placement_res.data[0]
    placement_id = placement["id"]

    learner = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("full_name")
        .eq("id", learner_id)
        .limit(1)
        .execute()
    )
    learner_name = (
        learner.data[0].get("full_name") if learner.data else None
    ) or "Unknown learner"

    # KPI totals: cumulative actuals vs total targets.
    entries = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select("*")
        .eq("placement_id", placement_id)
        .execute()
    )
    rows = entries.data or []
    kpi_lines = [
        KpiTotalLine(
            key=m.key,
            label=m.label,
            actual=sum(float(r.get(m.actual_col) or 0) for r in rows),
            target=float(placement.get(m.total_target_col) or 0),
        )
        for m in METRICS
    ]

    units_summary, units_complete, units_total = await _unit_progress(
        supabase, placement_id
    )

    return AdminLearnerSummary(
        learner_id=learner_id,
        learner_name=learner_name,
        placement_id=placement_id,
        facility_name=placement.get("facility_name") or "—",
        route=placement["route"],
        current_week_number=current_week_number(placement["start_date"]),
        planned_weeks=placement.get("planned_weeks") or 0,
        weeks_logged=len(rows),
        kpi_lines=kpi_lines,
        units=units_summary,
        units_complete=units_complete,
        units_total=units_total,
    )


async def _unit_progress(supabase, placement_id: str):
    """Per-unit status for a placement, derived from stored task progress."""
    units = await run_in_threadpool(
        lambda: supabase.table("units")
        .select("id, unit_number, title")
        .order("unit_number")
        .execute()
    )
    unit_rows = units.data or []

    tasks = await run_in_threadpool(
        lambda: supabase.table("unit_tasks").select("id, unit_id").execute()
    )
    tasks_by_unit: dict[str, list[str]] = {}
    for t in tasks.data or []:
        tasks_by_unit.setdefault(t["unit_id"], []).append(t["id"])

    progress = await run_in_threadpool(
        lambda: supabase.table("learner_task_progress")
        .select("unit_task_id, status")
        .eq("placement_id", placement_id)
        .execute()
    )
    status_by_task = {p["unit_task_id"]: p["status"] for p in (progress.data or [])}

    items: list[AdminUnitProgressItem] = []
    complete = 0
    for u in unit_rows:
        task_ids = tasks_by_unit.get(u["id"], [])
        statuses = [status_by_task.get(tid, "not_started") for tid in task_ids]
        derived = derive_unit_status(statuses)
        if derived == "complete":
            complete += 1
        items.append(
            AdminUnitProgressItem(
                unit_number=u["unit_number"],
                title=u["title"],
                status=derived,
            )
        )
    return items, complete, len(unit_rows)
