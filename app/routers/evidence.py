"""Evidence router.

- POST /v1/evidence/upload-url          presigned upload URL (private bucket)
- POST /v1/evidence                     record an item after upload
- GET  /v1/evidence/placement/{id}      a placement's evidence (with signed URLs)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    EvidenceCreateRequest,
    EvidenceItemResponse,
    EvidenceUploadUrlRequest,
    EvidenceUploadUrlResponse,
)
from app.services.placements import (
    assert_can_view_placement,
    assert_is_owner,
    fetch_placement,
)
from app.services.storage import (
    EVIDENCE_BUCKET,
    build_object_path,
    create_download_url,
    create_upload_url,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.post("/upload-url", response_model=EvidenceUploadUrlResponse)
async def evidence_upload_url(
    body: EvidenceUploadUrlRequest,
    user: AuthContext = Depends(get_current_user),
) -> EvidenceUploadUrlResponse:
    """Mint a presigned upload URL for the learner's own placement."""
    supabase = get_supabase()
    placement = await run_in_threadpool(
        lambda: fetch_placement(supabase, body.placement_id)
    )
    assert_is_owner(placement, user)

    path = build_object_path(body.placement_id, body.filename)
    try:
        signed = await run_in_threadpool(lambda: create_upload_url(supabase, path))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not create an upload URL. Ensure the private "
                f"'{EVIDENCE_BUCKET}' Storage bucket exists. ({exc})"
            ),
        )
    return EvidenceUploadUrlResponse(bucket=EVIDENCE_BUCKET, **signed)


@router.post("", response_model=EvidenceItemResponse, status_code=status.HTTP_201_CREATED)
async def create_evidence(
    body: EvidenceCreateRequest,
    user: AuthContext = Depends(get_current_user),
) -> EvidenceItemResponse:
    """Record an evidence item after its file has been uploaded."""
    supabase = get_supabase()
    placement = await run_in_threadpool(
        lambda: fetch_placement(supabase, body.placement_id)
    )
    assert_is_owner(placement, user)

    row = {
        "placement_id": body.placement_id,
        "unit_task_id": body.unit_task_id,
        "title": body.title,
        "description": body.description,
        "file_url": body.path,
        "file_type": body.file_type,
        "file_size_bytes": body.file_size_bytes,
        "uploaded_by": user.user_id,
    }
    saved = await run_in_threadpool(
        lambda: supabase.table("evidence_items").insert(row).execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record evidence item.",
        )
    item = saved.data[0]
    download_url = await run_in_threadpool(
        lambda: create_download_url(supabase, item["file_url"])
    )
    return EvidenceItemResponse(**item, download_url=download_url)


@router.get("/placement/{placement_id}", response_model=list[EvidenceItemResponse])
async def list_evidence(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> list[EvidenceItemResponse]:
    """All evidence for a placement, each with a short-lived signed URL."""
    supabase = get_supabase()
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    await run_in_threadpool(lambda: assert_can_view_placement(supabase, placement, user))

    res = await run_in_threadpool(
        lambda: supabase.table("evidence_items")
        .select("*")
        .eq("placement_id", placement_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []

    items: list[EvidenceItemResponse] = []
    for item in rows:
        download_url = await run_in_threadpool(
            lambda p=item["file_url"]: create_download_url(supabase, p)
        )
        items.append(EvidenceItemResponse(**item, download_url=download_url))
    return items
