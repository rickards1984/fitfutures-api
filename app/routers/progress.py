"""Unit/task progress router.

- GET   /v1/progress/placement/{id}   learner's unit + task progress
- PATCH /v1/progress/task/{task_id}   set a single task's status (learner only)

Progress rows are created lazily: a placement starts with none, and the UI
treats any missing task as `not_started`.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    PlacementProgressResponse,
    TaskProgressOut,
    TaskStatusUpdateRequest,
    UnitProgressOut,
)
from app.services.placements import (
    assert_can_view_placement,
    assert_is_owner,
    fetch_placement,
)
from app.services.units import derive_unit_status

router = APIRouter(prefix="/progress", tags=["progress"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/placement/{placement_id}", response_model=PlacementProgressResponse)
async def placement_progress(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> PlacementProgressResponse:
    """Return all stored unit + task progress for a placement."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    units = await run_in_threadpool(
        lambda: supabase.table("learner_unit_progress")
        .select("*")
        .eq("placement_id", placement_id)
        .execute()
    )
    tasks = await run_in_threadpool(
        lambda: supabase.table("learner_task_progress")
        .select("*")
        .eq("placement_id", placement_id)
        .execute()
    )
    return PlacementProgressResponse(
        placement_id=placement_id,
        units=[UnitProgressOut(**row) for row in (units.data or [])],
        tasks=[TaskProgressOut(**row) for row in (tasks.data or [])],
    )


@router.patch("/task/{task_id}", response_model=TaskProgressOut)
async def update_task_status(
    task_id: str,
    body: TaskStatusUpdateRequest,
    user: AuthContext = Depends(get_current_user),
) -> TaskProgressOut:
    """Set one task's status, then re-derive + persist the unit's status."""
    supabase = get_supabase()

    task = await run_in_threadpool(
        lambda: supabase.table("unit_tasks")
        .select("id, unit_id")
        .eq("id", task_id)
        .limit(1)
        .execute()
    )
    if not task.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found."
        )
    unit_id = task.data[0]["unit_id"]

    placement = await run_in_threadpool(
        lambda: fetch_placement(supabase, body.placement_id)
    )
    assert_is_owner(placement, user)

    new_status = body.status.value
    task_row = {
        "placement_id": body.placement_id,
        "unit_task_id": task_id,
        "status": new_status,
        "completed_at": _now() if new_status == "complete" else None,
    }
    saved = await run_in_threadpool(
        lambda: supabase.table("learner_task_progress")
        .upsert(task_row, on_conflict="placement_id,unit_task_id")
        .execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update task status.",
        )

    await _resync_unit_status(supabase, body.placement_id, unit_id)
    return TaskProgressOut(**saved.data[0])


async def _resync_unit_status(supabase, placement_id: str, unit_id: str) -> None:
    """Recompute the unit's status from its tasks and upsert it."""
    unit_tasks = await run_in_threadpool(
        lambda: supabase.table("unit_tasks").select("id").eq("unit_id", unit_id).execute()
    )
    task_ids = [t["id"] for t in (unit_tasks.data or [])]
    if not task_ids:
        return

    progress = await run_in_threadpool(
        lambda: supabase.table("learner_task_progress")
        .select("unit_task_id, status")
        .eq("placement_id", placement_id)
        .in_("unit_task_id", task_ids)
        .execute()
    )
    status_by_task = {p["unit_task_id"]: p["status"] for p in (progress.data or [])}
    statuses = [status_by_task.get(tid, "not_started") for tid in task_ids]
    derived = derive_unit_status(statuses)

    existing = await run_in_threadpool(
        lambda: supabase.table("learner_unit_progress")
        .select("started_at")
        .eq("placement_id", placement_id)
        .eq("unit_id", unit_id)
        .limit(1)
        .execute()
    )
    started_at = (existing.data[0].get("started_at") if existing.data else None)
    if started_at is None and derived != "not_started":
        started_at = _now()

    unit_row = {
        "placement_id": placement_id,
        "unit_id": unit_id,
        "status": derived,
        "started_at": started_at,
        "completed_at": _now() if derived == "complete" else None,
    }
    await run_in_threadpool(
        lambda: supabase.table("learner_unit_progress")
        .upsert(unit_row, on_conflict="placement_id,unit_id")
        .execute()
    )
