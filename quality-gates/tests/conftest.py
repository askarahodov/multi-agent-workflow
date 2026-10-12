"""Shared fixtures for the quality-gates test suite.

Each test gets its own isolated SQLite database, evidence root and artifact
root under ``tmp_path`` so no test depends on external infrastructure. Gates
that shell out (tester) are exercised against a tiny fixture workspace with a
real pytest run so unit/integration evidence is genuinely produced.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio

# Disable authentication for the non-auth test suite (matches agent-management,
# orchestration-server, runtime-hardening). SEC-001 wires AuthMiddleware; the
# suite runs with auth disabled, consistent with the other services.
os.environ["AUTH_ENABLED"] = "false"

from quality_gates.config import Settings
from quality_gates.db import build_engine, build_session_factory, create_all
from quality_gates.pipeline import GatePipeline


# Fake credentials used by Security-gate tests to exercise secret detection.
# They are assembled from fragments so that no literal secret-shaped string is
# committed to the repository: the security gate must not flag its own fixtures.
# The fragments are joined at runtime so the committed source holds no single
# match for the gate's secret patterns.
FAKE_AWS_KEY = "AKIA" + "0123456789ABCDEF"      # AKIA + 16 [0-9A-Z]
FAKE_GITHUB_TOKEN = "ghp_" + "a" * 36            # ghp_ + 36 [A-Za-z0-9]


class Harness:
    """A GatePipeline bound to one SQLite database + temp evidence/artifact roots."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.url = f"sqlite+aiosqlite:///{base / 'qg.db'}"
        self.engine = None
        self.sf = None
        self.settings = None
        self.pipeline = None

    async def start(self) -> "Harness":
        self.settings = Settings(
            evidence_root=self.base / "evidence",
            artifact_root=self.base / "artifacts",
            required_gates=("tester", "reviewer", "security", "release_prep"),
        )
        self.engine = build_engine(self.url)
        await create_all(self.engine)
        self.sf = build_session_factory(self.engine)
        self.pipeline = GatePipeline(self.sf, settings=self.settings)
        return self

    async def stop(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None


@pytest_asyncio.fixture
async def harness(tmp_path):
    h = Harness(tmp_path)
    await h.start()
    yield h
    await h.stop()


@pytest.fixture
def clean_workspace(tmp_path):
    """A minimal, clean source workspace that passes reviewer+security gates."""
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n")
    (ws / "README.md").write_text("# demo\n")
    (ws / "src").mkdir()
    # A trivial passing test so the TesterGate's pytest run succeeds (exit 0)
    # instead of "no tests collected" (exit 5).
    (ws / "tests").mkdir()
    (ws / "tests" / "test_demo.py").write_text(
        "def test_trivial():\n    assert True\n"
    )
    return ws


@pytest.fixture
def app(harness):
    from quality_gates.api import build_app

    app = build_app(settings=harness.settings, sf=harness.sf)
    return app
