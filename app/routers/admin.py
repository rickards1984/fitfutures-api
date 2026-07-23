"""Admin router (Phase 9a — enrolment + roster).

Staff-only (tutor/admin) views for the placement coordinator:

- GET /v1/admin/learners              all learners, flagged with whether they
                                      already have an active placement
- GET /v1/admin/placements            the active roster (name, facility, week,
                                      latest RAG)
- GET /v1/admin/learner/{id}/summary  read-only detail for a learner's active
                                      placement (KPI totals + unit progress)

Enrolment itself reuses POST /v1/placements (which seeds milestone rows).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import (
    AdminChecklistResponse,
    AdminChecklistTask,
    AdminChecklistUnit,
    AdminEvidenceItem,
    AdminEvidenceResponse,
    AdminEvidenceUnitGroup,
    AdminLearnerItem,
    AdminLearnersResponse,
    AdminLearnerSummary,
    AdminPlacementItem,
    AdminPlacementsResponse,
    AdminUnitProgressItem,
    EvidenceItemResponse,
    EvidenceReviewRequest,
    KpiTotalLine,
)
from app.services.kpi_calc import METRICS
from app.services.placements import current_week_number, fetch_placement, require_staff
from app.services.storage import create_download_url
from app.services.units import derive_unit_status

router = APIRouter(prefix="/admin", tags=["admin"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/learners", response_model=AdminLearnersResponse)
async def list_learners(
    user: AuthContext = Depends(get_current_user),
) -> AdminLearnersResponse:
    """All learner profiles, newest first, flagged by active-placement status."""
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    profiles = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("id, full_name, email, created_at")
        .eq("role", "learner")
        .order("created_at", desc=True)
        .execute()
    )
    rows = profiles.data or []

    active = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("learner_id")
        .eq("status", "active")
        .execute()
    )
    active_ids = {r["learner_id"] for r in (active.data or [])}

    items = [
        AdminLearnerItem(
            id=r["id"],
            full_name=r.get("full_name") or "Unknown learner",
            email=r.get("email") or "",
            created_at=r.get("created_at"),
            has_active_placement=r["id"] in active_ids,
        )
        for r in rows
    ]
    return AdminLearnersResponse(items=items)


@router.get("/placements", response_model=AdminPlacementsResponse)
async def list_active_placements(
    user: AuthContext = Depends(get_current_user),
) -> AdminPlacementsResponse:
    """Active roster: learner name, facility, week X of Y, latest week's RAG."""
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    placements = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("*")
        .eq("status", "active")
        .order("start_date", desc=True)
        .execute()
    )
    rows = placements.data or []
    if not rows:
        return AdminPlacementsResponse(items=[])

    learner_ids = list({r["learner_id"] for r in rows})
    placement_ids = [r["id"] for r in rows]

    profiles = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("id, full_name")
        .in_("id", learner_ids)
        .execute()
    )
    names = {p["id"]: p.get("full_name") or "Unknown learner" for p in (profiles.data or [])}

    # Latest RAG per placement: fetch all weeks once, keep the highest week_number.
    entries = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select("placement_id, week_number, overall_status")
        .in_("placement_id", placement_ids)
        .order("week_number", desc=True)
        .execute()
    )
    latest_rag: dict[str, str] = {}
    for e in entries.data or []:
        latest_rag.setdefault(e["placement_id"], e.get("overall_status") or "no_entry")

    awaiting, since_review = await _roster_signals(supabase, placement_ids)

    items = [
        AdminPlacementItem(
            placement_id=r["id"],
            learner_id=r["learner_id"],
            learner_name=names.get(r["learner_id"], "Unknown learner"),
            facility_name=r.get("facility_name") or "—",
            route=r["route"],
            current_week_number=current_week_number(r["start_date"]),
            planned_weeks=r.get("planned_weeks") or 0,
            latest_rag=latest_rag.get(r["id"], "no_entry"),
            evidence_awaiting_review=awaiting.get(r["id"], 0),
            tasks_completed_since_review=since_review.get(r["id"], 0),
        )
        for r in rows
    ]
    return AdminPlacementsResponse(items=items)


def _parse_ts(value):
    """Parse an ISO timestamp (as Supabase returns it) to an aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _roster_signals(supabase, placement_ids: list[str]):
    """Per-placement assessor signals: evidence awaiting review, and tasks
    completed since the last evidence review.

    "Last review" is the most recent evidence-review timestamp on the placement;
    if nothing has been reviewed yet, every completed task counts.
    """
    evidence = await run_in_threadpool(
        lambda: supabase.table("evidence_items")
        .select("placement_id, supervisor_approved, supervisor_approved_at")
        .in_("placement_id", placement_ids)
        .execute()
    )
    awaiting: dict[str, int] = {}
    last_review: dict[str, datetime] = {}
    for e in evidence.data or []:
        pid = e["placement_id"]
        if e.get("supervisor_approved") is None:
            awaiting[pid] = awaiting.get(pid, 0) + 1
        reviewed_at = _parse_ts(e.get("supervisor_approved_at"))
        if reviewed_at and (pid not in last_review or reviewed_at > last_review[pid]):
            last_review[pid] = reviewed_at

    progress = await run_in_threadpool(
        lambda: supabase.table("learner_task_progress")
        .select("placement_id, status, completed_at")
        .in_("placement_id", placement_ids)
        .eq("status", "complete")
        .execute()
    )
    since_review: dict[str, int] = {}
    for p in progress.data or []:
        pid = p["placement_id"]
        cutoff = last_review.get(pid)
        completed_at = _parse_ts(p.get("completed_at"))
        if cutoff is None or (completed_at and completed_at > cutoff):
            since_review[pid] = since_review.get(pid, 0) + 1
    return awaiting, since_review


@router.get("/learner/{learner_id}/summary", response_model=AdminLearnerSummary)
async def learner_summary(
    learner_id: str,
    user: AuthContext = Depends(get_current_user),
) -> AdminLearnerSummary:
    """Read-only detail for a learner's active placement: KPI totals + units."""
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    placement_res = await run_in_threadpool(
        lambda: supabase.table("placements")
        .select("*")
        .eq("learner_id", learner_id)
        .eq("status", "active")
        .order("start_date", desc=True)
        .limit(1)
        .execute()
    )
    if not placement_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This learner has no active placement.",
        )
    placement = placement_res.data[0]
    placement_id = placement["id"]

    learner = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("full_name")
        .eq("id", learner_id)
        .limit(1)
        .execute()
    )
    learner_name = (
        learner.data[0].get("full_name") if learner.data else None
    ) or "Unknown learner"

    # KPI totals: cumulative actuals vs total targets.
    entries = await run_in_threadpool(
        lambda: supabase.table("kpi_entries")
        .select("*")
        .eq("placement_id", placement_id)
        .execute()
    )
    rows = entries.data or []
    kpi_lines = [
        KpiTotalLine(
            key=m.key,
            label=m.label,
            actual=sum(float(r.get(m.actual_col) or 0) for r in rows),
            target=float(placement.get(m.total_target_col) or 0),
        )
        for m in METRICS
    ]

    units_summary, units_complete, units_total = await _unit_progress(
        supabase, placement_id
    )

    return AdminLearnerSummary(
        learner_id=learner_id,
        learner_name=learner_name,
        placement_id=placement_id,
        facility_name=placement.get("facility_name") or "—",
        route=placement["route"],
        current_week_number=current_week_number(placement["start_date"]),
        planned_weeks=placement.get("planned_weeks") or 0,
        weeks_logged=len(rows),
        kpi_lines=kpi_lines,
        units=units_summary,
        units_complete=units_complete,
        units_total=units_total,
    )


async def _unit_progress(supabase, placement_id: str):
    """Per-unit status for a placement, derived from stored task progress."""
    units = await run_in_threadpool(
        lambda: supabase.table("units")
        .select("id, unit_number, title")
        .order("unit_number")
        .execute()
    )
    unit_rows = units.data or []

    tasks = await run_in_threadpool(
        lambda: supabase.table("unit_tasks").select("id, unit_id").execute()
    )
    tasks_by_unit: dict[str, list[str]] = {}
    for t in tasks.data or []:
        tasks_by_unit.setdefault(t["unit_id"], []).append(t["id"])

    progress = await run_in_threadpool(
        lambda: supabase.table("learner_task_progress")
        .select("unit_task_id, status")
        .eq("placement_id", placement_id)
        .execute()
    )
    status_by_task = {p["unit_task_id"]: p["status"] for p in (progress.data or [])}

    items: list[AdminUnitProgressItem] = []
    complete = 0
    for u in unit_rows:
        task_ids = tasks_by_unit.get(u["id"], [])
        statuses = [status_by_task.get(tid, "not_started") for tid in task_ids]
        derived = derive_unit_status(statuses)
        if derived == "complete":
            complete += 1
        items.append(
            AdminUnitProgressItem(
                unit_number=u["unit_number"],
                title=u["title"],
                status=derived,
            )
        )
    return items, complete, len(unit_rows)


def _profile_names(supabase, ids: list[str]) -> dict[str, str]:
    """Map profile id -> full name (falls back to 'Unknown') for the given ids."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    res = (
        supabase.table("profiles")
        .select("id, full_name")
        .in_("id", list(set(ids)))
        .execute()
    )
    return {p["id"]: (p.get("full_name") or "Unknown") for p in (res.data or [])}


async def _learner_name(supabase, learner_id: str) -> str:
    res = await run_in_threadpool(
        lambda: supabase.table("profiles")
        .select("full_name")
        .eq("id", learner_id)
        .limit(1)
        .execute()
    )
    return (res.data[0].get("full_name") if res.data else None) or "Unknown learner"


@router.get(
    "/placement/{placement_id}/evidence", response_model=AdminEvidenceResponse
)
async def placement_evidence(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> AdminEvidenceResponse:
    """All evidence for a placement, grouped by unit, for assessor review.

    Each item carries a signed download URL, who uploaded it and when, and its
    current approval state + reviewer (general items — not tied to a unit task —
    land in a trailing 'General' group).
    """
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    learner_name = await _learner_name(supabase, placement["learner_id"])

    evidence = await run_in_threadpool(
        lambda: supabase.table("evidence_items")
        .select("*")
        .eq("placement_id", placement_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = evidence.data or []

    # Unit + task lookups so items can be grouped and labelled by unit.
    units = await run_in_threadpool(
        lambda: supabase.table("units")
        .select("id, unit_number, title")
        .order("unit_number")
        .execute()
    )
    unit_rows = units.data or []
    tasks = await run_in_threadpool(
        lambda: supabase.table("unit_tasks")
        .select("id, unit_id, description")
        .execute()
    )
    task_meta = {t["id"]: t for t in (tasks.data or [])}
    unit_by_id = {u["id"]: u for u in unit_rows}

    # Resolve uploader + reviewer display names in one query.
    people = _profile_names(
        supabase,
        [r.get("uploaded_by") for r in rows] + [r.get("supervisor_id") for r in rows],
    )

    # Bucket items by unit_number (None → general), preserving list order.
    buckets: dict[object, list[AdminEvidenceItem]] = {}
    for item in rows:
        task = task_meta.get(item.get("unit_task_id"))
        unit = unit_by_id.get(task["unit_id"]) if task else None
        unit_number = unit["unit_number"] if unit else None
        download_url = await run_in_threadpool(
            lambda p=item["file_url"]: create_download_url(supabase, p)
        )
        buckets.setdefault(unit_number, []).append(
            AdminEvidenceItem(
                id=item["id"],
                title=item["title"],
                description=item.get("description"),
                file_type=item["file_type"],
                unit_task_id=item.get("unit_task_id"),
                task_description=task["description"] if task else None,
                uploaded_by_name=people.get(item.get("uploaded_by"), "Unknown"),
                created_at=item.get("created_at"),
                supervisor_approved=item.get("supervisor_approved"),
                supervisor_approved_at=item.get("supervisor_approved_at"),
                review_feedback=item.get("review_feedback"),
                reviewed_by_name=people.get(item.get("supervisor_id")),
                download_url=download_url,
            )
        )

    groups: list[AdminEvidenceUnitGroup] = []
    for u in unit_rows:
        n = u["unit_number"]
        if n in buckets:
            groups.append(
                AdminEvidenceUnitGroup(
                    unit_number=n,
                    title=f"Unit {n} — {u['title']}",
                    items=buckets[n],
                )
            )
    if None in buckets:
        groups.append(
            AdminEvidenceUnitGroup(
                unit_number=None, title="General", items=buckets[None]
            )
        )

    return AdminEvidenceResponse(
        placement_id=placement_id,
        learner_name=learner_name,
        groups=groups,
    )


@router.get(
    "/placement/{placement_id}/checklist", response_model=AdminChecklistResponse
)
async def placement_checklist(
    placement_id: str,
    user: AuthContext = Depends(get_current_user),
) -> AdminChecklistResponse:
    """Read-only assessment checklist: per-unit task completion for a placement.

    For each task an assessor sees its status, whether it needs supervisor
    sign-off (and whether that's done), and how many evidence items are attached.
    """
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))
    placement = await run_in_threadpool(lambda: fetch_placement(supabase, placement_id))
    learner_name = await _learner_name(supabase, placement["learner_id"])

    units = await run_in_threadpool(
        lambda: supabase.table("units")
        .select("id, unit_number, title")
        .order("unit_number")
        .execute()
    )
    unit_rows = units.data or []

    tasks = await run_in_threadpool(
        lambda: supabase.table("unit_tasks")
        .select("*")
        .order("task_order")
        .execute()
    )
    tasks_by_unit: dict[str, list[dict]] = {}
    for t in tasks.data or []:
        tasks_by_unit.setdefault(t["unit_id"], []).append(t)

    progress = await run_in_threadpool(
        lambda: supabase.table("learner_task_progress")
        .select("unit_task_id, status, supervisor_signed_at")
        .eq("placement_id", placement_id)
        .execute()
    )
    prog_by_task = {p["unit_task_id"]: p for p in (progress.data or [])}

    # Evidence counts per task.
    evidence = await run_in_threadpool(
        lambda: supabase.table("evidence_items")
        .select("unit_task_id")
        .eq("placement_id", placement_id)
        .execute()
    )
    evidence_count: dict[str, int] = {}
    for e in evidence.data or []:
        tid = e.get("unit_task_id")
        if tid:
            evidence_count[tid] = evidence_count.get(tid, 0) + 1

    checklist_units: list[AdminChecklistUnit] = []
    for u in unit_rows:
        unit_tasks = sorted(
            tasks_by_unit.get(u["id"], []), key=lambda t: t["task_order"]
        )
        task_items: list[AdminChecklistTask] = []
        statuses: list[str] = []
        for t in unit_tasks:
            prog = prog_by_task.get(t["id"], {})
            task_status = prog.get("status") or "not_started"
            statuses.append(task_status)
            task_items.append(
                AdminChecklistTask(
                    task_order=t["task_order"],
                    description=t["description"],
                    is_mandatory=t["is_mandatory"],
                    requires_evidence=t["requires_evidence"],
                    requires_supervisor_sign=t["requires_supervisor_sign"],
                    status=task_status,
                    supervisor_signed=bool(prog.get("supervisor_signed_at")),
                    evidence_count=evidence_count.get(t["id"], 0),
                )
            )
        checklist_units.append(
            AdminChecklistUnit(
                unit_number=u["unit_number"],
                title=u["title"],
                status=derive_unit_status(statuses),
                tasks=task_items,
            )
        )

    return AdminChecklistResponse(
        placement_id=placement_id,
        learner_name=learner_name,
        units=checklist_units,
    )


@router.patch("/evidence/{evidence_id}/review", response_model=EvidenceItemResponse)
async def review_evidence(
    evidence_id: str,
    body: EvidenceReviewRequest,
    user: AuthContext = Depends(get_current_user),
) -> EvidenceItemResponse:
    """Staff approve an evidence item or request changes (with optional note).

    Records the reviewer id + timestamp so the audit trail is preserved.
    """
    supabase = get_supabase()
    await run_in_threadpool(lambda: require_staff(supabase, user))

    existing = await run_in_threadpool(
        lambda: supabase.table("evidence_items")
        .select("*")
        .eq("id", evidence_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence item not found."
        )

    updates = {
        "supervisor_approved": body.approved,
        "supervisor_approved_at": _now(),
        "supervisor_id": user.user_id,
        "review_feedback": (body.feedback or None),
    }
    saved = await run_in_threadpool(
        lambda: supabase.table("evidence_items")
        .update(updates)
        .eq("id", evidence_id)
        .execute()
    )
    if not saved.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record the review.",
        )
    item = saved.data[0]
    download_url = await run_in_threadpool(
        lambda: create_download_url(supabase, item["file_url"])
    )
    return EvidenceItemResponse(**item, download_url=download_url)
