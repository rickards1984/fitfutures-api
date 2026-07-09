"""Manager email briefings via Resend (Phase 7B-ii).

Two briefings, both sent from the daily internal cron run:

* Weekly cohort digest — one email listing every active placement (learner,
  facility, week of planned weeks, latest RAG, cumulative KPI attainment,
  units complete/total). Only fires on its scheduled weekday.
* Red-RAG alert — one email per placement/week whose overall_status is red,
  so a manager can intervene early.

Every send is deduped through `reminder_log` (channel 'email') so a daily cron
never double-sends: the digest keys on (type + today), the alert on
(placement + week). Resend failures are logged and swallowed — a bad send must
never crash the cron run.
"""
import logging
from datetime import date, datetime, time, timezone

import resend

from app.core.config import settings
from app.services.kpi_calc import METRICS, calc_rag
from app.services.placements import current_week_number

logger = logging.getLogger("fitfutures.briefings")

EMAIL_CHANNEL = "email"
WEEKLY_DIGEST = "weekly_digest"
RED_RAG_ALERT = "red_rag_alert"

# Red-RAG alerts only look at the current and immediately preceding programme
# week, so a first run never floods managers with alerts for historical reds.
RED_ALERT_WEEK_LOOKBACK = 1

RAG_COLORS = {
    "green": "#3FB950",
    "amber": "#D29922",
    "red": "#F85149",
    "no_entry": "#8B949E",
}
RAG_LABELS = {
    "green": "On track",
    "amber": "At risk",
    "red": "Behind",
    "no_entry": "No entry",
}

_RAG_METRICS = [m for m in METRICS if m.counts_for_rag]


# --- Resend transport -----------------------------------------------------


def send_email(subject: str, html: str) -> str:
    """Send one briefing email. Returns 'sent', 'failed', or 'skipped'.

    Never raises: a Resend/network failure is logged and swallowed so the cron
    run continues.
    """
    if not settings.resend_api_key or not settings.briefing_from_email:
        logger.warning("Resend not configured (missing key or from address); skipping.")
        return "skipped"
    if not settings.briefing_to_emails:
        logger.warning("No BRIEFING_TO_EMAILS recipients configured; skipping.")
        return "skipped"

    try:
        resend.api_key = settings.resend_api_key
        resend.Emails.send(
            {
                "from": settings.briefing_from_email,
                "to": settings.briefing_to_emails,
                "subject": subject,
                "html": html,
            }
        )
        return "sent"
    except Exception:  # noqa: BLE001 — email is best-effort; never crash the cron
        logger.exception("Resend send failed for briefing: %s", subject)
        return "failed"


# --- Shared data helpers --------------------------------------------------


def _sum_actuals(rows: list[dict], col: str) -> float:
    return sum(float(r.get(col) or 0) for r in rows)


def _cumulative_attainment_pct(entries: list[dict], placement: dict) -> int:
    """Overall cumulative actuals vs total targets across RAG-counting metrics."""
    total_actual = 0.0
    total_target = 0.0
    for m in _RAG_METRICS:
        target = float(placement.get(m.total_target_col) or 0)
        if target <= 0:
            continue
        total_actual += _sum_actuals(entries, m.actual_col)
        total_target += target
    if total_target <= 0:
        return 0
    return round(100 * total_actual / total_target)


def _placement_summary(supabase, placement: dict, total_units: int) -> dict:
    """Gather the digest row for one active placement."""
    placement_id = placement["id"]
    learner = _fetch_profile_name(supabase, placement["learner_id"])
    week = current_week_number(placement["start_date"])

    entries = (
        supabase.table("kpi_entries")
        .select("*")
        .eq("placement_id", placement_id)
        .order("week_number")
        .execute()
    ).data or []

    latest_rag = entries[-1]["overall_status"] if entries else "no_entry"

    units_complete = (
        supabase.table("learner_unit_progress")
        .select("unit_id")
        .eq("placement_id", placement_id)
        .eq("status", "complete")
        .execute()
    ).data or []

    return {
        "learner": learner,
        "facility": placement.get("facility_name") or "—",
        "week": week,
        "planned_weeks": placement.get("planned_weeks") or 0,
        "latest_rag": latest_rag,
        "attainment_pct": _cumulative_attainment_pct(entries, placement),
        "units_complete": len(units_complete),
        "units_total": total_units,
    }


def _fetch_profile_name(supabase, profile_id: str) -> str:
    res = (
        supabase.table("profiles")
        .select("full_name")
        .eq("id", profile_id)
        .limit(1)
        .execute()
    )
    if res.data and res.data[0].get("full_name"):
        return res.data[0]["full_name"]
    return "Unknown learner"


def _today_start_iso() -> str:
    """UTC midnight today — dedupe boundary for the once-a-day digest."""
    return datetime.combine(date.today(), time.min, tzinfo=timezone.utc).isoformat()


def _log_reminder(
    supabase,
    *,
    reminder_type: str,
    status: str,
    detail: str,
    placement_id=None,
    week_number=None,
) -> None:
    supabase.table("reminder_log").insert(
        {
            "placement_id": placement_id,
            "channel": EMAIL_CHANNEL,
            "reminder_type": reminder_type,
            "week_number": week_number,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "detail": detail,
        }
    ).execute()


# --- Weekly cohort digest -------------------------------------------------


def run_weekly_digest(supabase, *, force: bool = False) -> dict:
    """Send the cohort digest once on its scheduled weekday.

    Blocking (DB + network). Call via run_in_threadpool. `force` bypasses the
    weekday gate (used for manual testing) but not the once-a-day dedupe.
    """
    if not force and date.today().weekday() != settings.briefing_digest_weekday:
        return {"digest": "not_scheduled_today"}

    # Dedupe: already sent a digest since midnight today?
    already = (
        supabase.table("reminder_log")
        .select("id")
        .eq("channel", EMAIL_CHANNEL)
        .eq("reminder_type", WEEKLY_DIGEST)
        .gte("sent_at", _today_start_iso())
        .limit(1)
        .execute()
    )
    if already.data:
        return {"digest": "already_sent_today"}

    placements = (
        supabase.table("placements").select("*").eq("status", "active").execute()
    ).data or []

    total_units = (
        supabase.table("units").select("id", count="exact").execute()
    ).count or 0

    summaries = [_placement_summary(supabase, p, total_units) for p in placements]

    subject = f"FitFutures weekly cohort digest — {date.today():%d %b %Y}"
    html = _digest_html(summaries)
    result = send_email(subject, html)

    _log_reminder(
        supabase,
        reminder_type=WEEKLY_DIGEST,
        status=result,
        detail=f"{len(summaries)} active placement(s)",
    )
    return {"digest": result, "placements": len(summaries)}


# --- Red-RAG alerts -------------------------------------------------------


def run_red_rag_alerts(supabase) -> dict:
    """Alert managers about recent red KPI weeks not yet alerted.

    Blocking (DB + network). Call via run_in_threadpool.
    """
    placements = (
        supabase.table("placements").select("*").eq("status", "active").execute()
    ).data or []

    sent = skipped = failed = 0

    for placement in placements:
        placement_id = placement["id"]
        current_week = current_week_number(placement["start_date"])
        min_week = max(1, current_week - RED_ALERT_WEEK_LOOKBACK)

        red_entries = (
            supabase.table("kpi_entries")
            .select("*")
            .eq("placement_id", placement_id)
            .eq("overall_status", "red")
            .gte("week_number", min_week)
            .order("week_number")
            .execute()
        ).data or []

        for entry in red_entries:
            week = entry["week_number"]

            already = (
                supabase.table("reminder_log")
                .select("id")
                .eq("placement_id", placement_id)
                .eq("reminder_type", RED_RAG_ALERT)
                .eq("week_number", week)
                .limit(1)
                .execute()
            )
            if already.data:
                skipped += 1
                continue

            learner = _fetch_profile_name(supabase, placement["learner_id"])
            behind = _behind_metrics(entry, placement)

            subject = f"🔴 Red flag — {learner}, week {week}"
            html = _red_rag_html(learner, placement, entry, behind)
            result = send_email(subject, html)

            _log_reminder(
                supabase,
                reminder_type=RED_RAG_ALERT,
                status=result,
                detail=f"red week {week}",
                placement_id=placement_id,
                week_number=week,
            )
            if result == "sent":
                sent += 1
            else:
                failed += 1

    return {"red_alerts_sent": sent, "red_alerts_skipped": skipped, "red_alerts_failed": failed}


def _behind_metrics(entry: dict, placement: dict) -> list[dict]:
    """RAG-counting metrics that are amber/red vs the weekly target this week."""
    behind = []
    for m in _RAG_METRICS:
        actual = float(entry.get(m.actual_col) or 0)
        target = float(placement.get(m.wk_target_col) or 0)
        rag = calc_rag(actual, target)
        if rag in ("amber", "red"):
            behind.append(
                {"label": m.label, "actual": actual, "target": target, "rag": rag}
            )
    return behind


# --- HTML rendering -------------------------------------------------------

_BG = "#0D1117"
_SURFACE = "#161B22"
_BORDER = "#30363D"
_TEXT = "#E6EDF3"
_MUTED = "#8B949E"
_ACCENT = "#00E5FF"

_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def _rag_pill(rag: str) -> str:
    color = RAG_COLORS.get(rag, RAG_COLORS["no_entry"])
    label = RAG_LABELS.get(rag, rag)
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f'font-size:12px;font-weight:500;color:{_BG};background:{color};">{label}</span>'
    )


def _shell(title: str, intro: str, body: str) -> str:
    """Wrap content in a dark, email-client-safe container."""
    return (
        f'<div style="background:{_BG};padding:24px 0;font-family:{_FONT};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="max-width:640px;margin:0 auto;background:{_SURFACE};border:1px solid '
        f'{_BORDER};border-radius:12px;overflow:hidden;">'
        f'<tr><td style="padding:24px 28px;border-bottom:1px solid {_BORDER};">'
        f'<div style="font-size:13px;letter-spacing:1px;text-transform:uppercase;'
        f'color:{_ACCENT};font-weight:500;">FitFutures</div>'
        f'<div style="font-size:20px;font-weight:500;color:{_TEXT};margin-top:6px;">{title}</div>'
        f'<div style="font-size:14px;color:{_MUTED};margin-top:6px;">{intro}</div>'
        f'</td></tr>'
        f'<tr><td style="padding:20px 28px;">{body}</td></tr>'
        f'<tr><td style="padding:16px 28px;border-top:1px solid {_BORDER};'
        f'font-size:12px;color:{_MUTED};">Automated briefing from the FitFutures placement '
        f'programme. Do not reply.</td></tr>'
        f'</table></div>'
    )


def _digest_html(summaries: list[dict]) -> str:
    if not summaries:
        return _shell(
            "Weekly cohort digest",
            f"{date.today():%A %d %B %Y}",
            f'<p style="color:{_MUTED};font-size:14px;margin:0;">No active placements '
            f"this week.</p>",
        )

    th = (
        f'style="text-align:left;padding:10px 12px;font-size:12px;font-weight:500;'
        f'color:{_MUTED};text-transform:uppercase;letter-spacing:.5px;'
        f'border-bottom:1px solid {_BORDER};"'
    )
    rows = ""
    for s in summaries:
        td = (
            f'style="padding:12px;font-size:14px;color:{_TEXT};'
            f'border-bottom:1px solid {_BORDER};"'
        )
        rows += (
            f"<tr>"
            f'<td {td}><strong style="font-weight:500;">{_esc(s["learner"])}</strong></td>'
            f'<td {td}>{_esc(s["facility"])}</td>'
            f'<td {td}>{s["week"]} / {s["planned_weeks"]}</td>'
            f"<td {td}>{_rag_pill(s['latest_rag'])}</td>"
            f'<td {td}>{s["attainment_pct"]}%</td>'
            f'<td {td}>{s["units_complete"]} / {s["units_total"]}</td>'
            f"</tr>"
        )

    table = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;">'
        f"<tr>"
        f"<th {th}>Learner</th><th {th}>Facility</th><th {th}>Week</th>"
        f"<th {th}>Latest RAG</th><th {th}>KPI&nbsp;%</th><th {th}>Units</th>"
        f"</tr>{rows}</table>"
    )
    return _shell(
        "Weekly cohort digest",
        f"{len(summaries)} active placement(s) · {date.today():%A %d %B %Y}",
        table,
    )


def _red_rag_html(
    learner: str, placement: dict, entry: dict, behind: list[dict]
) -> str:
    week = entry["week_number"]
    rows = ""
    for b in behind:
        td = (
            f'style="padding:8px 12px;font-size:14px;color:{_TEXT};'
            f'border-bottom:1px solid {_BORDER};"'
        )
        actual = _num(b["actual"])
        target = _num(b["target"])
        rows += (
            f"<tr><td {td}>{_esc(b['label'])}</td>"
            f'<td {td}>{actual} / {target}</td>'
            f"<td {td}>{_rag_pill(b['rag'])}</td></tr>"
        )
    metrics_table = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;margin-top:4px;">'
        f"<tr><td style=\"padding:8px 12px;font-size:12px;color:{_MUTED};"
        f'text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid {_BORDER};">Metric</td>'
        f'<td style="padding:8px 12px;font-size:12px;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:.5px;border-bottom:1px solid {_BORDER};">This week</td>'
        f'<td style="padding:8px 12px;font-size:12px;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:.5px;border-bottom:1px solid {_BORDER};">Status</td></tr>'
        f"{rows}</table>"
        if behind
        else f'<p style="color:{_MUTED};font-size:14px;">No metric breakdown available.</p>'
    )

    reflection = entry.get("reflection")
    key_issue = entry.get("key_issue")
    notes = ""
    if key_issue:
        notes += _note_block("Key issue flagged", key_issue)
    if reflection:
        notes += _note_block("Learner reflection", reflection)
    if not notes:
        notes = (
            f'<p style="color:{_MUTED};font-size:14px;margin-top:16px;">'
            f"The learner did not add a reflection or key issue this week.</p>"
        )

    intro = (
        f'{_esc(learner)} logged a red week at '
        f'{_esc(placement.get("facility_name") or "their placement")}. '
        f"Early intervention recommended."
    )
    body = (
        f'<div style="font-size:14px;color:{_TEXT};margin-bottom:14px;">'
        f'<strong style="font-weight:500;">Week {week}</strong> · '
        f'{len(behind)} metric(s) behind target</div>'
        f"{metrics_table}{notes}"
    )
    return _shell(f"Red-RAG alert · Week {week}", intro, body)


def _note_block(label: str, text: str) -> str:
    return (
        f'<div style="margin-top:16px;padding:12px 14px;background:{_BG};'
        f'border:1px solid {_BORDER};border-radius:8px;">'
        f'<div style="font-size:12px;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:.5px;margin-bottom:6px;">{label}</div>'
        f'<div style="font-size:14px;color:{_TEXT};white-space:pre-wrap;">{_esc(text)}</div>'
        f"</div>"
    )


def _num(v: float) -> str:
    """Render a metric value without a trailing .0 for whole numbers."""
    return str(int(v)) if float(v).is_integer() else str(v)


def _esc(text) -> str:
    """Minimal HTML escaping for user-supplied strings."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
