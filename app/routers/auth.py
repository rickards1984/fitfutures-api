"""Auth router — profile bootstrap.

Exposes `POST /v1/auth/profile`, called by the web app immediately after a
successful Supabase sign-in. It creates the learner's `profiles` row on first
login (idempotent: a returning user just gets their existing row back). The
identity (id + email) is taken from the verified JWT, not the request body.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import ProfileResponse, ProfileUpsertRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/profile", response_model=ProfileResponse)
async def upsert_profile(
    body: ProfileUpsertRequest,
    user: AuthContext = Depends(get_current_user),
) -> ProfileResponse:
    """Create the caller's profile on first login; return it on every call.

    On first login we insert using the JWT identity. Subsequent calls are a
    no-op write — we return the stored row so any later profile edits (role,
    opt-ins) are preserved rather than clobbered.
    """
    if not user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing an email claim; cannot create profile.",
        )

    supabase = get_supabase()

    existing = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("*")
        .eq("id", user.user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return ProfileResponse(**existing.data[0])

    payload = {
        "id": user.user_id,
        "email": user.email,
        "full_name": body.full_name,
        "phone": body.phone,
    }
    inserted = await run_in_threadpool(
        lambda: supabase.table("profiles").insert(payload).execute()
    )
    if not inserted.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create profile.",
        )
    return ProfileResponse(**inserted.data[0])
