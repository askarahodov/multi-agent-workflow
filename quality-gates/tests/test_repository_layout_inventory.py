"""Read-only inventory honors repository contracts without editing files."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "layout_inventory",
    Path(__file__).resolve().parents[2] / "scripts/inventory_repository_layout.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_inventory_real_repository_has_expected_areas_and_overlays():
    root = Path(__file__).resolve().parents[2]
    report = module.inventory(root)
    assert set(module.SERVICE_AREAS) == set(report["service_areas"])
    assert "compose.native-worker-runtime.yml" in report["compose_overlays"]
    assert "compose.native-qa-runtime.yml" in report["compose_overlays"]
    assert "orchestration-server" in report["move_prohibited_without_agent_coordination"]


def test_inventory_rejects_incomplete_checkout_without_modification(tmp_path):
    (tmp_path / "README.md").write_text("read-only")
    with pytest.raises(ValueError, match="Repository structure incomplete"):
        module.inventory(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["README.md"]
