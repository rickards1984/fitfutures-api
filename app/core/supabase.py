"""Supabase service-role client.

Mirrors the Business Hero pattern: a single service-role client created
lazily so the app can boot without credentials during Phase 1. Routers in
later phases call `get_supabase()` to obtain the client.
"""
from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:  # pragma: no cover
    from supabase import Client


@lru_cache
def get_supabase() -> "Client":
    """Return a cached service-role Supabase client.

    Raises a clear error if credentials are missing so misconfiguration
    surfaces immediately rather than as an opaque network failure.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_KEY in the environment."
        )
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)
