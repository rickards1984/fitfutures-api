"""Coach chat router (Phase 7, step A).

- GET  /v1/coach/placement/{id}/messages   conversation history
- POST /v1/coach/placement/{id}/chat        learner message → coach reply

Each chat call injects a fresh context snapshot (route, week, KPIs, unit
progress, business milestones), persists both turns to `coach_messages`, and
reuses the shared `generate_coach_response` provider abstraction.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    CoachChatRequest,
    CoachChatResponse,
    CoachMessageOut,
)
from app.services import ai_coach
from app.services.kpi_calc import METRICS
from app.services.placements import (
    assert_can_view_placement,
    assert_is_owner,
    current_week_number,
    fetch_placement,
)

logger = logging.getLogger("fitfutures.coach")

router = APIRouter(prefix="/coach", tags=["coach"])

_HISTORY_LIMIT = 20  # most recent turns sent back to the model


@router.get("/placement/{placement_id}/messages", response_model=list[CoachMessageOut])
async def coach_messages(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> list[CoachMessageOut]:
    """Return the full coach conversation for a placement, oldest first."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    res = await run_in_threadpool(
        lambda: supabase.table("coach_messages")
        .select("id, placement_id, role, content, created_at")
        .eq("placement_id", placement_id)
        .order("created_at")
        .execute()
    )
    return [CoachMessageOut(**row) for row in (res.data or [])]


@router.post("/placement/{placement_id}/chat", response_model=CoachChatResponse)
async def coach_chat(
    placement_id: str,
    body: CoachChatRequest,
    user: AuthContext = Depends(get_current_user),
) -> CoachChatResponse:
    """Send a learner message, get + persist a coach reply."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    assert_is_owner(placement, user)

    context = await _build_context(supabase, placement)

    history_res = await run_in_threadpool(
        lambda: supabase.table("coach_messages")
        .select("role, content")
        .eq("placement_id", placement_id)
        .order("created_at")
        .execute()
    )
    history = (history_res.data or [])[-_HISTORY_LIMIT:]

    messages = ai_coach.build_chat_messages(context, history, body.message)
    try:
        reply = await run_in_threadpool(
            ai_coach.generate_coach_response, messages, context, 320
        )
    except Exception:  # noqa: BLE001
        logger.exception("Coach chat failed for placement %s", placement_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The coach is unavailable right now — please try again.",
        )

    # Persist both turns (user first so created_at ordering is stable).
    user_row = await run_in_threadpool(
        lambda: supabase.table("coach_messages")
        .insert(
            {
                "placement_id": placement_id,
                "role": "user",
                "content": body.message,
                "context_snapshot": context,
            }
        )
        .execute()
    )
    assistant_row = await run_in_threadpool(
        lambda: supabase.table("coach_messages")
        .insert(
            {"placement_id": placement_id, "role": "assistant", "content": reply}
        )
        .execute()
    )
    return CoachChatResponse(
        user_message=CoachMessageOut(**user_row.data[0]),
        assistant_message=CoachMessageOut(**assistant_row.data[0]),
    )


async def _build_context(supabase, placement: dict) -> dict:
    """Gather the per-call context snapshot for the prompt."""
    placement_id = placement["id"]

    # KPI cumulative totals + latest logged week.
    kpi_res = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select("*")
        .eq("placement_id", placement_id)
        .order("week_number")
        .execute()
    )
    kpi_rows = kpi_res.data or []
    kpi_totals = [
        {
            "label": m.label,
            "actual": sum(float(r.get(m.actual_col) or 0) for r in kpi_rows),
            "target": float(placement.get(m.total_target_col) or 0),
        }
        for m in METRICS
    ]
    latest_week = None
    if kpi_rows:
        last = kpi_rows[-1]
        latest_week = {
            "week_number": last.get("week_number"),
            "overall_status": last.get("overall_status"),
        }

    # Unit progress counts (units with no row default to not_started).
    units_res = await run_in_threadpool(
        lambda: supabase.table("units").select("id").execute()
    )
    unit_ids = [u["id"] for u in (units_res.data or [])]
    unit_prog_res = await run_in_threadpool(
        lambda: supabase.table("learner_unit_progress")
        .select("unit_id, status")
        .eq("placement_id", placement_id)
        .execute()
    )
    unit_status = {u["unit_id"]: u["status"] for u in (unit_prog_res.data or [])}
    units = {"complete": 0, "in_progress": 0, "not_started": 0}
    for uid in unit_ids:
        units[unit_status.get(uid, "not_started")] = (
            units.get(unit_status.get(uid, "not_started"), 0) + 1
        )

    # Business milestones counts + outstanding list.
    biz_res = await run_in_threadpool(
        lambda: supabase.table("business_milestones")
        .select("title, status")
        .eq("placement_id", placement_id)
        .order("created_at")
        .execute()
    )
    biz_rows = biz_res.data or []
    business = {"complete": 0, "in_progress": 0, "not_started": 0}
    next_up = []
    for m in biz_rows:
        s = m.get("status", "not_started")
        business[s] = business.get(s, 0) + 1
        if s != "complete" and len(next_up) < 5:
            next_up.append(m.get("title"))
    business["next_up"] = next_up

    return {
        "route": placement.get("route"),
        "week_number": current_week_number(placement["start_date"]),
        "planned_weeks": placement.get("planned_weeks"),
        "kpi_totals": kpi_totals,
        "latest_week": latest_week,
        "units": units,
        "business": business,
    }
