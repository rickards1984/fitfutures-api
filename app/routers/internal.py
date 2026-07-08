"""Internal (cron-triggered) endpoints.

Not under /v1 and not user-authenticated — guarded instead by a shared secret
(`INTERNAL_CRON_SECRET`) sent in the `X-Internal-Secret` header. A daily
scheduler (Railway cron) hits `/internal/reminders/run`.
"""
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.supabase import get_supabase
from app.models.schemas import ReminderRunResponse
from app.services.reminders import run_weekly_checkins

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
) -> ReminderRunResponse:
    """Send weekly-checkin web-push nudges to learners behind on KPIs."""
    _require_cron_secret(x_internal_secret)
    supabase = get_supabase()
    summary = await run_in_threadpool(run_weekly_checkins, supabase)
    return ReminderRunResponse(**summary)
