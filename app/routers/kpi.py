"""KPI router.

Phase 3 ships the cumulative totals endpoint only:
- GET /v1/kpi/placement/{id}/totals

Weekly entry endpoints + AI coach auto-message land in Phase 4.
"""
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import KpiTotalLine, KpiTotalsResponse
from app.services.placements import assert_can_view_placement, fetch_placement

router = APIRouter(prefix="/kpi", tags=["kpi"])

# (metric key, label, kpi_entries actual column, placements total-target column)
_METRICS: list[tuple[str, str, str, str]] = [
    ("placement_hours", "Placement hours", "actual_placement_hours", "total_target_placement_hours"),
    ("study_hours", "Study hours", "actual_study_hours", "total_target_study_hours"),
    ("member_conversations", "Member conversations", "actual_member_conversations", "total_target_member_conversations"),
    ("ex_member_contacts", "Ex-member contacts", "actual_ex_member_contacts", "total_target_ex_member_contacts"),
    ("retention_saves", "Retention saves", "actual_retention_saves", "total_target_retention_saves"),
    ("campaign_touches", "Campaign touches", "actual_campaign_touches", "total_target_campaign_touches"),
    ("tasters_booked", "Tasters booked", "actual_tasters_booked", "total_target_tasters_booked"),
    ("consultations", "Consultations", "actual_consultations", "total_target_consultations"),
    ("conversions", "Conversions", "actual_conversions", "total_target_conversions"),
]


@router.get("/placement/{placement_id}/totals", response_model=KpiTotalsResponse)
async def placement_totals(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> KpiTotalsResponse:
    """Cumulative actuals-to-date vs total targets. Zeroes before any entry."""
    supabase = get_supabase()

    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    actual_cols = [m[2] for m in _METRICS]
    entries = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select(",".join(actual_cols))
        .eq("placement_id", placement_id)
        .execute()
    )
    rows = entries.data or []

    lines = []
    for key, label, actual_col, target_col in _METRICS:
        actual = sum(float(r.get(actual_col) or 0) for r in rows)
        target = float(placement.get(target_col) or 0)
        lines.append(KpiTotalLine(key=key, label=label, actual=actual, target=target))

    return KpiTotalsResponse(
        placement_id=placement_id,
        weeks_logged=len(rows),
        lines=lines,
    )
