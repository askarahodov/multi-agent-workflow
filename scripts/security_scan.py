#!/usr/bin/env python3
"""Static security scan for the local quality gate (``make check``) and CI.

This is a thin wrapper around the repository's own security scanner -- the
Quality-Gates ``SecurityGate`` (``quality-gates/quality_gates/gates/security.py``)
-- so that the CI ``security`` check and the quality-gates service share a
single source of truth for the secret/dependency heuristics.

Test-fixture allowlist
----------------------
The gate's secret patterns are deliberately conservative and high-confidence.
The quality-gates suite ships fixture files that assemble AWS/GitHub token
*shapes* on purpose, in order to exercise the scanner; those files live under
``tests/``. A naive whole-repo scan therefore reports them as findings and the
gate would be permanently red on a clean checkout. Real secrets never ship in
test fixtures, so a ``secret`` hit whose path is a test/e2e/fixture path is
treated as allowlisted; every other hit fails the gate. The dependency scan is
*not* narrowed -- it always runs over the whole workspace.

Exit code: 0 when the gate passes, 1 when any real finding remains.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "quality-gates"))

from quality_gates.gates.security import SecurityGate  # noqa: E402

# A secret-shaped string in one of these paths is a deliberate test fixture,
# not a leaked credential.
FIXTURE_PATH = re.compile(
    r"(^|/)(tests?|e2e|fixtures?|__fixtures__)/"
    r"|(^|/)(test_[^/]*|[^/]*_test)\.py$"
    r"|\.spec\.[jt]sx?$"
)


def _is_fixture(path: str) -> bool:
    return bool(FIXTURE_PATH.search(path))


def main() -> int:
    result = SecurityGate().execute(str(REPO_ROOT))
    print(f"security gate: {result.summary} ({result.duration_ms:.0f} ms)")

    failed = False
    for finding in result.findings:
        hits = finding.detail.get("hits", []) if finding.category == "secret" else []
        fixtures = [h for h in hits if _is_fixture(h["file"])]
        real = [h for h in hits if not _is_fixture(h["file"])]
        passed = finding.passed or (finding.category == "secret" and not real)
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {finding.key}: {finding.summary}")
        for hit in real:
            print(f"        {hit['file']}  {hit['reason']} ({hit['severity']})")
        for row in finding.detail.get("vulnerable", []):
            print(f"        {row['package']} {row['version']} ({row['manifest']})")
        if finding.category == "secret" and fixtures:
            print(f"        ({len(fixtures)} test-fixture hit(s) allowlisted)")
        failed = failed or not passed

    if failed:
        print("security gate: FAILED", file=sys.stderr)
        return 1
    print("security gate: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
