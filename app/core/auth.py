"""Auth helpers — Supabase JWT verification.

Supabase projects sign access tokens one of two ways:

- **Asymmetric (current default):** an ECC P-256 key (alg ``ES256``), with the
  public keys published at ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``.
  We fetch + cache that JWKS, pick the key by the token header's ``kid``, and
  verify the signature.
- **Legacy symmetric:** a shared HS256 secret (``JWT_SECRET``). Retained as a
  fallback so the code still works on older projects.

The signing scheme is chosen from the token header's ``alg``. In both cases we
verify the ``authenticated`` audience and expiry, then map claims onto
``AuthContext`` (``user_id`` from ``sub``; app role from ``app_metadata.role``).
"""
import threading
import time
from dataclasses import dataclass
from typing import Optional

import httpx
import jwt
from fastapi import Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from jwt import PyJWK

from app.core.config import settings

# How long a fetched JWKS is trusted before a refresh. Key rotation also
# triggers an out-of-band refetch when an unknown kid is seen.
_JWKS_TTL_SECONDS = 600

_jwks_lock = threading.Lock()
_jwks_cache: Optional[dict] = None
_jwks_fetched_at: float = 0.0


@dataclass
class AuthContext:
    """Decoded identity attached to a request."""

    user_id: str
    email: Optional[str] = None
    role: str = "learner"


def _jwks_url() -> str:
    base = settings.supabase_url.rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json"


def _fetch_jwks() -> dict:
    """Fetch the project JWKS and replace the cache."""
    global _jwks_cache, _jwks_fetched_at
    resp = httpx.get(_jwks_url(), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _jwks_cache = data
    _jwks_fetched_at = time.time()
    return data


def _get_jwks(force: bool = False) -> dict:
    """Return the cached JWKS, fetching when stale or forced."""
    with _jwks_lock:
        fresh = (
            _jwks_cache is not None
            and (time.time() - _jwks_fetched_at) < _JWKS_TTL_SECONDS
        )
        if fresh and not force:
            return _jwks_cache  # type: ignore[return-value]
        return _fetch_jwks()


def _signing_key_for_kid(kid: Optional[str]) -> PyJWK:
    """Resolve the JWK matching ``kid``, refetching once on an unknown kid."""
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token header is missing a key id.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _find(jwks: dict) -> Optional[dict]:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None

    try:
        match = _find(_get_jwks())
        if match is None:
            # Likely a freshly rotated key — refetch once before giving up.
            match = _find(_get_jwks(force=True))
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not fetch token signing keys.",
        )

    if match is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No signing key found for token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return PyJWK.from_dict(match)


def _decode_token(token: str) -> dict:
    """Verify + decode a Supabase access token, or raise 401.

    Runs synchronously (a JWKS fetch may block on the network), so call it via
    a threadpool from async code.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    alg = header.get("alg", "")
    common = {"audience": "authenticated"}

    try:
        if alg == "HS256":
            if not settings.jwt_secret:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="JWT_SECRET is not configured for HS256 tokens.",
                )
            return jwt.decode(
                token, settings.jwt_secret, algorithms=["HS256"], **common
            )

        # Asymmetric path (ES256 for Supabase ECC P-256; RS256 supported too).
        signing_key = _signing_key_for_kid(header.get("kid"))
        return jwt.decode(
            token, signing_key.key, algorithms=["ES256", "RS256"], **common
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

    Expects an ``Authorization: Bearer <access_token>`` header. The app-level
    role (learner/tutor/...) lives in the ``profiles`` table, not the token; the
    token only carries Supabase's ``authenticated`` Postgres role. We surface
    any app role stamped into ``app_metadata.role``, defaulting to ``learner``.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    claims = await run_in_threadpool(_decode_token, token)

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
