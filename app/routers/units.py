"""Units router.

- GET /v1/units   all 6 units (global reference data) with their task lists.
"""
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.core.auth import AuthContext, get_current_user
from app.core.supabase import get_supabase
from app.models.schemas import UnitOut, UnitTaskOut

router = APIRouter(prefix="/units", tags=["units"])


@router.get("", response_model=list[UnitOut])
async def list_units(
    user: AuthContext = Depends(get_current_user),
) -> list[UnitOut]:
    """Return the 6 fixed units, each with its ordered task checklist."""
    supabase = get_supabase()

    units = await run_in_threadpool(
        lambda: supabase.table("units").select("*").order("unit_number").execute()
    )
    tasks = await run_in_threadpool(
        lambda: supabase.table("unit_tasks").select("*").order("task_order").execute()
    )

    tasks_by_unit: dict[str, list[UnitTaskOut]] = {}
    for row in tasks.data or []:
        tasks_by_unit.setdefault(row["unit_id"], []).append(UnitTaskOut(**row))

    return [
        UnitOut(**unit, tasks=tasks_by_unit.get(unit["id"], []))
        for unit in (units.data or [])
    ]
