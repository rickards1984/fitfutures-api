"""Supabase Storage helpers for the private `evidence` bucket.

The bucket is created manually during setup (Phase 1 checklist). The API holds
the service-role key, so it mints short-lived signed URLs: a signed *upload*
URL the browser PUTs the file to, and signed *download* URLs for displaying
private files in the gallery.
"""
import re
import uuid

EVIDENCE_BUCKET = "evidence"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def build_object_path(placement_id: str, filename: str) -> str:
    """Unique, namespaced object path: `{placement_id}/{uuid}_{safe_name}`."""
    safe = _SAFE_NAME.sub("_", filename).strip("_") or "file"
    return f"{placement_id}/{uuid.uuid4().hex}_{safe}"


def create_upload_url(supabase, path: str) -> dict:
    """Signed upload URL (token) the browser uploads the object to."""
    res = supabase.storage.from_(EVIDENCE_BUCKET).create_signed_upload_url(path)
    return {
        "path": res.get("path", path),
        "token": res["token"],
        "signed_url": res.get("signed_url") or res.get("signedUrl"),
    }


def create_download_url(supabase, path: str, expires_in: int = 3600):
    """Short-lived signed URL to read a private object; None on failure."""
    try:
        res = supabase.storage.from_(EVIDENCE_BUCKET).create_signed_url(
            path, expires_in
        )
        return res.get("signedURL") or res.get("signedUrl")
    except Exception:  # noqa: BLE001 — a missing/old object shouldn't break the list
        return None
