"""Deterministic collection of local + GitHub project state (no LLM)."""
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone

from . import config as C

# Statuses that are "open" in kanban ordering.
OPEN_STATUSES = ["triage", "todo", "scheduled", "ready", "running", "blocked", "review"]
ALL_STATUSES = OPEN_STATUSES + ["done", "archived"]


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sh(args, cwd=None, timeout=90):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def _q(db, sql, params=()):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def board_db_paths():
    out = []
    if C.KANBAN_TOP.exists():
        out.append(("default", str(C.KANBAN_TOP)))
    if C.KANBAN_BOARDS_DIR.exists():
        for d in sorted(C.KANBAN_BOARDS_DIR.iterdir()):
            if d.is_dir() and d.name != "_archived":
                db = d / "kanban.db"
                if db.exists():
                    out.append((d.name, str(db)))
    return out


def collect_kanban():
    boards, all_tasks = [], []
    counts_total = {}
    runs_total = {"rate_limited": 0, "spawn_failed": 0, "total": 0}
    for name, db in board_db_paths():
        try:
            tasks = _q(
                db,
                "SELECT id,title,status,assignee,priority,consecutive_failures,"
                "last_failure_error,workspace_kind,workspace_path,branch_name,"
                "worker_pid,created_at,completed_at FROM tasks",
            )
            counts = {}
            for t in tasks:
                t["board"] = name
                counts[t["status"]] = counts.get(t["status"], 0) + 1
            all_tasks += tasks
            for k, v in counts.items():
                counts_total[k] = counts_total.get(k, 0) + v
            rmap = {
                r["outcome"] or "none": r["c"]
                for r in _q(db, "SELECT outcome, COUNT(*) c FROM task_runs GROUP BY outcome")
            }
            runs_total["rate_limited"] += rmap.get("rate_limited", 0)
            runs_total["spawn_failed"] += rmap.get("spawn_failed", 0)
            runs_total["total"] += sum(rmap.values())
            boards.append({"name": name, "db": db, "counts": counts, "tasks": len(tasks)})
        except Exception as e:  # noqa: BLE001
            boards.append({"name": name, "db": db, "error": str(e)})
    return boards, all_tasks, counts_total, runs_total


def collect_git():
    info = {"state": "UNAVAILABLE"}
    rc, out, _ = _sh(["git", "-C", str(C.REPO), "rev-parse", "origin/main"])
    info["repo_main_sha"] = out.strip() if rc == 0 else "UNKNOWN"
    rc, out, _ = _sh(["git", "-C", str(C.REPO), "rev-parse", "--short", "HEAD"])
    info["local_head_sha"] = out.strip() if rc == 0 else "UNKNOWN"
    rc, out, _ = _sh(["git", "-C", str(C.REPO), "branch", "--show-current"])
    info["local_branch"] = out.strip() if rc == 0 else "UNKNOWN"
    rc, out, _ = _sh(["git", "-C", str(C.REPO), "ls-remote", "origin", f"refs/heads/{C.BRANCH}"])
    info["contact_branch_sha"] = out.split()[0] if rc == 0 and out.strip() else "UNKNOWN"
    rc, out, _ = _sh(["git", "-C", str(C.REPO), "worktree", "list", "--porcelain"])
    wts = []
    if rc == 0:
        cur = {}
        for line in out.splitlines():
            if line.startswith("worktree "):
                if cur:
                    wts.append(cur)
                cur = {"path": line.split(" ", 1)[1]}
            elif line.startswith("branch "):
                cur["branch"] = line.split(" ", 1)[1].replace("refs/heads/", "")
            elif line.startswith("HEAD "):
                cur["head"] = line.split(" ", 1)[1][:10]
            elif line.startswith("detached"):
                cur["branch"] = "(detached)"
        if cur:
            wts.append(cur)
    info["worktrees"] = wts
    info["state"] = "VERIFIED" if info["repo_main_sha"] != "UNKNOWN" else "PARTIAL"
    return info


def collect_workers():
    rc, out, _ = _sh(["ps", "-eo", "pid,etimes,args"])
    if rc != 0:
        return {"count": "UNKNOWN", "list": []}
    workers = []
    for line in out.splitlines():
        if "hermes_cli.main" in line and "--cli" in line:
            m = re.search(r"-p\s+(\S+)", line)
            parts = line.split(None, 2)
            workers.append(
                {"pid": parts[0], "elapsed_s": parts[1], "profile": m.group(1) if m else "?"}
            )
    return {"count": len(workers), "list": workers}


def collect_gateway():
    if not C.GATEWAY_LOG.exists():
        return {"state": "UNAVAILABLE", "spawn_lines": None, "reaped_lines": None, "paused": None}
    try:
        with open(C.GATEWAY_LOG, errors="replace") as f:
            data = f.read()
    except OSError as e:  # noqa: BLE001
        return {"state": "UNAVAILABLE", "error": str(e)}
    return {
        "state": "VERIFIED",
        "spawn_lines": len(re.findall(r"spawned=", data)),
        "reaped_lines": len(re.findall(r"reaped", data)),
        "paused": "dispatch paused by global emergency stop" in data,
        "size": len(data),
    }


def collect_ci():
    rc, out, err = _sh(
        ["gh", "run", "list", "-R", C.GITHUB_REPO, "-L", "20",
         "--json", "databaseId,status,conclusion,headBranch,url,createdAt,workflowName"],
        timeout=60,
    )
    if rc != 0 or not out.strip():
        return {"state": "UNAVAILABLE", "error": (err or "gh failed")[:200]}
    try:
        runs = json.loads(out)
    except ValueError:
        return {"state": "UNAVAILABLE", "error": "bad json"}
    latest = runs[0] if runs else None
    # Prefer the latest run on `main`: our own pushes to the contact branch start
    # CI runs whose changing id would otherwise re-trigger a publish every pass.
    latest_main = next((r for r in runs if r.get("headBranch") == "main"), None)
    return {"state": "VERIFIED", "runs": runs, "latest": latest, "latest_main": latest_main}


def collect_provider():
    """Active provider profiles WITHOUT secrets (names only)."""
    cfg = C.HERMES_ROOT / "config.yaml"
    profiles = []
    try:
        text = cfg.read_text(errors="replace")
        m = re.search(r"^model:\s*\n(?:.*\n)*?\s+provider:\s*(\S+)", text, re.M)
        if m:
            profiles.append(m.group(1))
    except OSError:
        pass
    for p in sorted((C.HERMES_ROOT / "profiles").glob("*/config.yaml")):
        try:
            t = p.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"provider:\s*(\S+)", t)
        if m:
            profiles.append(f"{p.parent.name}:{m.group(1).strip('\"')}")
    return sorted(set(profiles))


def collect_all(con):
    boards, all_tasks, counts, runs = collect_kanban()
    git = collect_git()
    workers = collect_workers()
    gw = collect_gateway()
    ci = collect_ci()
    providers = collect_provider()

    # deltas vs previous totals (stored in kv)
    prev_rl = int(_get(con, "total_rate_limited", "0") or 0)
    prev_sf = int(_get(con, "total_spawn_failed", "0") or 0)
    rl_since = runs["rate_limited"] - prev_rl
    sf_since = runs["spawn_failed"] - prev_sf

    prev_taskmap = json.loads(_get(con, "task_status_map", "{}") or "{}")
    cur_taskmap = {f'{t["board"]}:{t["id"]}': t["status"] for t in all_tasks}
    changes = []
    for k, st in cur_taskmap.items():
        old = prev_taskmap.get(k)
        if old is not None and old != st:
            board, tid = k.split(":", 1)
            changes.append({"board": board, "task": tid, "old": old, "new": st})

    return {
        "collected_at": iso(utcnow()),
        "boards": boards,
        "tasks": all_tasks,
        "counts": counts,
        "runs": runs,
        "rate_limited_since": rl_since,
        "spawn_failed_since": sf_since,
        "git": git,
        "workers": workers,
        "gateway": gw,
        "ci": ci,
        "providers": providers,
        "changes": changes,
        "prev_taskmap": prev_taskmap,
        "cur_taskmap": cur_taskmap,
    }


def _get(con, key, default):
    from . import store
    return store.get_kv(con, key, default)
