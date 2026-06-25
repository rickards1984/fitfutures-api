"""Auth helpers — Supabase JWT decode.

Protected routes depend on `get_current_user`, which verifies the Supabase
access token (HS256, signed with the project's JWT secret) and exposes the
caller's identity as an `AuthContext`. Supabase issues symmetric tokens with
`aud="authenticated"`; the user id is the `sub` claim.
"""
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings


@dataclass
class AuthContext:
    """Decoded identity attached to a request."""

    user_id: str
    email: Optional[str] = None
    role: str = "learner"


def _decode_token(token: str) -> dict:
    """Verify + decode a Supabase access token, or raise 401."""
    if not settings.jwt_secret:
        # Misconfiguration, not a client error — surface clearly.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured.",
        )
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> AuthContext:
    """Resolve the authenticated user from a Supabase JWT bearer token.

    Expects an `Authorization: Bearer <access_token>` header. The app-level
    role (learner/tutor/...) lives in the `profiles` table, not the token; the
    token only carries Supabase's `authenticated` Postgres role. We surface any
    app role stamped into `app_metadata.role`, defaulting to `learner`.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    claims = _decode_token(token)

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    app_metadata = claims.get("app_metadata") or {}
    role = app_metadata.get("role") or "learner"

    return AuthContext(user_id=user_id, email=claims.get("email"), role=role)
