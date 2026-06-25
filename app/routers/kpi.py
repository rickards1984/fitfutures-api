"""KPI router.

- GET  /v1/kpi/placement/{id}/weeks       all submitted weeks
- GET  /v1/kpi/placement/{id}/week/{n}     one week (or 404)
- POST /v1/kpi/placement/{id}/week/{n}     submit a week → AI coach auto-message
- GET  /v1/kpi/placement/{id}/totals       cumulative actuals vs total targets
"""
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    KpiEntryResponse,
    KpiTotalLine,
    KpiTotalsResponse,
    KpiWeekSubmitRequest,
)
from app.services import ai_coach
from app.services.kpi_calc import METRICS, week_overall_rag
from app.services.placements import (
    assert_can_view_placement,
    assert_is_owner,
    fetch_placement,
)

logger = logging.getLogger("fitfutures.kpi")

router = APIRouter(prefix="/kpi", tags=["kpi"])


def _sum_actuals(rows: list[dict]) -> dict:
    """Cumulative actuals across submitted weeks, keyed by actual column."""
    return {
        m.actual_col: sum(float(r.get(m.actual_col) or 0) for r in rows)
        for m in METRICS
    }


def _week_commencing(placement: dict, week_number: int) -> date:
    start = date.fromisoformat(placement["start_date"])
    return start + timedelta(weeks=week_number - 1)


@router.get("/placement/{placement_id}/weeks", response_model=list[KpiEntryResponse])
async def list_weeks(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> list[KpiEntryResponse]:
    """All submitted weeks for a placement, ordered by week number."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    res = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select("*")
        .eq("placement_id", placement_id)
        .order("week_number")
        .execute()
    )
    return [KpiEntryResponse(**row) for row in (res.data or [])]


@router.get("/placement/{placement_id}/week/{week_number}", response_model=KpiEntryResponse)
async def get_week(
    placement_id: str,
    week_number: int = Path(ge=1, le=52),
    user: AuthContext = Depends(get_current_user),
) -> KpiEntryResponse:
    """One submitted week, or 404 if not entered yet."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    res = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select("*")
        .eq("placement_id", placement_id)
        .eq("week_number", week_number)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No entry for this week yet.",
        )
    return KpiEntryResponse(**res.data[0])


@router.post("/placement/{placement_id}/week/{week_number}", response_model=KpiEntryResponse)
async def submit_week(
    body: KpiWeekSubmitRequest,
    placement_id: str,
    week_number: int = Path(ge=1, le=52),
    user: AuthContext = Depends(get_current_user),
) -> KpiEntryResponse:
    """Submit (or resubmit) a week's actuals.

    Computes + stores the overall RAG, then generates the AI coach auto-message
    from this week's actuals vs targets plus cumulative pace, stores it on the
    entry, and returns the entry inline.
    """
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    assert_is_owner(placement, user)

    week_commencing = body.week_commencing or _week_commencing(placement, week_number)

    entry = {
        "placement_id": placement_id,
        "week_number": week_number,
        "week_commencing": week_commencing.isoformat(),
        "actual_placement_hours": body.actual_placement_hours,
        "actual_study_hours": body.actual_study_hours,
        "actual_member_conversations": body.actual_member_conversations,
        "actual_ex_member_contacts": body.actual_ex_member_contacts,
        "actual_retention_saves": body.actual_retention_saves,
        "actual_campaign_touches": body.actual_campaign_touches,
        "actual_tasters_booked": body.actual_tasters_booked,
        "actual_consultations": body.actual_consultations,
        "actual_conversions": body.actual_conversions,
        "reflection": body.reflection,
        "key_issue": body.key_issue,
    }
    entry["overall_status"] = week_overall_rag(entry, placement)

    # Upsert on (placement_id, week_number) so a resubmission overwrites.
    saved = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .upsert(entry, on_conflict="placement_id,week_number")
        .execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save KPI entry.",
        )
    row = saved.data[0]

    # Generate + persist the coach auto-message. A provider failure must not
    # fail the submission — the entry is already saved.
    coach_message = await _generate_coach_message(
        supabase, placement, week_number, entry
    )
    if coach_message:
        generated_at = datetime.now(timezone.utc).isoformat()
        updated = await run_in_threadpool(
            lambda: supabase.table("kpi_entries")
            .update(
                {"ai_coach_message": coach_message, "ai_coach_generated_at": generated_at}
            )
            .eq("id", row["id"])
            .execute()
        )
        if updated.data:
            row = updated.data[0]

    return KpiEntryResponse(**row)


async def _generate_coach_message(
    supabase, placement: dict, week_number: int, entry: dict
):
    """Build context and call the coach; return the text or None on failure."""
    try:
        all_rows = await run_in_threadpool(
            lambda: supabase.table("kpi_entries")
            .select("*")
            .eq("placement_id", placement["id"])
            .execute()
        )
        rows = all_rows.data or []
        cumulative = _sum_actuals(rows)

        week_lines = [
            {
                "label": m.label,
                "actual": float(entry.get(m.actual_col) or 0),
                "target": float(placement.get(m.wk_target_col) or 0),
            }
            for m in METRICS
        ]
        total_lines = [
            {
                "label": m.label,
                "actual": cumulative.get(m.actual_col, 0),
                "target": float(placement.get(m.total_target_col) or 0),
            }
            for m in METRICS
        ]
        hours_done = cumulative.get("actual_placement_hours", 0)
        hours_remaining = round(
            float(placement.get("total_target_placement_hours") or 0) - hours_done, 1
        )

        context = {
            "route": placement.get("route"),
            "week_number": week_number,
            "planned_weeks": placement.get("planned_weeks"),
            "week_lines": week_lines,
            "total_lines": total_lines,
            "hours_remaining": hours_remaining,
            "reflection": entry.get("reflection"),
            "key_issue": entry.get("key_issue"),
        }
        messages = ai_coach.build_auto_message_messages(context)
        return await run_in_threadpool(
            ai_coach.generate_coach_response, messages, context
        )
    except Exception:  # noqa: BLE001 — coach is best-effort
        logger.exception("AI coach auto-message failed for placement %s", placement["id"])
        return None


@router.get("/placement/{placement_id}/totals", response_model=KpiTotalsResponse)
async def placement_totals(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> KpiTotalsResponse:
    """Cumulative actuals-to-date vs total targets. Zeroes before any entry."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    actual_cols = [m.actual_col for m in METRICS]
    entries = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select(",".join(actual_cols))
        .eq("placement_id", placement_id)
        .execute()
    )
    rows = entries.data or []
    cumulative = _sum_actuals(rows)

    lines = [
        KpiTotalLine(
            key=m.key,
            label=m.label,
            actual=cumulative.get(m.actual_col, 0),
            target=float(placement.get(m.total_target_col) or 0),
        )
        for m in METRICS
    ]
    return KpiTotalsResponse(
        placement_id=placement_id, weeks_logged=len(rows), lines=lines
    )
