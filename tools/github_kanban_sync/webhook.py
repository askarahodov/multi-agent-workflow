"""Optional webhook accelerator: signature verification + receiver (Issue #192 §2/§5).

The poll is authoritative; a webhook only *accelerates* it. Two rules make that
safe:

1. **Signature first** — ``X-Hub-Signature-256`` must verify (HMAC-SHA256, shared
   secret, constant-time compare) before the body is parsed. A bad/absent
   signature is rejected without side effects.
2. **Same dedup key** — the webhook reduces to the *same* ``source_event_id`` as
   the poll, so a change seen by both is delivered exactly once.

The receiver is transport-agnostic: :meth:`WebhookReceiver.handle` takes raw
headers + body bytes and can be mounted on any server (a stdlib fallback is
provided for local use). No public ingress is required for the sync to work.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping, Optional

from . import links as links_mod
from .config import Settings
from .store import Store

SIGNATURE_HEADER = "x-hub-signature-256"
EVENT_HEADER = "x-github-event"


class WebhookRejected(RuntimeError):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def verify_signature(secret: str, body: bytes, header: Optional[str],
                     algo: str = "sha256") -> bool:
    """Constant-time verify of a GitHub webhook signature header.

    ``header`` is the raw ``X-Hub-Signature-256`` value (``sha256=<hex>``).
    """
    if not secret or not header:
        return False
    prefix = f"{algo}="
    if not header.startswith(prefix):
        return False
    expected = hmac.new(secret.encode(), body, getattr(hashlib, algo)).hexdigest()
    return hmac.compare_digest(prefix + expected, header)


def normalize_webhook(event_name: str, payload: dict[str, Any], repo: str) -> Optional[dict[str, Any]]:
    """Reduce a GitHub webhook payload to the canonical event, or ``None``."""
    if event_name == "push":
        after = payload.get("after")
        if not after:
            return None
        eid = links_mod.source_event_id(repo, "push", after[:9], after)
        return {"source_event_id": eid, "kind": "push",
                "payload": {"after": after, "ref": payload.get("ref")},
                "repo_sha": after}
    if event_name == "issues":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        if number is None:
            return None
        action = payload.get("action", "edited")
        eid = links_mod.source_event_id(repo, "issue", number,
                                        f"webhook:{action}:{issue.get('updated_at')}")
        return {"source_event_id": eid, "kind": "issue",
                "payload": {"action": action, "number": number, "title": issue.get("title"),
                            "state": issue.get("state"), "url": issue.get("html_url"),
                            "source": "webhook"},
                "repo_sha": None}
    if event_name == "issue_comment":
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        number = issue.get("number")
        cid = comment.get("id")
        if number is None or cid is None:
            return None
        eid = links_mod.source_event_id(repo, "issue_comment", number, cid)
        body = comment.get("body") or ""
        from .ingest import HANDOFF_RE, is_sync_authored

        if is_sync_authored(body):
            return None
        handoff = bool(HANDOFF_RE.search(body))
        return {"source_event_id": eid, "kind": "handoff" if handoff else "issue_comment",
                "payload": {"issue": number, "comment_id": cid,
                            "author": (comment.get("user") or {}).get("login"),
                            "body": body[:2000], "url": comment.get("html_url"),
                            "handoff": handoff, "source": "webhook"},
                "repo_sha": None}
    if event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
        if number is None:
            return None
        merged = bool(pr.get("merged"))
        action = "merged" if merged else payload.get("action", "updated")
        eid = links_mod.source_event_id(repo, "pr", number, f"webhook:{action}:{pr.get('updated_at')}")
        return {"source_event_id": eid, "kind": "pr",
                "payload": {"action": action, "number": number, "title": pr.get("title"),
                            "state": pr.get("state"), "merged": merged,
                            "head": (pr.get("head") or {}).get("sha"),
                            "branch": (pr.get("head") or {}).get("ref"),
                            "source": "webhook"},
                "repo_sha": pr.get("merge_commit_sha")}
    if event_name in ("workflow_run", "check_suite"):
        run = payload.get("workflow_run") or payload.get("check_suite") or {}
        head = run.get("head_sha")
        if not head:
            return None
        eid = links_mod.source_event_id(repo, "ci", head[:9], f"webhook:{run.get('id')}")
        return {"source_event_id": eid, "kind": "ci",
                "payload": {"sha": head, "state": run.get("conclusion") or run.get("status"),
                            "source": "webhook"},
                "repo_sha": head}
    return None


class WebhookReceiver:
    def __init__(self, store: Store, ingestor, secret: str, settings: Settings):
        self.store = store
        self.ingestor = ingestor
        self.secret = secret
        self.settings = settings

    def handle(self, headers: Mapping[str, str], body: bytes) -> dict[str, Any]:
        lowered = {k.lower(): v for k, v in headers.items()}
        signature = lowered.get(SIGNATURE_HEADER)
        if not verify_signature(self.secret, body, signature):
            raise WebhookRejected("invalid or missing signature", status=401)
        event_name = lowered.get(EVENT_HEADER, "")
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookRejected(f"invalid JSON: {exc}", status=400) from exc

        normalized = normalize_webhook(event_name, payload, self.settings.repo)
        if normalized is None:
            return {"status": "ignored", "event": event_name, "reason": "not mirrorable"}
        is_new = self.store.record_event(
            normalized["source_event_id"], normalized["kind"], normalized["payload"],
            repo_sha=normalized.get("repo_sha"), correlation_id=f"webhook:{event_name}",
        )
        if not is_new:
            self.store.record_delivery(
                normalized["source_event_id"], "webhook", "duplicate",
                detail="already seen by poll or an earlier webhook",
            )
            return {"status": "duplicate", "event": event_name,
                    "source_event_id": normalized["source_event_id"]}
        outcome = self.ingestor.deliver(normalized["source_event_id"])
        return {"status": "accepted", "event": event_name, "outcome": outcome,
                "source_event_id": normalized["source_event_id"]}


def run_server(host: str, port: int, receiver: WebhookReceiver) -> None:  # pragma: no cover
    """Tiny stdlib receiver for local/manual runs (not required by the poller)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length", 0) or 0)
            body = self.rfile.read(length)
            try:
                result = receiver.handle(dict(self.headers), body)
                code = 202
            except WebhookRejected as exc:
                result, code = {"error": str(exc)}, exc.status
            except Exception as exc:  # noqa: BLE001
                result, code = {"error": str(exc)}, 500
            data = json.dumps(result).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    HTTPServer((host, port), _Handler).serve_forever()
