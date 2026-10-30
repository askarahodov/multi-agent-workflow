"""SHA-pinned migration review delivery contract."""
import pytest
from tools.github_kanban_sync.review_dispatch import (
    ReviewDispatchError, approval_matches_head, request_migration_review,
)

SHA = "a" * 40
NEXT = "b" * 40


class Board:
    def __init__(self, status="ready"):
        self.card = {"id": "t_qa", "status": status, "assignee": "sdlc-tester"}
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


def test_developer_owned_qa_card_is_rejected():
    b = Board()
    b.card["assignee"] = "sdlc-developer"
    with pytest.raises(ReviewDispatchError):
        dispatch(b)


def test_receipt_must_match_current_sha_and_latest_verdict():
    approved = {"body": f"MIGRATION_182_ACCEPTANCE: APPROVED\nSHA: {SHA}", "user": {"login": "trusted-qa"}}
    rejected = {"body": f"MIGRATION_182_ACCEPTANCE: CHANGES_REQUESTED\nSHA: {SHA}", "user": {"login": "trusted-qa"}}
    assert approval_matches_head([approved], SHA, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([approved], NEXT, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([approved, rejected], SHA, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([rejected, approved], NEXT, trusted_authors={"trusted-qa"})
    assert not approval_matches_head([{"body": "MIGRATION_182_ACCEPTANCE: APPROVED"}], SHA, trusted_authors={"trusted-qa"})


def test_pass_is_an_accepted_spelling_of_approved():
    """The independent migration verdicts say PASS. Reading that as an approval is a
    FORMAT equivalence — the SHA pin and the trusted-author requirement stay strict."""
    passed = {"body": f"MIGRATION_182_ACCEPTANCE: PASS\nSHA: {SHA}", "user": {"login": "trusted-qa"}}
    assert approval_matches_head([passed], SHA, trusted_authors={"trusted-qa"})
    # still pinned to the exact head
    assert not approval_matches_head([passed], NEXT, trusted_authors={"trusted-qa"})
    # still requires a trusted author (and never an empty allow-list)
    assert not approval_matches_head([passed], SHA, trusted_authors={"someone-else"})
    assert not approval_matches_head([passed], SHA, trusted_authors=set())
    # a revocation for the same SHA still wins, regardless of order
    revoked = {"body": f"MIGRATION_182_ACCEPTANCE: CHANGES_REQUESTED\nSHA: {SHA}", "user": {"login": "trusted-qa"}}
    assert not approval_matches_head([passed, revoked], SHA, trusted_authors={"trusted-qa"})



def test_pr_ingestion_routes_once_and_retries_missing_qa(tmp_path, monkeypatch):
    """Real GKS ingestion contract: failed dispatch is not marked consumed."""
    from tools.github_kanban_sync import links
    from tools.github_kanban_sync.config import Settings
    from tools.github_kanban_sync.ingest import Ingestor
    from tools.github_kanban_sync.store import Store
    from tools.tests._gks_helpers import add_task, board, make_kanban_db

    repo = "askarahodov/multi-agent-workflow"
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    add_task(db, "t_qa", assignee="sdlc-tester")
    store = Store(tmp_path / "coord.db")
    links.bind(store, repo, 182, "me", "t_dev", owner="sdlc-developer")
    kb = board(tmp_path / "kanban.db")
    settings = Settings(repo=repo, board="me",
                        coord_db=tmp_path / "coord.db",
                        kanban_db=tmp_path / "kanban.db")
    ing = Ingestor(store, None, kb, settings)
    pr = {"number": 194, "state": "open", "merged_at": None,
          "updated_at": "2026-10-30T12:00:00Z",
          "title": "Issue #182 migration",
          "body": "Fixes #182", "head": {"sha": SHA, "ref": "refactor/migration"},
          "base": {"sha": NEXT}}

    monkeypatch.setenv("GKS_MIGRATION_QA_TASK_ID", "t_qa")
    assert ing._ingest_pull(pr) == 1
    assert ing._ingest_pull(pr) == 0
    assert len([c for c in kb.comments("t_qa") if "gks:qa-request" in c["body"]]) == 1
    assert store.counts()["pending"] == 0
    kb.close()
    store.close()



def test_review_check_cli_fails_closed_for_stale_head(monkeypatch, capsys):
    import sys
    import types
    from tools.github_kanban_sync import cli
    from tools.github_kanban_sync import github as github_mod

    class Response:
        def __init__(self, data):
            self.data = data

    class FakeGitHub:
        def __init__(self, *args, **kwargs):
            pass

        def get_pull(self, number):
            return Response({"head": {"sha": NEXT}})

        def list_all_issue_comments(self, number):
            return [{"body": f"MIGRATION_182_ACCEPTANCE: APPROVED\\nSHA: {SHA}",
                     "user": {"login": "trusted-qa"}}]

        def close(self):
            pass

    monkeypatch.setattr(github_mod, "GitHubClient", FakeGitHub)
    assert cli.main(["review-check", "--issue", "182", "--pr", "194",
                     "--trusted-author", "trusted-qa"]) == 1
    assert '"approved": false' in capsys.readouterr().out


def test_duplicate_request_safe_after_qa_completed():
    board = Board()
    assert dispatch(board)["status"] == "delivered"
    board.card["status"] = "done"
    assert dispatch(board)["status"] == "duplicate"
    with pytest.raises(ReviewDispatchError):
        dispatch(board, NEXT)


def test_pr_ingest_without_opt_in_does_not_fail(tmp_path, monkeypatch):
    from tools.github_kanban_sync import links
    from tools.github_kanban_sync.config import Settings
    from tools.github_kanban_sync.ingest import Ingestor
    from tools.github_kanban_sync.store import Store
    from tools.tests._gks_helpers import add_task, board, make_kanban_db

    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    store = Store(tmp_path / "coord.db")
    repo = "askarahodov/multi-agent-workflow"
    links.bind(store, repo, 182, "me", "t_dev")
    kb = board(db)
    settings = Settings(repo=repo, board="me", coord_db=tmp_path / "coord.db", kanban_db=db)
    ing = Ingestor(store, None, kb, settings)
    monkeypatch.delenv("GKS_MIGRATION_QA_TASK_ID", raising=False)
    pr = {"number": 194, "state": "open", "updated_at": "2026-10-30T12:00:00Z",
          "title": "Fixes #182", "head": {"sha": SHA}}
    assert ing._ingest_pull(pr) == 1
    assert ing._ingest_pull(pr) == 0
    kb.close()
    store.close()
