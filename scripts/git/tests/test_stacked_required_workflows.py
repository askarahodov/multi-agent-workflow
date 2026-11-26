"""Required GitFlow checks must be triggered for stacked PRs, not only main."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("filename", "required_job"),
    [
        ("coordination-isolation.yml",
         "Reject external QA channel files in product main"),
        ("native-agent-e2e.yml", "Native LLM-tool-Contract Gate (offline)"),
    ],
)
def test_required_workflows_run_for_stacked_prs(filename, required_job):
    content = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
    # The event block is intentionally simple. Fail closed if it gains
    # branch/path filters or changes to a different event syntax: review the
    # trigger coverage rather than silently skipping required checks.
    trigger = re.search(r"(?m)^  pull_request:[ \t]*\n", content)
    assert trigger is not None
    tail = content[trigger.end():]
    assert not re.match(r"(?:(?:[ \t]*#.*|[ \t]*)\n)* {4}[^\s#]", tail)
    assert "pull_request_target:" not in content
    assert "permissions:\n  contents: read\n" in content
    assert f"name: {required_job}" in content
