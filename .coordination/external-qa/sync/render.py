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
    ci_line = "UNKNOWN (no CI run on main in window)"
    if ci.get("state") == "VERIFIED":
        r = ci.get("latest_main")
        if r:
            # No run id / url, and main branch only: our own contact-branch pushes
            # must not perturb the substance (would re-publish every pass).
            ci_line = f"{r.get('workflowName','?')} conclusion={r.get('conclusion')} branch=main"

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
    substance = hashlib.sha256(normalize(body).encode("utf-8")).hexdigest()
    return body, substance


def normalize(text):
    """Strip values that change on our OWN publish/collection so an unchanged
    project yields an unchanged hash (otherwise every push/pass re-triggers)."""
    sub = text
    sub = re.sub(r"snapshot_id: \S+", "snapshot_id: <id>", sub)
    sub = re.sub(r"collected_at_utc: \S+", "collected_at_utc: <ts>", sub)
    sub = re.sub(r"publish_state: \S+", "publish_state: <st>", sub)
    sub = re.sub(r"contact_branch_sha: \S+", "contact_branch_sha: <sha>", sub)
    # QA_DASHBOARD.md renders these as markdown table rows, not `key: value`.
    sub = re.sub(r"\|\s*snapshot_id\s*\|[^|]*\|", "| snapshot_id | <id> |", sub)
    sub = re.sub(r"\|\s*collected_at_utc\s*\|[^|]*\|", "| collected_at_utc | <ts> |", sub)
    sub = re.sub(r"\|\s*publish_state\s*\|[^|]*\|", "| publish_state | <st> |", sub)
    sub = re.sub(r"\|\s*contact_branch_sha\s*\|[^|]*\|", "| contact_branch_sha | <sha> |", sub)
    return sub


def render_dashboard(state, snapshot_id, publish_state="NONE", qa_verdicts=None, open_cases=None):
    """QA_DASHBOARD.md — русская читаемая сводка из ТОГО ЖЕ snapshot, что
    `status/current.md`, публикуется атомарно с ним.

    QA-статусы и Kanban-статусы разделены. Это панель, а не архив задач: полный
    history не загружается. Постоянный маркер `snapshot_id` сохранён для тестов.
    """
    counts = state["counts"]
    tk = {s: counts.get(s, 0) for s in _c.ALL_STATUSES}
    g = state["git"]
    estop = "ВКЛЮЧЁН (ESTOP)" if state["gateway"].get("paused") else "выключен"
    boards = [b["name"] for b in state["boards"] if "error" not in b]
    blocked = [t for t in state["tasks"] if t["status"] == "blocked"]
    active = [t for t in state["tasks"] if t["status"] in ("running", "ready", "review")]
    invalid_ws = [t["id"] for t in state["tasks"]
                  if t.get("workspace_kind") == "dir" and not t.get("workspace_path")]
    qa_verdicts = qa_verdicts or []
    open_cases = open_cases or []

    L = [
        "# Панель QA",
        "",
        "> Сгенерировано qa-sync из ТОГО ЖЕ snapshot, что `status/current.md`.",
        "> Публикуется атомарно с ним. Руками не редактировать.",
        "",
        "## Общая картина",
        "| поле | значение |",
        "|---|---|",
        f"| snapshot_id | {snapshot_id} |",
        f"| время сбора (UTC) | {state['collected_at']} |",
        f"| главная ветка (main) | {g.get('repo_main_sha', 'UNKNOWN')} |",
        f"| ветка обмена (coord/external-qa) | {g.get('contact_branch_sha', 'UNKNOWN')} |",
        f"| доски Kanban | {', '.join(boards) or 'недоступны'} |",
        f"| активных воркеров | {state['workers']['count']} |",
        f"| ESTOP | {estop} |",
        f"| последняя проверка CI (main) | {_ci_line(state)} |",
        "",
        "## Текущие риски",
    ]
    risks = []
    if state["gateway"].get("paused"):
        risks.append("kanban-dispatch приостановлен (ESTOP) — новый spawn не выполняется.")
    if state["rate_limited_since"] > 0:
        risks.append(f"событий rate_limited с прошлого snapshot: {state['rate_limited_since']}.")
    if state["spawn_failed_since"] > 0:
        risks.append(f"сбойных spawn с прошлого snapshot: {state['spawn_failed_since']}.")
    if invalid_ws:
        risks.append(f"невалидный dir-workspace: {', '.join(invalid_ws[:5])} (парковать).")
    if not risks:
        risks.append("новых рисков нет.")
    L += [f"- {r}" for r in risks]

    L += [
        "",
        "## Активные задачи (Kanban)",
        "| задача | доска | статус | исполнитель | попыток | последняя ошибка |",
        "|---|---|---|---|---|---|",
    ]
    for t in sorted(active, key=lambda x: (x["status"], x["id"]))[:25]:
        err = (t.get("last_failure_error") or "")[:60].replace("|", "/")
        L.append(f"| `{t['id']}` | {t['board']} | {t['status']} | {t.get('assignee') or '-'} | "
                 f"{t.get('consecutive_failures', 0)} | {err} |")
    if not active:
        L.append("| — | — | — | — | — | — |")
    L.append(f"- заблокировано: {len(blocked)}; "
             f"в т.ч. {', '.join('`'+t['id']+'`' for t in blocked[:6]) or 'нет'}")

    L += [
        "",
        "## Последние QA-вердикты (QA ≠ Kanban)",
        "| QA-ответ | вердикт |",
        "|---|---|",
    ]
    for rid, verdict in qa_verdicts[-8:]:
        L.append(f"| `{rid}` | {verdict or '—'} |")
    if not qa_verdicts:
        L.append("| — | — |")
    L.append(f"- открытых QA-кейсов: {len(open_cases)}")

    L += [
        "",
        "## task_counts",
        "```json",
        json.dumps(tk, ensure_ascii=False),
        "```",
        "",
        "## Следующий checkpoint",
        f"- индексированных новых запросов: см. `index/current.md`",
        f"- целью является независимая проверка REVIEW_REQUEST (diff + SHA + тесты).",
        "",
        "## Доказательства / время обновления",
        f"- источник: status/current.md @ {snapshot_id}",
        f"- ветка обмена: {g.get('contact_branch_sha', 'UNKNOWN')}",
        f"- publish_state: {publish_state}",
        f"- доступность источников: kanban={'OK' if boards else 'UNAVAILABLE'}, "
        f"git={g['state']}, gateway={state['gateway'].get('state')}, ci={state['ci'].get('state')}",
        "",
    ]
    return "\n".join(L)


def _ci_line(state):
    ci = state.get("ci", {})
    if ci.get("state") != "VERIFIED" or not ci.get("latest_main"):
        return "нет прогона на main в окне"
    r = ci["latest_main"]
    return f"{r.get('workflowName','?')} conclusion={r.get('conclusion')}"
