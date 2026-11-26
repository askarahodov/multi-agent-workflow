"""Structural contract inventory and mirror drift checks for #337.

The registry does not grant capabilities, change runtime schemas, or attest
that its related tests cover every requirement. Existing contract tests
remain authoritative for their individual behaviors.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/architecture/contract-registry.json"
RUNTIME = ROOT / "services/runtime-hardening"
DOCS = ROOT / "docs/runtime-hardening"


def _source(path):
    if not isinstance(path, str) or not path or Path(path).is_absolute():
        raise ValueError("Invalid registry path")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError("Invalid registry path")
    target = (ROOT / path).resolve(strict=True)
    if not target.is_relative_to(ROOT) or not target.is_file():
        raise ValueError("Registry path is not a repository file")
    return target


def _validate(registry):
    if registry.get("schema_version") != "0.1" or registry.get("status") != "draft":
        raise ValueError("Unsupported registry")
    entries = registry["contracts"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Empty inventory")
    ids = set()
    for entry in entries:
        cid = entry["id"]
        if not re.fullmatch(r"CT-\d{2}", cid) or cid in ids:
            raise ValueError("Duplicate or invalid contract ID")
        ids.add(cid)
        if entry["status"] != "inventory" or not all(
            isinstance(entry[key], str) and entry[key].strip()
            for key in ("name", "owner", "gap")
        ):
            raise ValueError("Invalid inventory status or metadata")
        if not entry["sources"] or not isinstance(entry["related_tests"], list):
            raise ValueError("Missing source/test list")
        for key in ("sources", "related_tests"):
            refs = entry[key]
            if not isinstance(refs, list) or len(refs) != len(set(refs)):
                raise ValueError("Invalid or duplicate references")
            for path in refs:
                _source(path)
    return ids


def _registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_inventory_references_are_real_and_complete():
    assert _validate(_registry()) == {f"CT-{n:02}" for n in range(1, 16)}


def test_inventory_rejects_orphan_duplicate_and_traversal():
    data = _registry()
    data["contracts"].append(data["contracts"][0])
    with pytest.raises(ValueError):
        _validate(data)
    data = _registry()
    data["contracts"][0]["sources"] = ["docs/../AGENT_GITFLOW_RULES.md"]
    with pytest.raises(ValueError):
        _validate(data)
    data["contracts"][0]["sources"] = ["docs/nonexistent-contract-fixture.json"]
    with pytest.raises(FileNotFoundError):
        _validate(data)


def test_quota_mirrors_only_have_known_uri_difference():
    rel = "config/resource-quota.schema.json"
    runtime = json.loads((RUNTIME / rel).read_text(encoding="utf-8"))
    nested = json.loads((RUNTIME / "hardening" / rel).read_text(encoding="utf-8"))
    docs = json.loads((DOCS / "schemas/resource-quota.schema.json").read_text(encoding="utf-8"))
    assert runtime == nested
    # Preserve the known legacy URI until owners agree on migration.
    # No other fields are ignored.
    assert runtime["$id"] == "https://harbor-transfer-portal/schemas/resource-quota.schema.json"
    assert docs["$id"] == "https://multi-agent-workflow/schemas/resource-quota.schema.json"
    assert {**runtime, "$id": docs["$id"]} == docs


@pytest.mark.parametrize("filename", ["agent-runtime-openapi.yaml", "lifecycle-events-asyncapi.yaml"])
def test_runtime_api_mirrors_only_have_known_contact_difference(filename):
    runtime = (RUNTIME / "hardening/api" / filename).read_text(encoding="utf-8")
    docs = (DOCS / "api" / filename).read_text(encoding="utf-8")
    old = "    name: Harbor-Transfer-Portal Platform Team"
    new = "    name: Multi-Agent Workflow Platform Team"
    assert runtime.splitlines().count(old) == 1
    assert docs.splitlines().count(new) == 1
    assert runtime.replace(old, new).splitlines() == docs.splitlines()
