"""Web push subscription router.

- POST /v1/push/subscribe     store a subscription + opt the learner in
- POST /v1/push/unsubscribe   remove a subscription + opt out
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    PushSubscribeRequest,
    PushUnsubscribeRequest,
    SimpleStatusResponse,
)

router = APIRouter(prefix="/push", tags=["push"])


@router.post("/subscribe", response_model=SimpleStatusResponse)
async def subscribe(
    body: PushSubscribeRequest,
    user: AuthContext = Depends(get_current_user),
) -> SimpleStatusResponse:
    """Store the caller's web-push subscription and set push_opt_in."""
    supabase = get_supabase()
    row = {
        "profile_id": user.user_id,
        "endpoint": body.endpoint,
        "p256dh": body.keys.p256dh,
        "auth": body.keys.auth,
    }
    saved = await run_in_threadpool(
        lambda: supabase.table("push_subscriptions")
        .upsert(row, on_conflict="profile_id,endpoint")
        .execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store subscription.",
        )
    await run_in_threadpool(
        lambda: supabase.table("profiles")
        .update({"push_opt_in": True})
        .eq("id", user.user_id)
        .execute()
    )
    return SimpleStatusResponse(ok=True, detail="Subscribed.")


@router.post("/unsubscribe", response_model=SimpleStatusResponse)
async def unsubscribe(
    body: PushUnsubscribeRequest,
    user: AuthContext = Depends(get_current_user),
) -> SimpleStatusResponse:
    """Remove the given subscription and opt the learner out of push."""
    supabase = get_supabase()
    await run_in_threadpool(
        lambda: supabase.table("push_subscriptions")
        .delete()
        .eq("profile_id", user.user_id)
        .eq("endpoint", body.endpoint)
        .execute()
    )
    await run_in_threadpool(
        lambda: supabase.table("profiles")
        .update({"push_opt_in": False})
        .eq("id", user.user_id)
        .execute()
    )
    return SimpleStatusResponse(ok=True, detail="Unsubscribed.")
