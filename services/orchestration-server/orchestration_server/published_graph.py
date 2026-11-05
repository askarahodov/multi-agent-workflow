"""Strict compiler for versioned workflow graphs -> orchestration task specs.

Only proven linear semantics are supported. Never silently skip a designed node:
conditional branches, parallelism, human approvals, tools, memory and delay are
not supported by the existing task engine and must fail before a run exists.
"""
from __future__ import annotations

import re
from typing import Any

from .errors import ValidationError

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
SUPPORTED = {"start", "agent", "gate", "end"}
MAX_NODES = 80


def _invalid(message: str):
    raise ValidationError("Published workflow is not executable: " + message)


def compile_published_graph(snapshot: Any) -> list[dict[str, Any]]:
    """Compile Start -> (Agent -> automatic Contract Gate)+ -> End.

    Each gate maps to contract_id on its preceding agent task, preserving the
    existing engine's verification and native leased-task requirement. Profile
    references are preserved as provenance metadata; assignment/runtime profile
    enforcement is a separate security boundary, not implied by this compiler.
    """
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != "1.0":
        _invalid("unsupported schema version")
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not 4 <= len(nodes) <= MAX_NODES or len(edges) != len(nodes) - 1:
        _invalid("expected a bounded linear graph with at least one Agent and Contract Gate")
    by_id: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict):
            _invalid("node must be an object")
        nid = node.get("id")
        kind = node.get("type")
        if not isinstance(nid, str) or not nid or len(nid) > 200 or nid in by_id:
            _invalid("missing or duplicate node id")
        if not isinstance(kind, str) or kind not in SUPPORTED:
            _invalid(f"node {nid}: unsupported runtime type {kind!r}")
        if not isinstance(node.get("label"), str) or not node["label"].strip() or len(node["label"]) > 255:
            _invalid(f"node {nid}: invalid label")
        if not isinstance(node.get("config"), dict):
            _invalid(f"node {nid}: invalid configuration")
        by_id[nid] = node
    starts = [n for n in nodes if n["type"] == "start"]
    ends = [n for n in nodes if n["type"] == "end"]
    if len(starts) != 1 or len(ends) != 1:
        _invalid("exactly one Start and one End node required")
    outgoing: dict[str, list[str]] = {i: [] for i in by_id}
    incoming: dict[str, int] = {i: 0 for i in by_id}
    for edge in edges:
        if not isinstance(edge, dict):
            _invalid("edge must be an object")
        src, dst = edge.get("source_node_id"), edge.get("target_node_id")
        if not isinstance(src, str) or not isinstance(dst, str) or src not in by_id or dst not in by_id:
            _invalid("dangling edge endpoint")
        if edge.get("condition") not in (None, "") or edge.get("output_mapping", {}) != {} or edge.get("on_error") != "fail" or edge.get("max_retries") != 0:
            _invalid("conditional/output mapping/retry edge semantics are not implemented")
        outgoing[src].append(dst)
        incoming[dst] += 1
    start_id, end_id = starts[0]["id"], ends[0]["id"]
    for nid in by_id:
        if (incoming[nid] != (0 if nid == start_id else 1)
                or len(outgoing[nid]) != (0 if nid == end_id else 1)):
            _invalid("branch, join, disconnected or cyclic edges are unsupported")
    if starts[0]["config"] or ends[0]["config"]:
        _invalid("Start/End configuration has no runtime semantics")
    tasks: list[dict[str, Any]] = []
    current = start_id
    visited = {current}
    while current != end_id:
        current = outgoing[current][0]
        if current in visited:
            _invalid("cycle detected")
        visited.add(current)
        if current == end_id:
            break
        agent = by_id[current]
        if agent["type"] != "agent":
            _invalid("every executable step must start with Agent")
        config = agent["config"]
        if set(config) != {"agent_definition_id", "model_profile_id", "tool_policy_id"}:
            _invalid(f"Agent {current}: unsupported or missing configuration")
        if not all(isinstance(v, str) and UUID.fullmatch(v) for v in config.values()):
            _invalid(f"Agent {current}: invalid agent/model/tool policy UUID references")
        if not outgoing[current]:
            _invalid("Agent must be followed by a Contract Gate")
        gate_id = outgoing[current][0]
        if gate_id in visited:
            _invalid("cycle detected")
        visited.add(gate_id)
        gate = by_id[gate_id]
        if gate["type"] != "gate" or set(gate["config"]) != {"gate_type", "contract_id"} or gate["config"]["gate_type"] != "automatic":
            _invalid(f"Agent {current}: only an automatic Contract Gate is executable")
        contract_id = gate["config"]["contract_id"]
        if not isinstance(contract_id, str) or not UUID.fullmatch(contract_id):
            _invalid(f"Gate {gate_id}: valid contract UUID required")
        tasks.append({
            "title": agent["label"].strip(),
            "node_id": current,
            "description": f"Published graph agent: {current}",
            "contract_id": contract_id,
            # These are provenance, not execution-mode/LLM/provider overrides.
            "input_data": {"workflow_node_id": current,
                           "workflow_agent_reference": dict(config)},
            "depends_on": [len(tasks) - 1] if tasks else [],
        })
        current = gate_id
    if len(visited) != len(by_id) or not tasks:
        _invalid("all nodes must form one connected Start -> Agent/Gate -> End chain")
    return tasks
