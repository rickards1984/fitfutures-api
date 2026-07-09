"""Internal (cron-triggered) endpoints.

Not under /v1 and not user-authenticated — guarded instead by a shared secret
(`INTERNAL_CRON_SECRET`) sent in the `X-Internal-Secret` header. A daily
scheduler (Railway cron) hits `/internal/reminders/run`.
"""
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.supabase import get_supabase
from app.models.schemas import ReminderRunResponse
from app.services.briefings import run_red_rag_alerts, run_weekly_digest
from app.services.reminders import run_weekly_checkins

logger = logging.getLogger("fitfutures.internal")

router = APIRouter(prefix="/internal", tags=["internal"])


def _require_cron_secret(x_internal_secret: Optional[str]) -> None:
    """Constant-time check of the shared cron secret, or 403."""
    expected = settings.internal_cron_secret
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTERNAL_CRON_SECRET is not configured.",
        )
    if not x_internal_secret or not secrets.compare_digest(
        x_internal_secret, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal secret.",
        )


@router.post("/reminders/run", response_model=ReminderRunResponse)
async def run_reminders(
    x_internal_secret: Optional[str] = Header(default=None),
    force_digest: bool = Query(
        default=False,
        description="Send the cohort digest now, ignoring its scheduled weekday "
        "(still deduped once/day). For manual testing.",
    ),
) -> ReminderRunResponse:
    """Daily cron pass: push nudges + weekly cohort digest + red-RAG alerts.

    Each job is independent — a failure in one is logged and the others still
    run, so a single bad channel never aborts the whole cron pass.
    """
    _require_cron_secret(x_internal_secret)
    supabase = get_supabase()

    # 1. Web-push weekly-checkin nudges.
    try:
        push_summary = await run_in_threadpool(run_weekly_checkins, supabase)
    except Exception:  # noqa: BLE001 — one channel must not abort the run
        logger.exception("Web-push nudges failed during cron run")
        push_summary = {"active_placements": 0, "nudged": 0, "skipped": 0, "failed": 0}

    # 2. Weekly cohort digest (only on its scheduled weekday, unless forced).
    try:
        digest_summary = await run_in_threadpool(
            lambda: run_weekly_digest(supabase, force=force_digest)
        )
    except Exception:  # noqa: BLE001
        logger.exception("Weekly digest failed during cron run")
        digest_summary = {"digest": "error"}

    # 3. Red-RAG alert emails.
    try:
        red_summary = await run_in_threadpool(run_red_rag_alerts, supabase)
    except Exception:  # noqa: BLE001
        logger.exception("Red-RAG alerts failed during cron run")
        red_summary = {}

    return ReminderRunResponse(
        **push_summary,
        digest=digest_summary.get("digest", "not_run"),
        digest_placements=digest_summary.get("placements"),
        red_alerts_sent=red_summary.get("red_alerts_sent", 0),
        red_alerts_skipped=red_summary.get("red_alerts_skipped", 0),
        red_alerts_failed=red_summary.get("red_alerts_failed", 0),
    )
