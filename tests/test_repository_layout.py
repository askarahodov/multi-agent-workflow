"""Repository layout guard (issue #257).

The monorepo has a single canonical place for every kind of file. This test
fails when a duplicate tree or a stray root-level script creeps back in, which
is exactly what happened before #257 (a second `pages/` frontend tree and
root-level Python helpers alongside `services/` + `scripts/`).

Rules enforced here:
1. `apps/frontend/src/pages/` must not exist (merged into `mvp/sections/`).
2. Root-level Python modules are not allowed; the only root `.py` entry points
   are the security gate helper (`scripts/`) and tests (`tests/`).
3. Frontend layouts are reachable through exactly one directory.
4. Documentation entry points stay at the root (`README.md`, `Makefile`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = REPO_ROOT / "apps" / "frontend" / "src"

# Root files that are intentionally part of the repository entry surface.
ALLOWED_ROOT_PYTHON: set[str] = set()
ALLOWED_ROOT_MARKDOWN = {
    "AGENT_GITFLOW_RULES.md",
    "CHANGELOG.md",
    "PLAN.md",
    "README.md",
    "RELEASE_NOTES_v0.1.0-rc1.md",
}


def _tracked_root_files(glob: str) -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", glob],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in output.splitlines() if line and "/" not in line]


def test_no_duplicate_frontend_pages_tree() -> None:
    assert not (FRONTEND_SRC / "pages").exists(), (
        "apps/frontend/src/pages/ must not exist; layouts live in mvp/sections/"
    )


def test_frontend_layouts_have_one_location() -> None:
    sections = FRONTEND_SRC / "mvp" / "sections"
    assert sections.is_dir(), "apps/frontend/src/mvp/sections/ is the canonical layout tree"
    layouts = sorted(p.name for p in sections.glob("*.tsx") if not p.name.endswith(".test.tsx"))
    assert layouts, "expected layout components in mvp/sections/"


def test_no_stray_root_python_modules() -> None:
    tracked = set(_tracked_root_files("*.py"))
    assert tracked == ALLOWED_ROOT_PYTHON, (
        "root-level Python modules are not part of the layout; "
        f"unexpected files: {sorted(tracked - ALLOWED_ROOT_PYTHON)}"
    )


def test_root_markdown_is_limited_to_entry_points() -> None:
    tracked = set(_tracked_root_files("*.md"))
    assert tracked <= ALLOWED_ROOT_MARKDOWN, (
        f"unexpected root markdown: {sorted(tracked - ALLOWED_ROOT_MARKDOWN)}"
    )


def test_documentation_entry_points_exist() -> None:
    for name in ("README.md", "Makefile", "AGENT_GITFLOW_RULES.md"):
        assert (REPO_ROOT / name).is_file(), f"{name} must stay at the repository root"


def test_local_sqlite_state_is_ignored_and_untracked() -> None:
    """Guard against accidentally re-committing a live DB (#311)."""
    names = [
        "services/orchestration-server/orchestration.db",
        "services/orchestration-server/orchestration.db-wal",
        "services/orchestration-server/orchestration.db-shm",
        "services/orchestration-server/orchestration.db-journal",
        "services/agent-management/agent_management.db",
        "services/quality-gates/quality_gates.db",
    ]
    output = subprocess.run(
        ["git", "ls-files", "--", *names],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    ).stdout
    assert not output.strip(), "Live SQLite databases must not be tracked by Git"
    for path in (*names, "smoke.json", ".maw-workspace-sample/secret.key"):
        checked = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert checked.returncode == 0, f"Local secret/state path is not ignored: {path}"


def test_docker_build_context_excludes_local_credentials_and_databases() -> None:
    """Git ignore alone cannot protect secrets from Docker build contexts."""
    ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    entries = {line.strip() for line in ignore.splitlines()
               if line.strip() and not line.lstrip().startswith("#")}
    for required in (
        ".env", ".env.*", "**/.env", "**/.env.*",
        ".local", "**/.local", ".maw-*", "**/.maw-*",
        "**/*.key", "**/*.pem", "**/*.db", "**/*.db-*",
        "smoke.json",
    ):
        assert required in entries, f"Unsafe Docker build context: {required}"
