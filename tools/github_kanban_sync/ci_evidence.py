"""Fail-closed CI assessment for developer GitHub <-> Kanban coordination.

A completed/green check is a specific positive observation. Missing, neutral,
skipped, pending or truncated results must not authorize automatic Issue closure.
The independent GitHub ruleset is authoritative for which names are required;
operators explicitly copy those names into GKS_REQUIRED_CHECKS before enabling
the local close command.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

_FAILURE = frozenset({
    "failure", "error", "timed_out", "cancelled", "action_required",
    "startup_failure", "skipped", "stale",
})
_PENDING = frozenset({"pending", "in_progress", "queued", "waiting", "requested"})


def classify_ci_state(states: Sequence[str | None]) -> str:
    """Collapse observations without interpreting unknown states as green."""
    if not states:
        return "unknown"
    normalized = [state.lower() if isinstance(state, str) else None for state in states]
    if any(state in _FAILURE for state in normalized):
        return "failure"
    if any(state in _PENDING for state in normalized):
        return "pending"
    if any(state != "success" for state in normalized):
        return "unknown"
    return "success"


def check_run_state(run: dict[str, Any]) -> str | None:
    """Use a running check's status, not its absent/stale conclusion."""
    status = run.get("status")
    if not isinstance(status, str):
        return None
    if status != "completed":
        return status
    return run.get("conclusion")


def observed_ci_state(combined: dict[str, Any], runs: dict[str, Any]) -> str:
    """Informational CI summary; not permission to close an Issue."""
    statuses = combined.get("statuses", [])
    check_runs = runs.get("check_runs", [])
    if not isinstance(statuses, list) or not isinstance(check_runs, list):
        return "unknown"
    if not all(isinstance(s, dict) for s in statuses + check_runs):
        return "unknown"
    return classify_ci_state(
        [s.get("state") for s in statuses]
        + [check_run_state(r) for r in check_runs]
    )


def required_ci_state(
    combined: dict[str, Any],
    runs: dict[str, Any],
    required_checks: Sequence[str],
) -> str:
    """Verify every named required context on the exact requested commit SHA.

    Fail closed for incomplete check-run pagination or malformed API bodies.
    A successful unrelated check cannot substitute for a required one.
    """
    names = tuple(required_checks)
    if not names or any(not isinstance(n, str) or not n.strip() for n in names):
        return "unknown"
    statuses = combined.get("statuses")
    checks = runs.get("check_runs")
    total = runs.get("total_count")
    if (not isinstance(statuses, list) or not isinstance(checks, list)
            or type(total) is not int or total != len(checks)
            or not all(isinstance(x, dict) for x in statuses + checks)):
        return "unknown"

    observed: dict[str, list[str | None]] = defaultdict(list)
    for item in statuses:
        context = item.get("context")
        if isinstance(context, str):
            observed[context].append(item.get("state"))
    for item in checks:
        name = item.get("name")
        if isinstance(name, str):
            observed[name].append(check_run_state(item))

    if any(name not in observed for name in names):
        return "unknown"
    return classify_ci_state([state for name in names for state in observed[name]])
