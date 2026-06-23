"""Auth helpers — Supabase JWT decode.

Phase 1 scaffold: defines the dependency shape used by protected routes in
Phase 2 onward. The full verification (signature + claims) is wired when
auth lands; for now it exposes the structures so routers can import them.
"""
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, status


@dataclass
class AuthContext:
    """Decoded identity attached to a request."""

    user_id: str
    email: Optional[str] = None
    role: str = "learner"


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> AuthContext:
    """Resolve the authenticated user from a Supabase JWT.

    Phase 1: not yet wired — raises 501 so accidental use is obvious.
    Phase 2 implements signature verification against the Supabase JWT
    secret and maps claims onto AuthContext.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth is implemented in Phase 2.",
    )
