"""SHA-pinned, idempotent delivery of independent review requests to a preassigned QA card.

Development-only coordination. Never creates/deletes worktrees or writes the
Kanban task state. A local Kanban dispatcher is responsible for claiming READY cards.
"""
from __future__ import annotations

import re

_SHA = re.compile(r"^[0-9a-f]{40}$")
_APPROVAL = re.compile(r"\bMIGRATION_182_ACCEPTANCE:\s*APPROVED\b")


class ReviewDispatchError(RuntimeError):
    """Fail closed if the independent reviewer cannot be reached."""


def request_migration_review(board, *, qa_task_id: str, issue: int, pr: int,
                             head_sha: str, owner_task_id: str | None = None) -> dict:
    """Deliver only one request per PR head SHA to an *existing* QA task.

    Delivery is a message and audit event, not a claim that the worker has run.
    """
    if not _SHA.fullmatch(head_sha):
        raise ValueError("A full 40-character pull request head SHA is required")
    if not qa_task_id:
        raise ReviewDispatchError("GKS_MIGRATION_QA_TASK_ID must name an independent QA task")
    if qa_task_id == owner_task_id:
        raise ReviewDispatchError("QA task must differ from the developer task")
    task = board.task(qa_task_id)
    if not task:
        raise ReviewDispatchError("QA task does not exist; create and assign it through Hermes")
    if task.get("status") not in ("ready", "running"):
        raise ReviewDispatchError("QA task must be ready or running; local orchestrator must requeue it")
    marker = f"<!-- gks:qa-request issue={issue} pr={pr} sha={head_sha} -->"
    if board.has_comment_marker(qa_task_id, marker):
        return {"status": "duplicate", "task_id": qa_task_id, "sha": head_sha}
    body = (f"{marker}\nIndependent migration acceptance required for "
            f"PR #{pr}, Issue #{issue}, exact HEAD `{head_sha}`.\n"
            "Read-only review: verify Compose Dockerfile paths, current docs "
            "commands, required GitHub checks, security and main compatibility. "
            "Publish MIGRATION_182_ACCEPTANCE: APPROVED or CHANGES_REQUESTED "
            f"with this exact SHA in Issue #{issue}. Older approvals are stale.")
    board.add_comment(qa_task_id, body)
    board.record_event(qa_task_id, "review_requested",
                       {"issue": issue, "pr": pr, "head_sha": head_sha,
                        "independent": True})
    return {"status": "delivered", "task_id": qa_task_id, "sha": head_sha}


def approval_matches_head(comments: list[dict], head_sha: str) -> bool:
    """Only accept a positive independent receipt bound to the current SHA.

    A later CHANGES_REQUESTED for the same SHA revokes approval.
    """
    if not _SHA.fullmatch(head_sha):
        return False
    verdict = None
    for comment in comments:
        body = comment.get("body") or ""
        if head_sha not in body:
            continue
        if "MIGRATION_182_ACCEPTANCE:" not in body:
            continue
        if "CHANGES_REQUESTED" in body:
            verdict = False
        elif _APPROVAL.search(body):
            verdict = True
    return verdict is True
