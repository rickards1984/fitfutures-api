"""Business start-up milestones router.

- GET   /v1/business/placement/{id}   the placement's business milestones
- PATCH /v1/business/{milestone_id}   update status / notes / target / next action
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    BusinessMilestoneResponse,
    BusinessMilestoneUpdateRequest,
)
from app.services.placements import (
    assert_can_view_placement,
    assert_is_owner,
    fetch_placement,
)

router = APIRouter(prefix="/business", tags=["business"])


@router.get("/placement/{placement_id}", response_model=list[BusinessMilestoneResponse])
async def list_business_milestones(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> list[BusinessMilestoneResponse]:
    """Return a placement's business start-up milestones, oldest first."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    res = await run_in_threadpool(
        lambda: supabase.table("business_milestones")
        .select("*")
        .eq("placement_id", placement_id)
        .order("created_at")
        .execute()
    )
    return [BusinessMilestoneResponse(**row) for row in (res.data or [])]


@router.patch("/{milestone_id}", response_model=BusinessMilestoneResponse)
async def update_business_milestone(
    milestone_id: str,
    body: BusinessMilestoneUpdateRequest,
    user: AuthContext = Depends(get_current_user),
) -> BusinessMilestoneResponse:
    """Partial update of a milestone (learner-owned placement only)."""
    supabase = get_supabase()

    existing = await run_in_threadpool(
        lambda: supabase.table("business_milestones")
        .select("*")
        .eq("id", milestone_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found."
        )
    milestone = existing.data[0]

    placement = await run_in_threadpool(
        lambda: fetch_placement(supabase, milestone["placement_id"])
    )
    assert_is_owner(placement, user)

    fields = body.model_fields_set
    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if "status" in fields and body.status is not None:
        updates["status"] = body.status.value
        updates["completed_at"] = (
            datetime.now(timezone.utc).isoformat()
            if body.status.value == "complete"
            else None
        )
    if "evidence_notes" in fields:
        updates["evidence_notes"] = body.evidence_notes
    if "target_date" in fields:
        updates["target_date"] = body.target_date.isoformat() if body.target_date else None
    if "next_action" in fields:
        updates["next_action"] = body.next_action

    saved = await run_in_threadpool(
        lambda: supabase.table("business_milestones")
        .update(updates)
        .eq("id", milestone_id)
        .execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update milestone.",
        )
    return BusinessMilestoneResponse(**saved.data[0])
