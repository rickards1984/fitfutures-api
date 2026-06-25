"""Placements router.

- POST /v1/placements        tutor/admin creates a placement for a learner and
                             seeds its business + study milestone rows.
- GET  /v1/placements/mine   the caller's active placement, with derived week.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import PlacementCreateRequest, PlacementResponse
from app.services.placements import current_week_number, require_staff

router = APIRouter(prefix="/placements", tags=["placements"])

# Seeded per placement on creation (brief §4). (milestone_key, title).
BUSINESS_MILESTONES: list[tuple[str, str]] = [
    ("business_name_decided", "Business name decided"),
    ("insurance_in_place", "Insurance in place"),
    ("dbs_checked", "DBS check complete"),
    ("pricing_set", "Pricing set"),
    ("social_presence_live", "Social media presence live"),
    ("first_taster_delivered", "First taster session delivered"),
    ("first_paying_client", "First paying client"),
    ("booking_system_setup", "Booking system set up"),
    ("three_regular_clients", "Three regular clients"),
    ("business_plan_drafted", "Business plan drafted"),
]

STUDY_MILESTONES: list[tuple[str, str]] = [
    ("route_confirmation", "Route confirmation"),
    ("gym_duties_induction", "Gym duties induction"),
    ("pt_theory_milestones", "PT theory milestones"),
    ("pt_practical_preparation", "PT practical preparation"),
    ("pt_practical_assessment", "PT practical assessment"),
    ("pt_qualification_complete", "PT qualification complete"),
    ("specialist_pathway_selection", "Specialist pathway selection"),
    ("specialist_planning", "Specialist planning"),
    ("portfolio_evidence_check", "Portfolio evidence check"),
    ("final_placement_review", "Final placement review"),
]


def _with_week(placement: dict) -> PlacementResponse:
    """Attach the derived current week number to a placement row."""
    week = current_week_number(placement["start_date"])
    return PlacementResponse(current_week_number=week, **placement)


@router.post("", response_model=PlacementResponse, status_code=status.HTTP_201_CREATED)
async def create_placement(
    body: PlacementCreateRequest,
    user: AuthContext = Depends(get_current_user),
) -> PlacementResponse:
    """Create a placement (tutor/admin) and seed its milestone rows.

    Best-effort transactional: if milestone seeding fails after the placement
    row is created, the placement is deleted so we don't leave a half-built
    record behind.
    """
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    learner = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("id")
        .eq("id", body.learner_id)
        .limit(1)
        .execute()
    )
    if not learner.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learner profile not found.",
        )

    expected_end = body.expected_end_date or (
        body.start_date + timedelta(weeks=body.planned_weeks)
    )
    payload = {
        "learner_id": body.learner_id,
        "tutor_id": body.tutor_id or user.user_id,
        "supervisor_id": body.supervisor_id,
        "facility_name": body.facility_name,
        "route": body.route.value,
        "start_date": body.start_date.isoformat(),
        "expected_end_date": expected_end.isoformat(),
        "planned_weeks": body.planned_weeks,
        "notes": body.notes,
    }

    inserted = await run_in_threadpool(
        lambda: supabase.table("placements").insert(payload).execute()
    )
    if not inserted.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create placement.",
        )
    placement = inserted.data[0]
    placement_id = placement["id"]

    try:
        business_rows = [
            {"placement_id": placement_id, "milestone_key": key, "title": title}
            for key, title in BUSINESS_MILESTONES
        ]
        study_rows = [
            {"placement_id": placement_id, "milestone_key": key, "title": title}
            for key, title in STUDY_MILESTONES
        ]
        await run_in_threadpool(
            lambda: supabase.table("business_milestones").insert(business_rows).execute()
        )
        await run_in_threadpool(
            lambda: supabase.table("study_milestones").insert(study_rows).execute()
        )
    except Exception:
        # Roll back the placement so seeding stays all-or-nothing.
        await run_in_threadpool(
            lambda: supabase.table("placements").delete().eq("id", placement_id).execute()
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to seed placement milestones; placement rolled back.",
        )

    return _with_week(placement)


@router.get("/mine", response_model=PlacementResponse)
async def my_placement(
    user: AuthContext = Depends(get_current_user),
) -> PlacementResponse:
    """Return the caller's active placement (most recent if more than one)."""
    supabase = get_supabase()
    res = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("*")
        .eq("learner_id", user.user_id)
        .eq("status", "active")
        .order("start_date", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active placement found for this learner.",
        )
    return _with_week(res.data[0])
