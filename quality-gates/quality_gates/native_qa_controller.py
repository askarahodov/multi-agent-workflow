"""Bounded independent QA autopilot; never import/run this in a model worker."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import ssl
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from agent_management.trusted_git_worktree import TrustedGitWorktreeStore

import re
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_SHA = re.compile(r"[0-9a-f]{40,64}\Z")


class QaControllerError(RuntimeError):
    """Fail-closed error which must not contain secrets or model text."""


def trusted_origin(raw: str) -> str:
    u = urlsplit(raw)
    if (u.scheme != "https" or not u.hostname or u.username or u.password
            or u.query or u.fragment or u.path not in ("", "/")):
        raise ValueError("Independent QA requires a bare HTTPS origin")
    return raw.rstrip("/")


@dataclass(frozen=True, repr=False)
class QaControllerConfig:
    orch_url: str
    orch_admin_key: str
    qg_url: str
    qg_admin_key: str
    test_command: tuple[str, ...]
    orch_ca_file: str | None = None
    qg_ca_file: str | None = None
    max_runs: int = 20
    max_tasks: int = 50

    def __post_init__(self):
        trusted_origin(self.orch_url)
        trusted_origin(self.qg_url)
        for ca in (self.orch_ca_file, self.qg_ca_file):
            if ca is not None and (
                type(ca) is not str or not Path(ca).is_absolute()
                or Path(ca).is_symlink() or not Path(ca).is_file()
            ):
                raise ValueError("QA HTTPS CA must be an absolute regular file")
        if (not isinstance(self.orch_admin_key, str)
                or not isinstance(self.qg_admin_key, str)
                or len(self.orch_admin_key) < 8 or len(self.qg_admin_key) < 8
                or self.orch_admin_key == self.qg_admin_key):
            raise ValueError("QA/controller credentials must be separate")
        if (type(self.test_command) is not tuple or not self.test_command
                or len(self.test_command) > 16
                or any(type(s) is not str or not 1 <= len(s) <= 512 or "\0" in s
                       for s in self.test_command)):
            raise ValueError("Explicit bounded operator test argv required")
        if (type(self.max_runs) is not int or type(self.max_tasks) is not int
                or not 1 <= self.max_runs <= 100
                or not 1 <= self.max_tasks <= 200):
            raise ValueError("QA page limits invalid")

    def __repr__(self):
        return "QaControllerConfig(<redacted>)"


def require_scoped_gate_result(result, *, task_id: str, attempt_id: str,
                               commit_sha: str, gate: str) -> None:
    if (type(result) is not dict or result.get("status") != "passed"
            or result.get("task_id") != task_id
            or result.get("gate") != gate
            or result.get("attempt_id") != attempt_id
            or result.get("commit_sha") != commit_sha):
        raise QaControllerError("QA gate scope mismatch; downstream remains blocked")


def require_scoped_receipt(proof, *, task_id: str, attempt_id: str,
                           commit_sha: str) -> None:
    if (type(proof) is not dict or proof.get("task_id") != task_id
            or proof.get("attempt_id") != attempt_id
            or proof.get("commit_sha") != commit_sha):
        raise QaControllerError("QA receipt scope mismatch; registration denied")


class NativeQaController:
    """A separate operator-owned process. Only orchestration stores SDLC state."""

    def __init__(self, config: QaControllerConfig, *,
                 git_store: TrustedGitWorktreeStore,
                 orchestration_transport=None, qa_transport=None):
        self.config = config
        self.git_store = git_store
        orch_verify = (ssl.create_default_context(cafile=config.orch_ca_file)
                       if config.orch_ca_file else True)
        qg_verify = (ssl.create_default_context(cafile=config.qg_ca_file)
                     if config.qg_ca_file else True)
        self.orch = httpx.AsyncClient(
            base_url=trusted_origin(config.orch_url),
            headers={"X-API-Key": config.orch_admin_key}, trust_env=False,
            follow_redirects=False, timeout=15, verify=orch_verify,
            transport=orchestration_transport)
        self.qg = httpx.AsyncClient(
            base_url=trusted_origin(config.qg_url),
            headers={"X-API-Key": config.qg_admin_key}, trust_env=False,
            follow_redirects=False, timeout=660, verify=qg_verify,
            transport=qa_transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.orch.aclose()
        await self.qg.aclose()

    async def request(self, client, method, path, *, payload=None, params=None):
        try:
            response = await client.request(
                method, "/api/v1" + path, json=payload, params=params)
        except httpx.RequestError as exc:
            raise QaControllerError("Independent QA service unavailable") from exc
        if response.status_code != 200 or len(response.content) > 131072:
            raise QaControllerError("Independent QA API refused request")
        try:
            return response.json()
        except ValueError as exc:
            raise QaControllerError("Independent QA API response malformed") from exc

    async def run_once(self) -> str | None:
        """Process one unverified completed stage, then return its task id."""
        runs = await self.request(
            self.orch, "GET", "/workflows/runs",
            params={"status": "running", "limit": self.config.max_runs})
        if type(runs) is not dict or type(runs.get("items")) is not list:
            raise QaControllerError("Workflow discovery invalid")
        for run in runs["items"][:self.config.max_runs]:
            if type(run) is not dict or run.get("status") != "running":
                raise QaControllerError("Workflow status invalid")
            run_id = run.get("id")
            if type(run_id) is not str or not _UUID.fullmatch(run_id):
                raise QaControllerError("Workflow identity invalid")
            page = await self.request(
                self.orch, "GET", f"/workflows/runs/{run_id}/tasks",
                params={"limit": self.config.max_tasks})
            if type(page) is not dict or type(page.get("items")) is not list:
                raise QaControllerError("Task page invalid")
            for task in page["items"][:self.config.max_tasks]:
                if type(task) is not dict or task.get("status") != "completed":
                    continue
                task_id = task.get("id")
                if (task.get("workflow_run_id") != run_id
                        or type(task_id) is not str or not _UUID.fullmatch(task_id)):
                    raise QaControllerError("Cross-run QA task denied")
                status = await self.request(
                    self.orch, "GET", f"/tasks/{task_id}/qa-attestation")
                if type(status) is not dict or status.get("task_id") != task_id:
                    raise QaControllerError("QA status invalid")
                if status.get("status") == "verified":
                    continue
                if status.get("status") != "pending":
                    continue
                artifacts = await self.request(
                    self.orch, "GET", f"/tasks/{task_id}/git-evidence")
                if type(artifacts) is not list or len(artifacts) != 1:
                    raise QaControllerError("Native Git evidence missing/ambiguous")
                artifact = artifacts[0]
                if type(artifact) is not dict or artifact.get("task_id") != task_id:
                    raise QaControllerError("Native Git scope invalid")
                attempt_id = artifact.get("attempt_id")
                sha = artifact.get("commit_sha")
                paths = artifact.get("changed_paths")
                if (type(attempt_id) is not str or not _UUID.fullmatch(attempt_id)
                        or type(sha) is not str or not _SHA.fullmatch(sha)
                        or type(paths) is not list or not 1 <= len(paths) <= 64
                        or any(type(p) is not str for p in paths)):
                    raise QaControllerError("Native Git evidence malformed")
                try:
                    checked = await asyncio.to_thread(
                        self.git_store.verify_artifact,
                        task_id, attempt_id, expected_sha=sha,
                        expected_paths=tuple(paths))
                except Exception as exc:
                    raise QaControllerError("Trusted Git ref readback denied") from exc
                if checked.commit_sha != sha:
                    raise QaControllerError("Git SHA does not match")
                await self.attest(task_id, attempt_id, sha)
                return task_id
        return None

    async def attest(self, task_id: str, attempt_id: str, sha: str):
        # Never QA the model's old, writable worktree. The controller creates
        # a fresh detached checkout from a separately verified Git object.
        root = Path(tempfile.mkdtemp(prefix="maw-qa-", dir=self.git_store.home))
        checkout = root / "snapshot"
        attached = False
        try:
            try:
                await asyncio.to_thread(
                    self.git_store._git, self.git_store.repository,
                    "worktree", "add", "--detach", str(checkout), sha)
                attached = True
            except Exception as exc:
                raise QaControllerError("Trusted checkout failed") from exc
            for gate in ("tester", "reviewer", "security"):
                body = {"task_id": task_id, "attempt_id": attempt_id,
                        "commit_sha": sha, "workspace": str(checkout),
                        "gate": gate}
                if gate == "tester":
                    body["context"] = {
                        "commands": {"unit": list(self.config.test_command)}}
                result = await self.request(self.qg, "POST", "/runs", payload=body)
                require_scoped_gate_result(
                    result, task_id=task_id, attempt_id=attempt_id,
                    commit_sha=sha, gate=gate)
            proof = await self.request(
                self.qg, "POST", f"/tasks/{task_id}/qa-attestation",
                payload={"attempt_id": attempt_id, "commit_sha": sha})
            require_scoped_receipt(
                proof, task_id=task_id, attempt_id=attempt_id, commit_sha=sha)
            result = await self.request(
                self.orch, "POST", f"/tasks/{task_id}/qa-attestation",
                payload=proof)
            if (type(result) is not dict or result.get("status") != "verified"
                    or result.get("attempt_id") != attempt_id):
                raise QaControllerError("Orchestration QA registration denied")
            readback = await self.request(
                self.orch, "GET", f"/tasks/{task_id}/qa-attestation")
            if (type(readback) is not dict or readback.get("status") != "verified"
                    or readback.get("attempt_id") != attempt_id
                    or readback.get("commit_sha") != sha):
                raise QaControllerError("Orchestration QA readback mismatch")
        finally:
            if attached:
                try:
                    await asyncio.to_thread(
                        self.git_store._git, self.git_store.repository,
                        "worktree", "remove", "--force", str(checkout))
                except Exception as exc:
                    raise QaControllerError("QA worktree cleanup requires operator") from exc
            shutil.rmtree(root, ignore_errors=True)


def private_key(path: str) -> str:
    """Reject symlink, shared and hardlinked credentials before a bounded read."""
    p = Path(path)
    if not p.is_absolute() or any(i.is_symlink() for i in (p, *p.parents)):
        raise ValueError("Private operator key path invalid")
    st = os.lstat(p)
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_mode & 0o077
            or (hasattr(os, "geteuid") and st.st_uid != os.geteuid())):
        raise ValueError("Private operator key permissions invalid")
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fresh = os.fstat(fd)
        if (fresh.st_ino, fresh.st_dev) != (st.st_ino, st.st_dev):
            raise ValueError("Private operator key changed")
        data = os.read(fd, 257)
    finally:
        os.close(fd)
    if not 8 <= len(data) <= 256 or b"\n" in data or b"\r" in data:
        raise ValueError("Private operator key content invalid")
    return data.decode("ascii")


def controller_from_env():
    if os.environ.get("MAW_QA_CONTROLLER_ENABLED") != "1":
        raise ValueError("QA controller requires explicit opt-in")
    test_argv = json.loads(os.environ["MAW_QA_TEST_COMMAND_JSON"])
    if type(test_argv) is not list:
        raise ValueError("Trusted QA test argv must be JSON list")
    config = QaControllerConfig(
        orch_url=os.environ["MAW_QA_ORCH_URL"],
        orch_admin_key=private_key(os.environ["MAW_QA_ORCH_ADMIN_KEY_FILE"]),
        qg_url=os.environ["MAW_QA_SERVICE_URL"],
        qg_admin_key=private_key(os.environ["MAW_QA_SERVICE_ADMIN_KEY_FILE"]),
        test_command=tuple(test_argv),
        orch_ca_file=os.environ.get("MAW_QA_ORCH_CA_FILE"),
        qg_ca_file=os.environ.get("MAW_QA_SERVICE_CA_FILE"),
    )
    store = TrustedGitWorktreeStore(
        repository=os.environ["MAW_QA_GIT_REPOSITORY"],
        worktree_home=os.environ["MAW_QA_WORKTREE_HOME"],
        git_executable=os.environ["MAW_QA_GIT_EXECUTABLE"],
    )
    polls = int(os.environ["MAW_QA_MAX_POLLS"])
    interval = float(os.environ["MAW_QA_POLL_SECONDS"])
    if not 1 <= polls <= 1000 or not 0.01 <= interval <= 3600:
        raise ValueError("QA controller finite polling bounds invalid")
    return config, store, polls, interval


def autonomous_qa_limits(env: dict[str, str], test_command: tuple[str, ...]) -> tuple[int, int]:
    """Require explicit operator opt-in and a non-placeholder test command."""
    if env.get("MAW_QA_AUTONOMOUS_ENABLED") != "1":
        raise ValueError("Autonomous QA requires operator opt-in")
    if test_command == ("python", "-B", "-c", "raise SystemExit(1)"):
        raise ValueError("Autonomous QA requires real operator test command")
    try:
        polls = int(env.get("MAW_QA_AUTONOMOUS_MAX_POLLS", "100"))
        verified = int(env.get("MAW_QA_AUTONOMOUS_MAX_VERIFICATIONS", "7"))
    except (ValueError, OverflowError):
        raise ValueError("Autonomous QA budget malformed") from None
    if not 1 <= polls <= 1000 or not 1 <= verified <= 100:
        raise ValueError("Autonomous QA budget outside bounds")
    return polls, verified


async def run_autonomous_qa() -> int:
    """Finite self-starting QA loop; always fail closed on ambiguous results."""
    config, store, _, interval = controller_from_env()
    max_polls, max_verified = autonomous_qa_limits(dict(os.environ), config.test_command)
    verified = 0
    async with NativeQaController(config, git_store=store) as qa:
        for poll in range(max_polls):
            if poll:
                await asyncio.sleep(interval)
            result = await qa.run_once()
            if result is not None:
                verified += 1
                if verified >= max_verified:
                    break
    print("Autonomous QA stopped within explicit verification/poll budgets")
    return 0


async def run_controller() -> int:
    config, store, polls, interval = controller_from_env()
    async with NativeQaController(config, git_store=store) as qa:
        for n in range(polls):
            if n:
                await asyncio.sleep(interval)
            await qa.run_once()
    return 0


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="maw-native-qa")
    parser.add_argument("command", choices=("preflight", "run", "dispatch"))
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            controller_from_env()
            print("Native QA preflight OK (no execution performed)")
            return 0
        if args.command == "dispatch":
            return asyncio.run(run_autonomous_qa())
        return asyncio.run(run_controller())
    except (ValueError, OSError, QaControllerError, KeyError, TypeError, RuntimeError):
        print("Native QA FAIL_CLOSED; independent operator review required",
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
