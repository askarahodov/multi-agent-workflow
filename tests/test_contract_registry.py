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
        if (entry["producer"] != entry["owner"] or
                not isinstance(entry["consumers"], list) or not entry["consumers"] or
                not all(isinstance(v, str) and v.strip() for v in entry["consumers"]) or
                len(entry["consumers"]) != len(set(entry["consumers"]))):
            raise ValueError("Invalid producer/consumer boundary")
        authority = entry["runtime_authority"]
        if entry["authority_status"] == "observed":
            if not authority or authority not in entry["sources"]:
                raise ValueError("Runtime authority must reference an inventoried source")
        elif entry["authority_status"] != "owner_decision_required" or authority is not None:
            raise ValueError("Unresolved authority must not claim canonical source")
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


def test_inventory_rejects_duplicate_contract():
    data = _registry()
    data["contracts"].append(data["contracts"][0])
    with pytest.raises(ValueError, match="Duplicate or invalid contract ID"):
        _validate(data)


def test_inventory_rejects_path_traversal():
    data = _registry()
    data["contracts"][0]["sources"].append("docs/../AGENT_GITFLOW_RULES.md")
    with pytest.raises(ValueError, match="Invalid registry path"):
        _validate(data)


def test_inventory_rejects_missing_source():
    data = _registry()
    data["contracts"][0]["sources"].append("docs/nonexistent-contract-fixture.json")
    with pytest.raises(FileNotFoundError, match="nonexistent-contract-fixture"):
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


def test_inventory_rejects_missing_consumer_and_unlisted_authority():
    data = _registry()
    data["contracts"][0]["consumers"] = []
    with pytest.raises(ValueError, match="producer/consumer"):
        _validate(data)
    data = _registry()
    data["contracts"][0]["runtime_authority"] = "README.md"
    with pytest.raises(ValueError, match="authority"):
        _validate(data)
    data = _registry()
    row = next(r for r in data["contracts"] if r["id"] == "CT-13")
    row["runtime_authority"] = row["sources"][0]
    with pytest.raises(ValueError, match="Unresolved authority"):
        _validate(data)


def _quota_document():
    return {"schemaVersion": "1.0.0", "parentBudget": {"memory": {
        "highBytes": 80, "maxBytes": 100, "swapMaxBytes": 100}},
        "resourceClasses": {"default": {"cpu": {"quotaMicros": 1000},
            "pids": {"max": 10}}},
        "agents": {"worker": {"class": "default"}}}


def _quota_schema():
    from jsonschema import Draft202012Validator

    schema = json.loads((RUNTIME / "config/resource-quota.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _load_quota_document(tmp_path, payload):
    import yaml
    from runtime.config import load_quota_config

    path = tmp_path / "quota.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return load_quota_config(path)


def test_runtime_quota_example_and_round_trip(tmp_path):
    import yaml

    validator = _quota_schema()
    example = yaml.safe_load((RUNTIME / "config/resource-quotas.example.yaml").read_text())
    for payload in (_quota_document(), example):
        validator.validate(payload)
        result = _load_quota_document(tmp_path, payload)
        # Persisted JSON/YAML representation uses the public "class" alias.
        emitted = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        validator.validate(emitted)
        assert _load_quota_document(tmp_path, emitted) == result


@pytest.mark.parametrize("case", ["unknown_top_level", "unknown_nested", "missing_parent",
    "empty_classes", "negative_pid", "bad_cpu_weight", "bad_device", "unknown_agent_field"])
def test_runtime_and_documented_quota_reject_invalid_structure(tmp_path, case):
    from pydantic import ValidationError

    payload = _quota_document()
    cls = payload["resourceClasses"]["default"]
    if case == "unknown_top_level": payload["unexpected"] = True
    elif case == "unknown_nested": cls["cpu"]["unexpected"] = 1
    elif case == "missing_parent": del payload["parentBudget"]
    elif case == "empty_classes": payload["resourceClasses"] = {}
    elif case == "negative_pid": cls["pids"]["max"] = 0
    elif case == "bad_cpu_weight": cls["cpu"]["weight"] = 10001
    elif case == "bad_device": cls["diskIo"] = {"max": [{"device": "invalid"}]}
    elif case == "unknown_agent_field": payload["agents"]["worker"]["unexpected"] = 1
    assert not _quota_schema().is_valid(payload)
    with pytest.raises(ValidationError):
        _load_quota_document(tmp_path, payload)


@pytest.mark.parametrize("case", ["high_above_max", "swap_mismatch", "unknown_class"])
def test_runtime_enforces_semantics_not_expressible_by_current_schema(tmp_path, case):
    from pydantic import ValidationError

    payload = _quota_document()
    if case == "high_above_max": payload["parentBudget"]["memory"]["highBytes"] = 101
    elif case == "swap_mismatch": payload["parentBudget"]["memory"]["swapMaxBytes"] = 99
    elif case == "unknown_class": payload["agents"]["worker"]["class"] = "missing"
    # Draft JSON Schema does not enforce these cross-field/reference rules.
    # Never count schema success alone as acceptance.
    assert _quota_schema().is_valid(payload)
    with pytest.raises(ValidationError):
        _load_quota_document(tmp_path, payload)


@pytest.mark.parametrize("case", ["missing_version", "unknown_version", "numeric_string"])
def test_runtime_quota_known_compatibility_gap(tmp_path, case):
    payload = _quota_document()
    if case == "missing_version": del payload["schemaVersion"]
    elif case == "unknown_version": payload["schemaVersion"] = "2.0.0"
    elif case == "numeric_string": payload["resourceClasses"]["default"]["pids"]["max"] = "10"
    # Explicit unresolved compatibility baseline, NOT a positive contract
    # acceptance. Changing either boundary requires revisiting CT-10.
    assert not _quota_schema().is_valid(payload)
    result = _load_quota_document(tmp_path, payload)
    if case == "missing_version": assert result.schemaVersion == "1.0.0"
    elif case == "unknown_version": assert result.schemaVersion == "2.0.0"
    elif case == "numeric_string": assert result.resourceClasses["default"].pids.max == 10
