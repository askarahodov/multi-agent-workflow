"""Render status/current.md from collected state. Deterministic.

The *substance* (everything except the volatile snapshot id / timestamps /
publish_state) is hashed so an unchanged project produces an unchanged hash and
the caller can skip the commit.
"""
import hashlib
import json
import re

from . import collect as _c

VOLATILE_KEYS = ("snapshot_id", "collected_at_utc", "publish_state")


def _fmt_ts(ts):
    if not ts:
        return "-"
    try:
        import time
        return time.strftime("%Y-%m-%d %H:%M MSK", time.localtime(int(ts)))
    except (ValueError, OSError):
        return str(ts)


def _source_status(state):
    st = state
    if st["git"]["state"] != "VERIFIED":
        return "PARTIAL"
    if state["ci"].get("state") != "VERIFIED":
        return "PARTIAL"
    return "VERIFIED"


def render(state, snapshot_id, publish_state="PENDING"):
    g = state["git"]
    counts = state["counts"]
    tk = {s: counts.get(s, 0) for s in _c.ALL_STATUSES}
    boards = [b["name"] for b in state["boards"] if "error" not in b]
    ci = state["ci"]
    ci_line = "UNKNOWN (gh unavailable)"
    if ci.get("state") == "VERIFIED" and ci.get("latest"):
        r = ci["latest"]
        ci_line = f"{r.get('workflowName','?')} #{r.get('databaseId')} " \
                  f"status={r.get('status')} conclusion={r.get('conclusion')} " \
                  f"branch={r.get('headBranch')} {r.get('url','')}".strip()

    head = {
        "snapshot_id": snapshot_id,
        "collected_at_utc": state["collected_at"],
        "source": "local-hermes-kanban+git+gateway+ci",
        "source_status": _source_status(state),
        "project": "multi-agent-workflow",
        "repo_main_sha": g.get("repo_main_sha", "UNKNOWN"),
        "local_branch": g.get("local_branch", "UNKNOWN"),
        "local_head_sha": g.get("local_head_sha", "UNKNOWN"),
        "contact_branch_sha": g.get("contact_branch_sha", "UNKNOWN"),
        "active_provider_profiles": state["providers"],
        "cost_budget": "UNKNOWN",
        "active_workers": f"{state['workers']['count']} running" if isinstance(state["workers"]["count"], int) else "UNKNOWN",
        "rate_limited_events_since_last": state["rate_limited_since"],
        "spawn_failures_since_last": state["spawn_failed_since"],
        "kanban_boards": boards,
        "task_counts": tk,
        "ci_latest": ci_line,
        "last_qa_response_processed": state.get("last_qa_response", "NONE"),
        "publish_state": publish_state,
    }

    lines = []
    # --- YAML head ---
    lines.append("```yaml")
    for k, v in head.items():
        if isinstance(v, (list, dict)):
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("```")
    lines.append("")

    # 1. changed since last snapshot
    lines.append("## 1. Изменилось с прошлого snapshot")
    if state["changes"]:
        for c in state["changes"]:
            lines.append(f"- `{c['task']}` ({c['board']}): {c['old']} → {c['new']}")
    else:
        lines.append("- (нет изменений статусов задач)")
    lines.append("")

    # 2. priority / dependency order
    lines.append("## 2. Текущий приоритет и dependency order")
    blocked = [t for t in state["tasks"] if t["status"] == "blocked"][:15]
    for t in blocked:
        lines.append(
            f"- BLOCKED `{t['task_id'] if 'task_id' in t else t['id']}` ({t['board']}): "
            f"{(t.get('last_failure_error') or 'no reason recorded')[:120]}"
        )
    if not blocked:
        lines.append("- Нет заблокированных задач.")
    lines.append("")

    # 3. active / recently changed
    lines.append("## 3. Активные и недавно изменённые задачи")
    lines.append("| task | board | status | owner | fails | last error | workspace |")
    lines.append("|---|---|---|---|---|---|---|")
    active = sorted(
        [t for t in state["tasks"] if t["status"] in ("running", "ready", "review", "blocked")],
        key=lambda t: (t["status"], t["board"], t["id"]),
    )
    for t in active[:40]:
        ws = t.get("workspace_path") or t.get("workspace_kind") or "-"
        err = (t.get("last_failure_error") or "")[:60].replace("|", "/")
        lines.append(
            f"| `{t['id']}` | {t['board']} | {t['status']} | {t.get('assignee') or '-'} | "
            f"{t.get('consecutive_failures', 0)} | {err} | {ws} |"
        )
    lines.append("")

    # 4. recently completed
    lines.append("## 4. Последние завершённые задачи")
    done = [t for t in state["tasks"] if t["status"] == "done" and t.get("completed_at")]
    done.sort(key=lambda t: t.get("completed_at") or 0, reverse=True)
    for t in done[:12]:
        lines.append(f"- `{t['id']}` ({t['board']}) — {t['title'][:70]} @ {_fmt_ts(t.get('completed_at'))}")
    if not done:
        lines.append("- (нет данных)")
    lines.append("")

    # 5. QA responses
    lines.append("## 5. QA-ответы")
    for r in state.get("qa_entries", []):
        lines.append(f"- `{r['id']}` → {r['disposition']} ({r.get('related') or 'n/a'})")
    if not state.get("qa_entries"):
        lines.append("- Обработанных в этом проходе нет.")
    lines.append("")

    # 6. risks / limits
    lines.append("## 6. Риски и известные ограничения")
    risks = []
    if state["gateway"].get("paused"):
        risks.append("Gemini/kanban dispatch PAUSED by global emergency stop (ESTOP).")
    if state["rate_limited_since"] > 0:
        risks.append(f"rate_limited events since last snapshot: {state['rate_limited_since']}")
    if state["spawn_failed_since"] > 0:
        risks.append(f"spawn_failed events since last snapshot: {state['spawn_failed_since']}")
    bad = [t for t in state["tasks"] if t.get("workspace_kind") == "dir" and not t.get("workspace_path")]
    if bad:
        risks.append(f"invalid dir-workspace tasks: {', '.join(t['id'] for t in bad[:5])}")
    if not risks:
        risks.append("(нет новых рисков)")
    lines += [f"- {r}" for r in risks]
    lines.append("")

    # 7. source availability
    lines.append("## 7. Отчёт о доступности источников")
    lines.append(f"- kanban: {'VERIFIED' if boards else 'UNAVAILABLE'}")
    lines.append(f"- git: {state['git']['state']}")
    lines.append(f"- gateway log: {state['gateway'].get('state')}")
    lines.append(f"- CI (gh): {state['ci'].get('state')}")
    lines.append(f"- worktrees: {len(state['git'].get('worktrees', []))} visible")
    lines.append("")

    body = "\n".join(lines)
    # substance = body with volatile values normalised out
    sub = body
    sub = re.sub(r"snapshot_id: \S+", "snapshot_id: <id>", sub)
    sub = re.sub(r"collected_at_utc: \S+", "collected_at_utc: <ts>", sub)
    sub = re.sub(r"publish_state: \S+", "publish_state: <st>", sub)
    # contact_branch_sha advances on our OWN publish; normalize so a push does not
    # itself look like a project change (would otherwise loop forever).
    sub = re.sub(r"contact_branch_sha: \S+", "contact_branch_sha: <sha>", sub)
    substance = hashlib.sha256(sub.encode("utf-8")).hexdigest()
    return body, substance
