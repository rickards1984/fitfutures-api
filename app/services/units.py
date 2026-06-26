"""Unit progress helpers.

A unit's status is derived from its tasks' completion (the brief: "a unit's
status should derive from its task completion"), so it stays consistent
wherever it is computed. `not_applicable` tasks are excluded from the
"all complete" check.
"""


def derive_unit_status(task_statuses: list[str]) -> str:
    """Roll a unit's task statuses up into not_started / in_progress / complete."""
    applicable = [s for s in task_statuses if s != "not_applicable"]
    if applicable and all(s == "complete" for s in applicable):
        return "complete"
    if any(s in ("in_progress", "complete") for s in task_statuses):
        return "in_progress"
    return "not_started"
