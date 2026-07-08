"""Reminders service — web push only (Phase 7B-i).

The weekly-checkin job nudges learners on an active placement who have not yet
logged the current week's KPIs. Every send is written to `reminder_log` so a
learner is never nudged with the same reminder type twice in one week
(WhatsApp + email land in later steps).
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone

from pywebpush import WebPushException, webpush

from app.core.config import settings
from app.services.placements import current_week_number

logger = logging.getLogger("fitfutures.reminders")

WEEKLY_CHECKIN = "weekly_checkin"
PUSH_CHANNEL = "push"

_NUDGE_PAYLOAD = {
    "title": "FitFutures",
    "body": "You haven't logged this week's KPIs yet — take 2 minutes to update your numbers.",
    "url": "/kpi",
}


def _week_commencing(start_date: str, week_number: int) -> date:
    return date.fromisoformat(start_date) + timedelta(weeks=week_number - 1)


def send_web_push(subscription: dict, payload: dict) -> str:
    """Send one push. Returns 'sent', 'gone' (expired), or 'failed'."""
    try:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {
                    "p256dh": subscription["p256dh"],
                    "auth": subscription["auth"],
                },
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        return "sent"
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in (404, 410):
            return "gone"  # subscription no longer valid — prune it
        logger.warning("Web push failed (%s): %s", status_code, exc)
        return "failed"


def run_weekly_checkins(supabase) -> dict:
    """Nudge learners with no KPI entry for their current week.

    Blocking (DB + network). Call via run_in_threadpool.
    """
    if not settings.vapid_private_key or not settings.vapid_subject:
        raise RuntimeError("VAPID keys are not configured; cannot send web push.")

    placements = (
        supabase.table("placements").select("*").eq("status", "active").execute()
    )
    rows = placements.data or []
    nudged = skipped = failed = 0

    for placement in rows:
        placement_id = placement["id"]
        week = current_week_number(placement["start_date"])
        wc = _week_commencing(placement["start_date"], week)

        # Already logged this week? No nudge needed.
        entry = (
            supabase.table("kpi_entries")
            .select("id")
            .eq("placement_id", placement_id)
            .eq("week_number", week)
            .limit(1)
            .execute()
        )
        if entry.data:
            skipped += 1
            continue

        # Dedupe: already nudged (this type + channel) this week?
        already = (
            supabase.table("reminder_log")
            .select("id")
            .eq("placement_id", placement_id)
            .eq("reminder_type", WEEKLY_CHECKIN)
            .eq("channel", PUSH_CHANNEL)
            .gte("sent_at", wc.isoformat())
            .limit(1)
            .execute()
        )
        if already.data:
            skipped += 1
            continue

        # Respect the learner's opt-in.
        profile = (
            supabase.table("profiles")
            .select("push_opt_in")
            .eq("id", placement["learner_id"])
            .limit(1)
            .execute()
        )
        if not (profile.data and profile.data[0].get("push_opt_in")):
            skipped += 1
            continue

        subs = (
            supabase.table("push_subscriptions")
            .select("*")
            .eq("profile_id", placement["learner_id"])
            .execute()
        )
        if not subs.data:
            skipped += 1
            continue

        sent_any = False
        for sub in subs.data:
            result = send_web_push(sub, _NUDGE_PAYLOAD)
            if result == "sent":
                sent_any = True
            elif result == "gone":
                supabase.table("push_subscriptions").delete().eq(
                    "id", sub["id"]
                ).execute()

        supabase.table("reminder_log").insert(
            {
                "placement_id": placement_id,
                "channel": PUSH_CHANNEL,
                "reminder_type": WEEKLY_CHECKIN,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "sent" if sent_any else "failed",
                "detail": f"week {week} check-in nudge",
            }
        ).execute()

        if sent_any:
            nudged += 1
        else:
            failed += 1

    return {
        "active_placements": len(rows),
        "nudged": nudged,
        "skipped": skipped,
        "failed": failed,
    }
