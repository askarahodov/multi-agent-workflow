"""Operator CLI for the GitHub <-> Kanban sync (Issue #192 §6/§7).

Subcommands
-----------
``status``   links, cursors, pending events, delivery journal, health.
``health``   one-line health/lag verdict (exit 0 healthy, 1 not, 2 tool error).
``sync``     poll + ingest GitHub -> Kanban, then publish Kanban -> GitHub.
``ingest``   ingest only (issues / comments / pulls / ci).
``publish``  publish only (optionally one ``--task``).
``conflict`` report changed-path / reservation / stale-main conflicts.
``bind``     manual, idempotent Issue <-> card binding (never clones).
``unbind``   remove a binding.
``dedupe``   remove duplicate GitHub->Kanban ingest comments from a card.
``reconcile``inventory of links / unlinked issues / unlinked cards (read-only).
``close``    close a linked Issue *only* on confirmed merge + CI + evidence.
``trail``    delivery trail for one ``source_event_id``.
``reserve``  register an ownership reservation (e.g. #182).

Every write is idempotent and rate-limited; nothing here force-pushes, rebases,
resets, merges or deletes any worktree/branch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from . import conflict as conflict_mod
from . import links as links_mod
from . import observability
from .config import Settings, resolve_token
from .store import Store


def _context(settings: Settings, *, with_github: bool = True):
    from .github import GitHubClient
    from .kanban import KanbanBoard

    store = Store(settings.coord_db)
    board = KanbanBoard(settings.kanban_db, author=settings.author)
    gh = None
    if with_github:
        gh = GitHubClient(resolve_token(), repo=settings.repo)
    return store, board, gh


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False))


def cmd_status(args: argparse.Namespace) -> int:
    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    store, board, _ = _context(settings, with_github=False)
    try:
        _emit(observability.status(store, board))
        return 0
    finally:
        store.close()
        board.close()


def cmd_health(args: argparse.Namespace) -> int:
    settings = Settings.from_env(coord_db=args.db)
    store = Store(settings.coord_db)
    try:
        report = observability.health(store, max_lag=args.max_lag)
        _emit(report)
        return 0 if report["healthy"] else 1
    finally:
        store.close()


def cmd_ingest(args: argparse.Namespace) -> int:
    from .ingest import Ingestor

    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    store, board, gh = _context(settings)
    ingestor = Ingestor(store, gh, board, settings)
    out: dict[str, Any] = {}
    try:
        if args.issues or args.all:
            out["issues"] = ingestor.ingest_issues(full=args.full)
        for number in args.issue or []:
            out[f"comments:{number}"] = ingestor.ingest_issue_comments(int(number), full=args.full)
        if args.pulls or args.all:
            out["pulls"] = ingestor.ingest_pulls(full=args.full)
        if args.ci:
            out["ci"] = ingestor.ingest_ci(args.ci)
        _emit(out)
        return 0
    finally:
        store.close()
        board.close()
        if gh:
            gh.close()


def cmd_publish(args: argparse.Namespace) -> int:
    from .publish import Publisher

    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    store, board, gh = _context(settings)
    assert gh is not None
    publisher = Publisher(store, gh, board, settings)
    try:
        if args.task:
            _emit(publisher.publish_task(args.task, force=args.force))
        else:
            _emit(publisher.publish_pending(force=args.force))
        return 0
    finally:
        store.close()
        board.close()
        gh.close()


def cmd_conflict(args: argparse.Namespace) -> int:
    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db)
    store = Store(settings.coord_db)
    try:
        claims = store.claims()
        snapshot = store.last_snapshot()
        report = conflict_mod.detect(
            main_changed=args.changed or [],
            claims=claims,
            reservations=store.reservations(),
            snapshot_origin_main=snapshot.get("origin_main") if snapshot else None,
            live_origin_main=args.live_main,
            self_task_id=args.task,
        )
        if args.gather:
            gathered = conflict_mod.gather_claims(args.repo, args.live_main or "origin/main")
            report["gathered_claims"] = gathered
        _emit(report)
        return 0 if report["decision"] == "allow" else 20
    finally:
        store.close()


def cmd_bind(args: argparse.Namespace) -> int:
    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db)
    store = Store(settings.coord_db)
    try:
        link = links_mod.bind(
            store, settings.repo, args.issue, settings.board, args.task,
            force=args.force, owner=args.owner, branch=args.branch,
            pr_number=args.pr, status=args.status,
            changed_paths=args.path or None,
        )
        _emit(link)
        return 0
    except links_mod.LinkConflict as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 23
    finally:
        store.close()


def cmd_unbind(args: argparse.Namespace) -> int:
    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db)
    store = Store(settings.coord_db)
    try:
        _emit({"removed": links_mod.unbind(store, settings.repo, args.issue)})
        return 0
    finally:
        store.close()


def cmd_reconcile(args: argparse.Namespace) -> int:
    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    store, board, gh = _context(settings, with_github=not args.no_github)
    from .ingest import _is_pull

    linked = {l["task_id"] for l in links_mod.all_links(store)}
    linked_issues = {int(l["issue_number"]) for l in links_mod.all_links(store)}
    unlinked_cards = [t["id"] for t in board.tasks() if t["id"] not in linked]
    result: dict[str, Any] = {
        "linked": sorted(linked),
        "unlinked_cards": unlinked_cards,
        "unlinked_issues": [],
    }
    if gh is not None:
        try:
            issues = gh.list_issues(state="open").data or []
            result["unlinked_issues"] = sorted(
                i["number"] for i in issues
                if not _is_pull(i) and i["number"] not in linked_issues
            )
        except Exception as exc:  # noqa: BLE001
            result["github_error"] = str(exc)
    _emit(result)
    store.close()
    board.close()
    if gh:
        gh.close()
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    from .publish import Publisher

    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    store, board, gh = _context(settings)
    assert gh is not None
    try:
        _emit(Publisher(store, gh, board, settings).close_if_confirmed(args.issue))
        return 0
    finally:
        store.close()
        board.close()
        gh.close()


def cmd_trail(args: argparse.Namespace) -> int:
    settings = Settings.from_env(coord_db=args.db)
    store = Store(settings.coord_db)
    try:
        _emit(observability.delivery_trail(store, args.event_id))
        return 0
    finally:
        store.close()


def cmd_reserve(args: argparse.Namespace) -> int:
    settings = Settings.from_env(coord_db=args.db)
    store = Store(settings.coord_db)
    try:
        store.reserve(args.scope, issue_number=args.issue, task_id=args.task, reason=args.reason)
        _emit({"reserved": args.scope})
        return 0
    finally:
        store.close()


def cmd_dedupe(args: argparse.Namespace) -> int:
    """Remove duplicate GitHub->Kanban ingest comments from a card."""
    from .kanban import KanbanBoard

    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    board = KanbanBoard(settings.kanban_db, author=settings.author)
    try:
        _emit(board.dedupe_ingest_comments(args.task, keep="none" if args.all else "first"))
        return 0
    finally:
        board.close()


def cmd_sync(args: argparse.Namespace) -> int:
    from .ingest import Ingestor
    from .publish import Publisher

    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    store, board, gh = _context(settings)
    assert gh is not None
    try:
        if args.dry_run:
            _emit({"dry_run": True,
                   "status": observability.status(store, board),
                   "conflicts": conflict_mod.detect(
                       main_changed=[], claims=store.claims(),
                       reservations=store.reservations())})
            return 0
        ingestor = Ingestor(store, gh, board, settings)
        result: dict[str, Any] = {}
        if not args.skip_ingest:
            result["issues"] = ingestor.ingest_issues(full=args.full)
            result["pulls"] = ingestor.ingest_pulls(full=args.full)
        if not args.skip_publish:
            result["publish"] = Publisher(store, gh, board, settings).publish_pending()
        _emit(result)
        return 0
    finally:
        store.close()
        board.close()
        gh.close()


def cmd_webhook(args: argparse.Namespace) -> int:
    from .ingest import Ingestor
    from .webhook import WebhookReceiver, run_server

    settings = Settings.from_env(repo=args.repo, board=args.board, coord_db=args.db,
                                 kanban_db=args.kanban_db)
    if not args.secret:
        print(json.dumps({"error": "GKS_WEBHOOK_SECRET / --secret required"}), file=sys.stderr)
        return 2
    store, board, gh = _context(settings)
    receiver = WebhookReceiver(store, Ingestor(store, gh, board, settings), args.secret, settings)
    print(f"listening on {args.host}:{args.port}")
    run_server(args.host, args.port, receiver)  # pragma: no cover
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="github-kanban-sync", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--repo")
        p.add_argument("--board")
        p.add_argument("--db")
        p.add_argument("--kanban-db")

    p = sub.add_parser("status"); common(p); p.set_defaults(func=cmd_status)
    p = sub.add_parser("health"); common(p); p.add_argument("--max-lag", type=float, default=600.0)
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("ingest"); common(p)
    p.add_argument("--issues", action="store_true"); p.add_argument("--pulls", action="store_true")
    p.add_argument("--all", action="store_true"); p.add_argument("--full", action="store_true")
    p.add_argument("--issue", type=int, action="append"); p.add_argument("--ci")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("publish"); common(p)
    p.add_argument("--task"); p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("conflict"); common(p)
    p.add_argument("--changed", action="append"); p.add_argument("--live-main")
    p.add_argument("--task"); p.add_argument("--gather", action="store_true")
    p.set_defaults(func=cmd_conflict)

    p = sub.add_parser("bind"); common(p)
    p.add_argument("--issue", type=int, required=True); p.add_argument("--task", required=True)
    p.add_argument("--owner"); p.add_argument("--branch"); p.add_argument("--pr", type=int)
    p.add_argument("--status"); p.add_argument("--path", action="append")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_bind)

    p = sub.add_parser("unbind"); common(p); p.add_argument("--issue", type=int, required=True)
    p.set_defaults(func=cmd_unbind)

    p = sub.add_parser("reconcile"); common(p); p.add_argument("--no-github", action="store_true")
    p.set_defaults(func=cmd_reconcile)

    p = sub.add_parser("close"); common(p); p.add_argument("--issue", type=int, required=True)
    p.set_defaults(func=cmd_close)

    p = sub.add_parser("trail"); common(p); p.add_argument("--event-id", required=True)
    p.set_defaults(func=cmd_trail)

    p = sub.add_parser("reserve"); common(p); p.add_argument("--scope", required=True)
    p.add_argument("--issue", type=int); p.add_argument("--task"); p.add_argument("--reason")
    p.set_defaults(func=cmd_reserve)

    p = sub.add_parser("dedupe"); common(p)
    p.add_argument("--task", required=True)
    p.add_argument("--all", action="store_true",
                   help="remove every ingest comment on the card (clean re-delivery)")
    p.set_defaults(func=cmd_dedupe)

    p = sub.add_parser("sync"); common(p)
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--full", action="store_true")
    p.add_argument("--skip-ingest", action="store_true"); p.add_argument("--skip-publish", action="store_true")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("webhook-serve"); common(p)
    p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8765)
    p.add_argument("--secret")
    p.set_defaults(func=cmd_webhook)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary: fail visible, exit 2
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
