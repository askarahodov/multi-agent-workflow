"""Reliable publication of coordinator-owned files to origin/coord/external-qa.

Guarantees: single writer (lock w/ stale recovery), fresh temp worktree from the
latest fetched remote, only coordinator-owned files are committed, secrets are
sanitized, push is never forced, and success is asserted against the REMOTE
(a local commit alone is NOT success).
"""
import json
import os
import re
import shutil
import subprocess
import time

from . import config as C

_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:OPENROUTER|OPENAI|ANTHROPIC|HERMESONE|GITHUB|GH)_[A-Z_]*KEY\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED-PRIVATE-KEY]"),
    (re.compile(r"(?i)(client_secret\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
]


class Busy(RuntimeError):
    """Another sync holds the lock."""


def sanitize(text):
    for pat, rep in _SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


def _git(args, cwd, timeout=180):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout)


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def acquire_lock():
    C.SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    if C.LOCK_FILE.exists():
        try:
            data = json.loads(C.LOCK_FILE.read_text())
        except (OSError, ValueError):
            data = {}
        pid = data.get("pid")
        age = time.time() - float(data.get("ts", 0))
        if pid and _pid_alive(pid) and age < C.LOCK_TTL_SECONDS:
            raise Busy(f"lock held by pid {pid} ({int(age)}s)")
        # stale (dead pid or expired ttl) -> remove and steal
        try:
            C.LOCK_FILE.unlink()
        except OSError:
            pass
    fd = os.open(str(C.LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode())
    os.close(fd)


def release_lock():
    try:
        C.LOCK_FILE.unlink()
    except OSError:
        pass


def _remove_worktree():
    if C.PUBLISH_WT.exists():
        _git(["worktree", "remove", "-f", str(C.PUBLISH_WT)], C.REPO)
        if C.PUBLISH_WT.exists():
            shutil.rmtree(C.PUBLISH_WT, ignore_errors=True)
    _git(["worktree", "prune"], C.REPO)


def fresh_worktree():
    """Create a detached worktree at PUBLISH_WT from the freshly fetched remote."""
    _remove_worktree()
    C.PUBLISH_WT.parent.mkdir(parents=True, exist_ok=True)
    r = _git(["fetch", "origin", C.BRANCH], C.REPO, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"fetch failed: {r.stderr.strip()[:200]}")
    r = _git(["worktree", "add", "--detach", str(C.PUBLISH_WT), f"origin/{C.BRANCH}"], C.REPO)
    if r.returncode != 0:
        raise RuntimeError(f"worktree add failed: {r.stderr.strip()[:200]}")


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _remote_head_sha():
    r = subprocess.run(["git", "-C", str(C.REPO), "ls-remote", "origin", f"refs/heads/{C.BRANCH}"],
                       capture_output=True, text=True, timeout=90)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split()[0]


def publish(*, status_body, append_requests, sync_files=None, snapshot_id,
            verify_markers, commit_msg, dry_run=False, attempts=None):
    """Publish coordinator-owned files. Returns a result dict.

    status_body: full status/current.md content
    append_requests: list of coordinator entry texts appended to requests.md (deduped by heading)
    sync_files: {repo_rel_path: content} extra coordinator-owned files (e.g. sync code)
    verify_markers: list of (repo_rel_path, substring) asserted on the REMOTE after push
    """
    attempts = attempts or C.PUSH_RETRIES
    result = {"state": "UNKNOWN", "attempts": 0, "remote_sha": None}
    acquire_lock()
    try:
        for attempt in range(1, attempts + 1):
            result["attempts"] = attempt
            fresh_worktree()
            contact = C.PUBLISH_WT / C.CONTACT_REL
            changed = []

            # status/current.md
            if _write(contact / "status" / "current.md", sanitize(status_body)):
                changed.append(f"{C.CONTACT_REL}/status/current.md")

            # requests.md: layer append entries on the fresh remote copy
            req_path = contact / "requests.md"
            base = req_path.read_text(encoding="utf-8") if req_path.exists() else ""
            additions = [sanitize(e) for e in append_requests
                         if e.splitlines() and e.splitlines()[0].strip() not in base]
            if additions:
                new_req = base.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"
                if _write(req_path, new_req):
                    changed.append(f"{C.CONTACT_REL}/requests.md")

            # extra coordinator-owned files (sync code)
            for rel, content in (sync_files or {}).items():
                if _write(C.PUBLISH_WT / rel, sanitize(content)):
                    changed.append(rel)

            if not changed:
                result["state"] = "NOCHANGE"
                return result

            result["changed"] = changed
            if dry_run:
                result["state"] = "DRY_RUN"
                return result

            _git(["add", "--", *changed], C.PUBLISH_WT)
            r = _git(["-c", f"user.name={C.GIT_NAME}", "-c", f"user.email={C.GIT_EMAIL}",
                      "commit", "-m", commit_msg], C.PUBLISH_WT)
            if r.returncode != 0:
                result["state"] = "COMMIT_FAILED"
                result["error"] = r.stderr.strip()[:300]
                return result

            push = _git(["push", "origin", f"HEAD:refs/heads/{C.BRANCH}"], C.PUBLISH_WT, timeout=180)
            if push.returncode != 0:
                # non-fast-forward / transient: refetch and replay on next loop
                result["last_push_error"] = push.stderr.strip()[:200]
                time.sleep(1)
                continue

            # --- verify against the REMOTE ---
            sha = _remote_head_sha()
            _git(["fetch", "origin", C.BRANCH], C.REPO)
            ok = True
            missing = []
            for rel, needle in verify_markers:
                show = _git(["show", f"origin/{C.BRANCH}:{rel}"], C.REPO)
                if show.returncode != 0 or needle not in show.stdout:
                    ok = False
                    missing.append(rel)
            result["remote_sha"] = sha
            if ok and sha:
                result["state"] = "PUBLISHED"
                return result
            result["state"] = "PUBLISH_FAILED"
            result["missing_markers"] = missing
            return result
        result["state"] = "PUBLISH_FAILED"
        return result
    finally:
        release_lock()
        _remove_worktree()
