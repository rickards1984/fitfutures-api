"""Placement helpers shared across routers.

Centralises placement fetch + access checks and the derived week-number
calculation so the placements and KPI routers stay consistent. The API uses
the service-role client (bypasses RLS), so authorization is enforced here.
"""
import math
from datetime import date
from typing import Optional, Union

from fastapi import HTTPException, status

from app.core.auth import AuthContext


def current_week_number(
    start_date: Union[date, str], today: Optional[date] = None
) -> int:
    """1-based programme week: max(1, ceil((today - start) / 7 days)).

    Accepts an ISO date string (as the DB returns it) or a date. Mirrors the
    frontend weekCalc so the API and UI never disagree.
    """
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    today = today or date.today()
    days = (today - start_date).days
    if days <= 0:
        return 1
    return max(1, math.ceil(days / 7))


def fetch_placement(supabase, placement_id: str) -> dict:
    """Return the placement row or raise 404."""
    res = (
        supabase.table("placements")
        .select("*")
        .eq("id", placement_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Placement not found."
        )
    return res.data[0]


def fetch_role(supabase, user_id: str) -> str:
    """Resolve the caller's app role from `profiles` (the canonical source).

    The JWT only carries Supabase's `authenticated` Postgres role; the
    learner/tutor/admin role lives in the profiles table, matching the RLS
    helpers and the "set your own profile to role = admin" setup step.
    """
    res = (
        supabase.table("profiles")
        .select("role")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return "learner"
    return res.data[0].get("role") or "learner"


def require_staff(supabase, user: AuthContext) -> None:
    """Raise 403 unless the caller is a tutor or admin."""
    if fetch_role(supabase, user.user_id) not in ("tutor", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires a tutor or admin role.",
        )


def assert_can_view_placement(supabase, placement: dict, user: AuthContext) -> None:
    """Allow the owning learner, the assigned supervisor, or any tutor/admin."""
    if placement.get("learner_id") == user.user_id:
        return
    if placement.get("supervisor_id") == user.user_id:
        return
    if fetch_role(supabase, user.user_id) in ("tutor", "admin"):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this placement.",
    )
