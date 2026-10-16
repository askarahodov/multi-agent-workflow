"""Explicitly deployed trusted filesystem tool gateway for remote workers.

This service is NOT installed in the model process and NOT exposed by the
orchestration API by default. It must run next to the private orchestration
SQLite state, with a separately protected tool ledger and operator-provided
workspace. Only allowlisted filesystem read/write tools are supported.

The gateway is intentionally co-located SQLite-only: it is not a PostgreSQL
fence, not a general remote sandbox, and does not fence Git/shell/network I/O.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import stat
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from shared.attempt_fence import AttemptFenceDenied, TrustedSqliteAttemptFence

from .errors import ToolPolicyDenied
from .native_tool_dispatch import (
    NativeFilesystemDispatcher, _require_control_file_outside_workspace,
)
from .scoped_fs import ScopedFilesystemExecutor
from .trusted_git_worktree import TrustedGitWorktreeStore
from .tool_ledger import SqliteToolLedger

_ID = re.compile(r"[A-Za-z0-9-]{1,64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{40,128}\Z")
_IDENTITY_FIELDS = {"run_id", "task_id", "attempt_id", "agent_id", "lease_token"}
_REQUEST_FIELDS = _IDENTITY_FIELDS | {"event"}
_MAX_REQUEST_BYTES = 1_100_000


def _verify_protected_ancestors(path: str | os.PathLike[str]) -> None:
    """Refuse DB paths replaceable by an untrusted local principal.

    Every ancestor must be non-symlink and not group/other writable.
    A sticky world-writable ancestor (typically /tmp) is acceptable ONLY
    when its immediate child is a private 0700 directory owned by this
    service, which another uid cannot unlink/replace under sticky semantics.
    A DB directly inside /tmp is not accepted: SQLite sidecars are unsafe.
    Same-UID untrusted workers must be isolated by the deployment.
    """
    target = Path(path)
    if not target.is_absolute():
        raise ToolPolicyDenied("Trusted control path must be absolute")
    try:
        parents = list(reversed(target.parents))
        for index, parent in enumerate(parents):
            pst = os.lstat(parent)
            if not stat.S_ISDIR(pst.st_mode) or parent.is_symlink():
                raise ToolPolicyDenied("Trusted control ancestor invalid")
            if not (pst.st_mode & 0o022):
                continue
            # POSIX sticky dirs protect private service-owned subdirectories
            # from replacement by other uids, including when /tmp is shared.
            if index + 1 >= len(parents) or not pst.st_mode & stat.S_ISVTX:
                raise ToolPolicyDenied("Trusted control ancestor is writable")
            child = parents[index + 1]
            cst = os.lstat(child)
            if (
                not stat.S_ISDIR(cst.st_mode)
                or child.is_symlink()
                or cst.st_mode & 0o077
                or (hasattr(os, "geteuid") and cst.st_uid != os.geteuid())
            ):
                raise ToolPolicyDenied("Trusted control ancestor is writable")
    except OSError as exc:
        raise ToolPolicyDenied("Trusted control directory unavailable") from exc


def build_trusted_filesystem_gateway(
    *,
    workspace_root: str,
    orchestration_database: str,
    ledger_database: str,
    gateway_key: str,
    git_store: TrustedGitWorktreeStore | None = None,
) -> FastAPI:
    """Build a separate, TLS-only privileged tool service (opt-in).

    Paths, API gateway credential and workspace policy come ONLY from trusted
    deployment settings. Never forward tool requests to a host where the
    untrusted runner can mutate these control-plane resources.
    """
    if (
        not isinstance(gateway_key, str)
        or not gateway_key.isascii()
        or not 32 <= len(gateway_key) <= 128
    ):
        raise ValueError("Dedicated gateway API key must be private ASCII (32-128)")
    root = Path(workspace_root).resolve(strict=True)
    permissions = {
        "fs_read": [str(root / "src" / "**")],
        "fs_write": [str(root / "out" / "**")],
    }
    filesystem = ScopedFilesystemExecutor(root, permissions)
    if git_store is not None:
        if not isinstance(git_store, TrustedGitWorktreeStore):
            raise TypeError("Trusted Git store must be operator-owned")
        for control_path in (git_store.repository, git_store.home):
            if (control_path == root or control_path.is_relative_to(root)
                    or root.is_relative_to(control_path)):
                raise ToolPolicyDenied("Trusted Git control paths must be separate from legacy workspace")
    _require_control_file_outside_workspace(
        orchestration_database, filesystem.root,
        "Orchestration state cannot live inside agent workspace",
    )
    _verify_protected_ancestors(orchestration_database)
    # The ledger MAY be absent on first boot. Check its *parent* and the
    # proposed target BEFORE creating it; the final strict file check runs
    # only after SqliteToolLedger creates the private regular file.
    ledger_target = Path(ledger_database)
    _verify_protected_ancestors(ledger_target)
    if (
        not ledger_target.is_absolute()
        or ledger_target.is_symlink()
        or any(part.is_symlink() for part in ledger_target.parents)
    ):
        raise ToolPolicyDenied("Trusted ledger path must be absolute without symlinks")
    try:
        parent = ledger_target.parent.resolve(strict=True)
        st = parent.stat()
        if (
            not parent.is_dir() or st.st_mode & 0o022
            or (hasattr(os, "geteuid") and st.st_uid != os.geteuid())
        ):
            raise ToolPolicyDenied("Trusted ledger directory must be private")
        if os.path.commonpath((str(parent), filesystem.root)) == filesystem.root:
            raise ToolPolicyDenied("Tool ledger cannot live inside agent workspace")
    except (OSError, ValueError) as exc:
        raise ToolPolicyDenied("Trusted ledger directory unavailable") from exc
    ledger = SqliteToolLedger(ledger_target)
    _require_control_file_outside_workspace(
        ledger.path, filesystem.root,
        "Tool ledger cannot live inside agent workspace",
    )

    # This factory does not register with orchestration-server's FastAPI app.
    # A deployment must explicitly start this separate application, configure
    # TLS and isolate its privileged filesystem/database credentials.
    app = FastAPI(
        title="Trusted Native Filesystem Gateway",
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    async def safe_error(status: int, code: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"ok": False, "content": "", "error_code": code},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/v1/filesystem/dispatch")
    async def dispatch(request: Request):
        # Reject raw HTTP and unauthenticated clients before parsing any
        # untrusted model content. No redirects or ambient proxy trust.
        if request.url.scheme != "https":
            return await safe_error(403, "SECURE_TRANSPORT_REQUIRED")
        supplied_key = request.headers.get("X-Gateway-Key")
        if (
            not isinstance(supplied_key, str)
            or not supplied_key.isascii()
            or not hmac.compare_digest(supplied_key, gateway_key)
        ):
            return await safe_error(401, "GATEWAY_UNAUTHORIZED")

        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > _MAX_REQUEST_BYTES:
                return await safe_error(413, "REQUEST_TOO_LARGE")
            chunks.append(chunk)
        try:
            body = json.loads(b"".join(chunks))
        except (ValueError, UnicodeDecodeError):
            return await safe_error(400, "INVALID_REQUEST")
        if not isinstance(body, dict) or set(body) != _REQUEST_FIELDS:
            return await safe_error(400, "INVALID_REQUEST")
        if any(
            not isinstance(body.get(key), str) or not _ID.fullmatch(body[key])
            for key in ("run_id", "task_id", "attempt_id", "agent_id")
        ):
            return await safe_error(400, "INVALID_REQUEST")
        if not isinstance(body.get("lease_token"), str) or not _TOKEN.fullmatch(
            body["lease_token"]
        ):
            return await safe_error(400, "INVALID_REQUEST")
        if not isinstance(body["event"], dict):
            return await safe_error(400, "INVALID_REQUEST")
        # The event itself is untrusted; dispatcher validates its exact shape,
        # arguments, model tool name, path allow-list and durable call ID.
        try:
            fence = TrustedSqliteAttemptFence(
                orchestration_database,
                run_id=body["run_id"], task_id=body["task_id"],
                attempt_id=body["attempt_id"], agent_id=body["agent_id"],
                lease_token=body["lease_token"], require_lease=True,
            )
            active_filesystem = filesystem
            if git_store is not None:
                task_root = git_store._path(body["task_id"], body["attempt_id"])
                if not task_root.is_dir() or task_root.is_symlink():
                    return await safe_error(409, "GIT_NOT_PROVISIONED")
                active_filesystem = ScopedFilesystemExecutor(task_root, {
                    "fs_read": [str(task_root / "src" / "**")],
                    "fs_write": [str(task_root / "out" / "**")],
                })
            worker_dispatch = NativeFilesystemDispatcher(
                active_filesystem, ledger=ledger,
                execution_scope=fence.execution_scope, attempt_fence=fence,
            )
            result = await asyncio.to_thread(worker_dispatch.dispatch, body["event"])
        except (AttemptFenceDenied, ToolPolicyDenied):
            return await safe_error(409, "ATTEMPT_FENCED")
        except Exception:
            # No raw SQL errors, filesystem paths, model arguments, auth data,
            # token or Python tracebacks must cross the trust boundary.
            return await safe_error(503, "TOOL_GATEWAY_UNAVAILABLE")
        return JSONResponse(
            status_code=200,
            content={
                "ok": result.ok,
                "content": result.content if result.ok else "",
                "error_code": result.error_code,
            },
            headers={"Cache-Control": "no-store"},
        )


    async def git_request(request: Request) -> tuple[dict, TrustedSqliteAttemptFence] | JSONResponse:
        """Server identity and lease, not LLM data, controls Git lifecycle."""
        if request.url.scheme != "https":
            return await safe_error(403, "SECURE_TRANSPORT_REQUIRED")
        supplied_key = request.headers.get("X-Gateway-Key")
        if (
            not isinstance(supplied_key, str) or not supplied_key.isascii()
            or not hmac.compare_digest(supplied_key, gateway_key)
        ):
            return await safe_error(401, "GATEWAY_UNAUTHORIZED")
        # A model does not receive this endpoint as a tool; accepting only an
        # exact bounded identity object avoids path/argv/commit injection.
        data = await request.body()
        if len(data) > 4096:
            return await safe_error(413, "REQUEST_TOO_LARGE")
        try:
            def no_duplicates(pairs):
                out = {}
                for k, v in pairs:
                    if k in out:
                        raise ValueError("Duplicate identity field")
                    out[k] = v
                return out
            body = json.loads(data, object_pairs_hook=no_duplicates)
        except (ValueError, UnicodeDecodeError):
            return await safe_error(400, "INVALID_REQUEST")
        if not isinstance(body, dict) or set(body) != _IDENTITY_FIELDS:
            return await safe_error(400, "INVALID_REQUEST")
        if any(type(body.get(key)) is not str or not _ID.fullmatch(body[key])
               for key in ("run_id", "task_id", "attempt_id", "agent_id")):
            return await safe_error(400, "INVALID_REQUEST")
        if type(body.get("lease_token")) is not str or not _TOKEN.fullmatch(body["lease_token"]):
            return await safe_error(400, "INVALID_REQUEST")
        try:
            fence = TrustedSqliteAttemptFence(
                orchestration_database,
                run_id=body["run_id"], task_id=body["task_id"],
                attempt_id=body["attempt_id"], agent_id=body["agent_id"],
                lease_token=body["lease_token"], require_lease=True,
            )
        except (AttemptFenceDenied, ToolPolicyDenied):
            return await safe_error(409, "ATTEMPT_FENCED")
        return body, fence

    @app.post("/v1/git/provision")
    async def provision_git(request: Request):
        if git_store is None:
            return await safe_error(404, "GIT_NOT_CONFIGURED")
        admitted = await git_request(request)
        if isinstance(admitted, JSONResponse):
            return admitted
        body, fence = admitted
        def provision():
            with fence.operation():
                git_store.provision(body["task_id"], body["attempt_id"])
        try:
            await asyncio.to_thread(provision)
        except (AttemptFenceDenied, ToolPolicyDenied):
            return await safe_error(409, "GIT_ATTEMPT_DENIED")
        except Exception:
            return await safe_error(503, "GIT_UNAVAILABLE")
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    @app.post("/v1/git/commit")
    async def commit_git(request: Request):
        if git_store is None:
            return await safe_error(404, "GIT_NOT_CONFIGURED")
        admitted = await git_request(request)
        if isinstance(admitted, JSONResponse):
            return admitted
        body, fence = admitted
        try:
            artifact = await asyncio.to_thread(
                git_store.commit, body["task_id"], body["attempt_id"],
                fence=fence, ledger=ledger,
            )
        except (AttemptFenceDenied, ToolPolicyDenied):
            return await safe_error(409, "GIT_ATTEMPT_DENIED")
        except Exception:
            return await safe_error(503, "GIT_UNAVAILABLE")
        return JSONResponse(
            {"ok": True, "commit_sha": artifact.commit_sha,
             "changed_paths": list(artifact.changed_paths)},
            headers={"Cache-Control": "no-store"},
        )

    return app


def trusted_gateway_from_env() -> FastAPI:
    """Explicit deployment factory; no default workspaces or insecure secrets.

    Example: uvicorn agent_management.trusted_fs_gateway:trusted_gateway_from_env
             --factory --host 127.0.0.1 --ssl-certfile ... --ssl-keyfile ...
    """
    workspace = os.environ.get("MAW_GATEWAY_WORKSPACE_ROOT")
    orchestration_db = os.environ.get("MAW_GATEWAY_ORCHESTRATION_SQLITE")
    ledger_db = os.environ.get("MAW_GATEWAY_LEDGER_SQLITE")
    secret_file = os.environ.get("MAW_GATEWAY_KEY_FILE")
    if not all((workspace, orchestration_db, ledger_db, secret_file)):
        raise ValueError("Trusted gateway deployment configuration is incomplete")
    secret_path = Path(secret_file)
    if (
        not secret_path.is_absolute()
        or secret_path.is_symlink()
        or any(parent.is_symlink() for parent in secret_path.parents)
    ):
        raise ValueError("Gateway secret must be an absolute non-symlink file")
    st = secret_path.stat()
    if (
        not stat.S_ISREG(st.st_mode)
        or st.st_mode & 0o077
        or st.st_nlink != 1
        or (hasattr(os, "geteuid") and st.st_uid != os.geteuid())
    ):
        raise ValueError("Gateway credential file must be private (0600)")
    # Never allow the model-writable workspace to hold auth material.
    _require_control_file_outside_workspace(
        secret_path, workspace, "Gateway secret cannot live inside workspace",
    )
    key = secret_path.read_text(encoding="ascii").strip()
    if not 32 <= len(key) <= 128:
        raise ValueError("Invalid dedicated gateway credential")
    git_mode = os.environ.get("MAW_GATEWAY_GIT_ENABLED")
    if git_mode not in (None, "", "0", "1"):
        raise ValueError("Invalid Git mode flag")
    git_store = None
    if git_mode == "1":
        repo = os.environ.get("MAW_GATEWAY_GIT_SOURCE_REPOSITORY")
        home = os.environ.get("MAW_GATEWAY_GIT_WORKTREE_HOME")
        binary = os.environ.get("MAW_GATEWAY_GIT_EXECUTABLE")
        if not all((repo, home, binary)):
            raise ValueError("Trusted Git mode requires explicit private paths")
        git_store = TrustedGitWorktreeStore(repo, home, git_executable=binary)
        for git_path in (git_store.repository, git_store.home):
            _verify_protected_ancestors(git_path)
    return build_trusted_filesystem_gateway(
        git_store=git_store,
        workspace_root=workspace,
        orchestration_database=orchestration_db,
        ledger_database=ledger_db,
        gateway_key=key,
    )
