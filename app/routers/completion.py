"""Completion flow router (Phase 7C — final MVP piece).

- GET  /v1/completion/roster                    tutor/admin: every learner's
                                                 completion state, for the picker
- GET  /v1/completion/placement/{id}            the placement's completion review
- POST /v1/completion/placement/{id}/submit     learner submits final reflection
- POST /v1/completion/placement/{id}/decide     tutor/admin records Pass / Refer

A Pass decision completes the placement (status → complete, actual_end_date
stamped), triggers the certificate flag, and emails managers that a Focus
Awards CPD certificate needs issuing. The email is best-effort — a mail
failure never rolls back the decision.
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    CompletionDecideRequest,
    CompletionReviewResponse,
    CompletionRosterItem,
    CompletionRosterResponse,
    CompletionSubmitRequest,
    DecisionInput,
)
from app.services import briefings
from app.services.placements import (
    assert_can_view_placement,
    assert_is_owner,
    current_week_number,
    fetch_placement,
    require_staff,
)

logger = logging.getLogger("fitfutures.completion")

router = APIRouter(prefix="/completion", tags=["completion"])

_ROUTE_LABELS = {
    "route_a": "Route A — PT Qualification Builder",
    "route_b": "Route B — Already PT Qualified Specialist",
}

# Placements that never surface in the completion picker.
_ROSTER_EXCLUDED_STATUSES = ("withdrawn",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _review_response(review: Optional[dict], placement: dict) -> CompletionReviewResponse:
    """Build the response from a review row (or defaults if none yet)."""
    data = review or {}
    return CompletionReviewResponse(
        placement_id=placement["id"],
        learner_final_reflection=data.get("learner_final_reflection"),
        tutor_decision=data.get("tutor_decision", "pending"),
        tutor_feedback=data.get("tutor_feedback"),
        tutor_id=data.get("tutor_id"),
        decided_at=data.get("decided_at"),
        certificate_triggered=bool(data.get("certificate_triggered")),
        certificate_triggered_at=data.get("certificate_triggered_at"),
        placement_status=placement["status"],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _fetch_review(supabase, placement_id: str) -> Optional[dict]:
    res = (
        supabase.table("completion_reviews")
        .select("*")
        .eq("placement_id", placement_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


@router.get("/roster", response_model=CompletionRosterResponse)
async def completion_roster(
    user: AuthContext = Depends(get_current_user),
) -> CompletionRosterResponse:
    """Every learner's completion state (tutor/admin only) for the picker."""
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    placements = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("*")
        .not_.in_("status", list(_ROSTER_EXCLUDED_STATUSES))
        .order("start_date", desc=True)
        .execute()
    )
    rows = placements.data or []
    if not rows:
        return CompletionRosterResponse(items=[])

    learner_ids = list({r["learner_id"] for r in rows})
    placement_ids = [r["id"] for r in rows]

    profiles = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("id, full_name")
        .in_("id", learner_ids)
        .execute()
    )
    names = {p["id"]: p.get("full_name") or "Unknown learner" for p in (profiles.data or [])}

    reviews = await run_in_threadpool(
        lambda: supabase.table("completion_reviews")
        .select("placement_id, tutor_decision, learner_final_reflection, certificate_triggered")
        .in_("placement_id", placement_ids)
        .execute()
    )
    review_by_placement = {r["placement_id"]: r for r in (reviews.data or [])}

    items = []
    for r in rows:
        review = review_by_placement.get(r["id"], {})
        items.append(
            CompletionRosterItem(
                placement_id=r["id"],
                learner_name=names.get(r["learner_id"], "Unknown learner"),
                facility_name=r.get("facility_name") or "—",
                placement_status=r["status"],
                current_week_number=current_week_number(r["start_date"]),
                planned_weeks=r.get("planned_weeks") or 0,
                decision=review.get("tutor_decision", "pending"),
                reflection_submitted=bool(review.get("learner_final_reflection")),
                certificate_triggered=bool(review.get("certificate_triggered")),
            )
        )
    return CompletionRosterResponse(items=items)


@router.get("/mine", response_model=CompletionReviewResponse)
async def my_completion(
    user: AuthContext = Depends(get_current_user),
) -> CompletionReviewResponse:
    """The caller's own completion review for their latest placement.

    Unlike /placements/mine this is not restricted to active placements — a
    learner must still see their Pass/Refer outcome after the placement has been
    marked complete.
    """
    supabase = get_supabase()
    res = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("*")
        .eq("learner_id", user.user_id)
        .order("start_date", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No placement found for this learner.",
        )
    placement = res.data[0]
    review = await run_in_threadpool(lambda: _fetch_review(supabase, placement["id"]))
    return _review_response(review, placement)


@router.get("/placement/{placement_id}", response_model=CompletionReviewResponse)
async def get_review(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> CompletionReviewResponse:
    """Return the completion review (owning learner or tutor/admin)."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))
    review = await run_in_threadpool(lambda: _fetch_review(supabase, placement_id))
    return _review_response(review, placement)


@router.post("/placement/{placement_id}/submit", response_model=CompletionReviewResponse)
async def submit_reflection(
    body: CompletionSubmitRequest,
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> CompletionReviewResponse:
    """Learner submits (or updates) their final reflection.

    Only the reflection is touched — a resubmission never clears a decision the
    tutor may already have recorded.
    """
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    assert_is_owner(placement, user)

    existing = await run_in_threadpool(lambda: _fetch_review(supabase, placement_id))
    if existing and existing.get("tutor_decision") == "pass":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This placement has already passed; the reflection is locked.",
        )

    row = {
        "placement_id": placement_id,
        "learner_final_reflection": body.final_reflection,
        "updated_at": _now(),
    }
    saved = await run_in_threadpool(
        lambda: supabase.table("completion_reviews")
        .upsert(row, on_conflict="placement_id")
        .execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save final reflection.",
        )
    return _review_response(saved.data[0], placement)


@router.post("/placement/{placement_id}/decide", response_model=CompletionReviewResponse)
async def decide(
    body: CompletionDecideRequest,
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> CompletionReviewResponse:
    """Tutor/admin records a Pass or Refer decision.

    Pass is terminal: it completes the placement, triggers the certificate, and
    emails managers. A placement already passed cannot be re-decided (avoids a
    duplicate certificate notification).
    """
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))

    existing = await run_in_threadpool(lambda: _fetch_review(supabase, placement_id))
    if existing and existing.get("tutor_decision") == "pass":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This placement has already passed and cannot be re-decided.",
        )

    is_pass = body.decision == DecisionInput.pass_
    now = _now()
    row = {
        "placement_id": placement_id,
        "tutor_decision": body.decision.value,
        "tutor_feedback": body.feedback,
        "tutor_id": user.user_id,
        "decided_at": now,
        "updated_at": now,
    }
    if is_pass:
        row["certificate_triggered"] = True
        row["certificate_triggered_at"] = now

    saved = await run_in_threadpool(
        lambda: supabase.table("completion_reviews")
        .upsert(row, on_conflict="placement_id")
        .execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record decision.",
        )
    review = saved.data[0]

    if is_pass:
        await run_in_threadpool(
            lambda: supabase.table("placements")
            .update({"status": "complete", "actual_end_date": date.today().isoformat()})
            .eq("id", placement_id)
            .execute()
        )
        placement["status"] = "complete"
        await _notify_certificate(supabase, placement, user)

    return _review_response(review, placement)


async def _notify_certificate(supabase, placement: dict, user: AuthContext) -> None:
    """Email managers that a certificate is needed; log the send. Best-effort:
    a mail/DB hiccup here must not fail the (already-persisted) decision."""
    try:
        learner_name = await run_in_threadpool(
            lambda: _profile_name(supabase, placement["learner_id"])
        )
        decided_by = await run_in_threadpool(
            lambda: _profile_name(supabase, user.user_id)
        )
        route_label = _ROUTE_LABELS.get(placement.get("route"), placement.get("route") or "—")
        result = await run_in_threadpool(
            lambda: briefings.send_certificate_ready(
                learner_name,
                placement.get("facility_name") or "—",
                route_label,
                decided_by,
            )
        )
        await run_in_threadpool(
            lambda: supabase.table("reminder_log")
            .insert(
                {
                    "placement_id": placement["id"],
                    "channel": briefings.EMAIL_CHANNEL,
                    "reminder_type": briefings.CERTIFICATE_READY,
                    "sent_at": _now(),
                    "status": result,
                    "detail": f"pass — certificate for {learner_name}",
                }
            )
            .execute()
        )
    except Exception:  # noqa: BLE001 — notification must not fail the decision
        logger.exception(
            "Certificate notification failed for placement %s", placement["id"]
        )


def _profile_name(supabase, profile_id: str) -> str:
    res = (
        supabase.table("profiles")
        .select("full_name")
        .eq("id", profile_id)
        .limit(1)
        .execute()
    )
    if res.data and res.data[0].get("full_name"):
        return res.data[0]["full_name"]
    return "Unknown"
