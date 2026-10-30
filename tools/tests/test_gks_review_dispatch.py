"""SHA-pinned migration review delivery contract."""
import pytest
from tools.github_kanban_sync.review_dispatch import (
    ReviewDispatchError, approval_matches_head, request_migration_review,
)

SHA = "a" * 40
NEXT = "b" * 40


class Board:
    def __init__(self, status="ready"):
        self.card = {"id": "t_qa", "status": status}
        self.comments = []
        self.events = []

    def task(self, task_id):
        return self.card if task_id == "t_qa" else None

    def has_comment_marker(self, task_id, marker):
        return any(marker in c for c in self.comments)

    def add_comment(self, task_id, body):
        self.comments.append(body)

    def record_event(self, task_id, kind, payload):
        self.events.append((kind, payload))


def dispatch(board, sha=SHA, task="t_qa", owner="t_dev"):
    return request_migration_review(
        board, qa_task_id=task, issue=182, pr=194,
        head_sha=sha, owner_task_id=owner,
    )


def test_one_delivery_per_sha_and_new_sha_invalidates_prior():
    board = Board()
    assert dispatch(board)["status"] == "delivered"
    assert dispatch(board)["status"] == "duplicate"
    assert len(board.comments) == 1
    assert dispatch(board, NEXT)["status"] == "delivered"
    assert len(board.comments) == 2
    assert board.events[-1][1]["head_sha"] == NEXT
    assert "APPROVED or CHANGES_REQUESTED" in board.comments[-1]


@pytest.mark.parametrize("task,owner,status", [
    ("", "t_dev", "ready"),
    ("t_dev", "t_dev", "ready"),
    ("t_qa", "t_dev", "done"),
    ("t_qa", "t_dev", "blocked"),
])
def test_missing_independence_or_unavailable_reviewer_fails_closed(task, owner, status):
    with pytest.raises(ReviewDispatchError):
        dispatch(Board(status=status), task=task, owner=owner)


def test_receipt_must_match_current_sha_and_latest_verdict():
    approved = {"body": f"MIGRATION_182_ACCEPTANCE: APPROVED\nSHA: {SHA}", "user": {"login": "trusted-qa"}}
    rejected = {"body": f"MIGRATION_182_ACCEPTANCE: CHANGES_REQUESTED\nSHA: {SHA}", "user": {"login": "trusted-qa"}}
    assert approval_matches_head([approved], SHA, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([approved], NEXT, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([approved, rejected], SHA, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([rejected, approved], NEXT, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([{"body": "MIGRATION_182_ACCEPTANCE: APPROVED"}], SHA, trusted_authors={"trusted-qa"})
