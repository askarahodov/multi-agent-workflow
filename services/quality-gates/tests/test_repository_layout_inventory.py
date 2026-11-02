"""Read-only inventory honors repository contracts without editing files."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "layout_inventory",
    Path(__file__).resolve().parents[3] / "scripts/inventory_repository_layout.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_inventory_real_repository_has_expected_areas_and_overlays():
    root = Path(__file__).resolve().parents[3]
    report = module.inventory(root)
    assert set(module.SERVICE_AREAS) == set(report["service_areas"])
    assert "compose.native-worker-runtime.yml" in report["compose_overlays"]
    assert "compose.native-qa-runtime.yml" in report["compose_overlays"]
    assert "services/orchestration-server" in report["move_prohibited_without_agent_coordination"]


def test_inventory_rejects_incomplete_checkout_without_modification(tmp_path):
    (tmp_path / "README.md").write_text("read-only")
    with pytest.raises(ValueError, match="Repository structure incomplete"):
        module.inventory(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["README.md"]


def test_path_reference_map_finds_consumers_and_skips_vendor_and_symlinks(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("build: ./orchestration-server\\n")
    (tmp_path / "Makefile").write_text("test:; cd quality-gates && pytest\\n")
    vendor = tmp_path / "node_modules"
    vendor.mkdir()
    (vendor / "ignored.py").write_text("orchestration-server")
    (tmp_path / "unrelated.py").write_text("nothing to relocate")
    assert module.path_references(tmp_path, ("orchestration-server", "quality-gates")) == {
        "orchestration-server": ["docker-compose.yml"],
        "quality-gates": ["Makefile"],
    }


def test_path_reference_scan_is_read_only(tmp_path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("context: ./frontend")
    before = compose.read_bytes()
    result = module.path_references(tmp_path, ("frontend",))
    assert result == {"frontend": ["docker-compose.yml"]}
    assert compose.read_bytes() == before
