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

## Evidence & release flow

- Every gate run stores `gate_runs` and immutable `evidence_items` rows; each
  evidence document is written to disk under `evidence_root` with an embedded
  SHA-256 checksum (`quality_gates/evidence.py`).
- `GatePipeline.transition` blocks any status advance until `required_gates` all
  have a passing run (`TransitionForbiddenError` otherwise).
- `release_prep` creates a candidate in `awaiting_approval`; only an explicit
  human approval can move it to `approved` (`approve_release_candidate`), and
  the release agent can never approve its own candidate.
