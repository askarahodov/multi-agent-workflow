"""Regression tests for the #182 migration plan (no checkout mutation)."""
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.migrate_repository_layout import tracked_moves, verify


class MigrationPlannerTests(unittest.TestCase):
    @patch("scripts.migrate_repository_layout.git")
    def test_paths_and_secure_overlays(self, git):
        git.return_value = (
            "frontend/src/app.tsx\0orchestration-server/Dockerfile\0"
            "agent-management/pyproject.toml\0quality-gates/Dockerfile\0"
            "runtime-hardening/Dockerfile\0shared/pyproject.toml\0"
            "docker-compose.yml\0docker-compose.override.yml.example\0"
            "compose.native-worker-runtime.yml\0README.md\0"
        )
        self.assertEqual(dict(tracked_moves(pathlib.Path("."))), {
            "frontend/src/app.tsx": "apps/frontend/src/app.tsx",
            "orchestration-server/Dockerfile": "services/orchestration-server/Dockerfile",
            "agent-management/pyproject.toml": "services/agent-management/pyproject.toml",
            "quality-gates/Dockerfile": "services/quality-gates/Dockerfile",
            "runtime-hardening/Dockerfile": "services/runtime-hardening/Dockerfile",
            "shared/pyproject.toml": "packages/shared/pyproject.toml",
            "docker-compose.yml": "deploy/compose/dev/docker-compose.yml",
            "docker-compose.override.yml.example": "deploy/compose/dev/docker-compose.override.yml.example",
            "compose.native-worker-runtime.yml": "deploy/compose/secure/compose.native-worker-runtime.yml",
        })

    @patch("scripts.migrate_repository_layout.git")
    def test_dirty_checkout_refused(self, git):
        git.return_value = " M Makefile"
        with self.assertRaisesRegex(RuntimeError, "modifications"):
            verify(pathlib.Path("."), [("a", "b")])

    @patch("scripts.migrate_repository_layout.git")
    def test_existing_destination_refused(self, git):
        git.return_value = ""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "old").write_text("old")
            (root / "new").write_text("existing")
            with self.assertRaisesRegex(RuntimeError, "Target already exists"):
                verify(root, [("old", "new")])


if __name__ == "__main__":
    unittest.main()
