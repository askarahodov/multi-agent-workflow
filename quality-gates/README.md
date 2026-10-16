# Quality Gates

Automated quality-gate pipeline for the Harbor Transfer Portal agent platform:
Tester, Reviewer, Security and Release-Prep gates with auditable, checksummed
evidence and enforced Kanban-style transitions.

## Gates

| Gate        | What it checks                                                       |
| ----------- | ------------------------------------------------------------------- |
| `tester`    | Runs the workspace's own test command (e.g. `pytest`) and records the exit code and evidence. |
| `reviewer`  | Deterministic static style + architecture checks (manifests present, no tabs / long lines / trailing whitespace, no `TODO`/`FIXME`/`HACK` markers in production code). |
| `security`  | Dependency advisory scan + high-confidence secret detection (AWS/GitHub/Stripe/Slack/Google/private-key patterns). |
| `release_prep` | Builds a versioned, SHA-256-checksummed release artifact and records it as `awaiting_approval` (human gate). |

Gates are registered in `quality_gates/gates/base.py` via `GATE_REGISTRY` and
run by `GatePipeline` (`quality_gates/pipeline.py`), which persists each run and
its immutable, checksummed evidence to SQLite (or PostgreSQL) and refuses any
task transition unless every required gate has a passing run.

## Running the gates

```bash
pip install -e ".[dev]"
pytest            # unit tests (45 tests)
```

Run a single gate directly against a workspace:

```python
from quality_gates.gates.reviewer import ReviewerGate
from quality_gates.gates.security import SecurityGate

result = ReviewerGate().execute("/path/to/workspace")
print(result.passed, result.summary)
for f in result.findings:
    print(f.category, f.passed, f.summary)
```

Or run the full pipeline as a server:

```bash
python -m quality_gates.main --db sqlite+aiosqlite:///./quality_gates.db
```

## Scanning policy

All gates share one traversal helper (`quality_gates/gates/walk.py`) and one
skip set. Scans prune (never descend into) VCS metadata, virtualenvs
(`venv`/`.venv`), the pipeline's own verification scratch dirs (`.verify`,
`.qg-verify`), build/cache output, vendored code and any `*.egg-info` directory,
so a virtualenv anywhere in the scanned tree cannot poison results.

Secret fixtures used in the test suite are assembled from fragments at runtime
so that no literal secret-shaped string is committed to the repository — the
security gate does not flag its own test data.

## Граница доверия независимых QA gates

При `AUTH_ENABLED=true` только операторский `ADMIN_API_KEYS` имеет доступ
к `POST /api/v1/runs` (реальный запуск tester/reviewer/security),
`POST /api/v1/tasks/{task_id}/transition` (решение о переходе) и
`POST /api/v1/tasks/{task_id}/releases` (подготовка релиза).
`WRITE_API_KEYS` собственных AI worker **недостаточно** для выдачи себе
независимых QA evidence или запуска произвольной команды через
`tester.context.commands`. Операторы должны хранить QA ADMIN-ключ
отдельно от native worker и допускать тестовую конфигурацию только из
проверенных источников. Режим `AUTH_ENABLED=false` подходит для локальной
разработки, но не является доверенной QA-границей для SDLC-приёмки.

**Ограничение #11:** эта защита разграничивает права в подсистеме quality-gates,
но пока не вводит обязательную сверку QA evidence внутри
`orchestration-server` перед продвижением очередной SDLC-стадии.

## Evidence & release flow

- Every gate run stores `gate_runs` and immutable `evidence_items` rows; each
  evidence document is written to disk under `evidence_root` with an embedded
  SHA-256 checksum (`quality_gates/evidence.py`).
- `GatePipeline.transition` blocks any status advance until `required_gates` all
  have a passing run (`TransitionForbiddenError` otherwise).
- `release_prep` creates a candidate in `awaiting_approval`. The public HTTP
  approval/rejection endpoints require an **authenticated ADMIN API key**
  (`AUTH_ENABLED=true`). A WRITE key used by a native worker cannot approve;
  unauthenticated dev mode cannot approve; `approver` supplied in JSON is
  ignored for audit, the stored `approved_by` is the authenticated key subject.
  The release agent cannot approve its own candidate.

### Обязательная настройка перед одобрением релиза

Потребуется отдельный ADMIN-ключ для оператора и отдельный WRITE-ключ
для worker. До выдачи прав человек должен независимо проверить кандидата,
сводку тестов и security evidence. API связывает решение с доверенным ключом,
но **API-ключ сам по себе не доказывает присутствие человека**; выдача
admin-ключа unattended агенту уничтожит human approval boundary.

Пример Windows CMD / Linux при настроенной аутентификации:

```cmd
curl -X POST http://127.0.0.1:8003/api/v1/releases/RELEASE_ID/approve -H "X-API-Key: ADMIN_OPERATOR_KEY" -H "Content-Type: application/json" -d "{}"
```

В продуктовой конфигурации используйте HTTPS и не передавайте ключи в
журналируемых CLI-аргументах. Старое поле JSON `approver` больше не является
источником удостоверенной личности: `approved_by` вычисляется только по
авторизованному контексту. Эндпоинт остаётся API-закономерностью, а не
подтверждением фактического внешнего human review. 



## Autonomous native QA controller (opt-in)

The separate `quality_gates.native_qa_controller` process verifies a trusted Git ref after native completion, runs real `tester/reviewer/security` on a fresh detached checkout and transfers a signed QA receipt to orchestration. The worker never receives operator ADMIN or HMAC secrets. See [Russian operator instructions](../docs/qa/issue-11-auto-controller-ru.md). This finite controller is not enabled by the insecure default Compose and is not a multi-tenant sandbox.
