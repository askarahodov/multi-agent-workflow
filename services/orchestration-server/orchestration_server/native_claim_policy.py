"""Operator-owned assignment constraints for revision-pinned native tasks.

Not a second profile registry: no prompts, tools, credentials or delegation
authority are defined here. Bind a reviewed deployment to one worker key
digest and explicit immutable workflow nodes. Unconfigured pinned work is
denied, including when AUTH_ENABLED=false.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import ConflictError
from .native_profile_binding import (
    PROFILE_KEYS, REVISION_KEY, UUID, TrustedProfileBinding,
    TrustedProfileRevision, task_matches_binding,
)


def credential_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _uuid(value):
    if type(value) is not str or not UUID.fullmatch(value):
        raise ValueError("Invalid assignment UUID")
    return value.lower()


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("Invalid assignment fields")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate assignment field")
        result[key] = value
    return result


@dataclass(frozen=True)
class AssignmentScope:
    project_id: str
    workspace_id: str | None
    workflow_version_id: str
    node_id: str

    @classmethod
    def parse(cls, value):
        _exact(value, ("project_id", "workspace_id", "workflow_version_id", "node_id"))
        node = value["node_id"]
        if type(node) is not str or not 1 <= len(node) <= 200 or any(ord(c) < 32 for c in node):
            raise ValueError("Invalid assignment node")
        return cls(_uuid(value["project_id"]),
                   None if value["workspace_id"] is None else _uuid(value["workspace_id"]),
                   _uuid(value["workflow_version_id"]), node)


@dataclass(frozen=True, repr=False)
class WorkerAssignment:
    agent_id: str
    key_sha256: str
    binding: TrustedProfileBinding
    revision: TrustedProfileRevision
    scopes: frozenset[AssignmentScope]


def is_pinned_task(input_data):
    return (isinstance(input_data, dict)
            and isinstance(input_data.get("workflow_agent_reference"), dict)
            and REVISION_KEY in input_data["workflow_agent_reference"])


@dataclass(frozen=True, repr=False)
class NativeClaimPolicy:
    assignments: tuple[WorkerAssignment, ...] = ()

    @classmethod
    def parse(cls, document):
        _exact(document, ("schema_version", "workers"))
        if type(document["schema_version"]) is not int or document["schema_version"] != 1:
            raise ValueError("Unsupported assignment schema")
        workers = document["workers"]
        if type(workers) is not list or not 1 <= len(workers) <= 128:
            raise ValueError("Invalid assignment count")
        entries = []
        for row in workers:
            _exact(row, ("agent_id", "key_sha256", "profile", "scopes"))
            digest = row["key_sha256"]
            if type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError("Invalid worker credential digest")
            profile = row["profile"]
            _exact(profile, (*PROFILE_KEYS, REVISION_KEY))
            scopes = row["scopes"]
            if type(scopes) is not list or not 1 <= len(scopes) <= 128:
                raise ValueError("Invalid scope count")
            parsed_scopes = frozenset(AssignmentScope.parse(scope) for scope in scopes)
            if len(parsed_scopes) != len(scopes):
                raise ValueError("Duplicate assignment scope")
            entries.append(WorkerAssignment(
                _uuid(row["agent_id"]), digest,
                TrustedProfileBinding(*(_uuid(profile[k]) for k in PROFILE_KEYS)),
                TrustedProfileRevision.from_mapping(profile[REVISION_KEY]), parsed_scopes,
            ))
        if (len({e.agent_id for e in entries}) != len(entries)
                or len({e.key_sha256 for e in entries}) != len(entries)):
            raise ValueError("Each worker requires a distinct identity and key")
        return cls(tuple(entries))

    def has_key(self, digest):
        return any(row.key_sha256 == digest for row in self.assignments)

    def validate_credentials(self, *, auth_enabled, leases_enabled, write_keys, admin_keys,
                             reserved_keys=()):
        if not self.assignments:
            return
        if not auth_enabled or not leases_enabled:
            raise ValueError("Pinned worker assignments require authentication and leases")
        eligible = {credential_digest(key) for key in write_keys
                    if key not in admin_keys and key not in reserved_keys
                    and key.isascii() and 32 <= len(key) <= 128}
        if any(row.key_sha256 not in eligible for row in self.assignments):
            raise ValueError("Pinned worker requires a separate configured WRITE credential")

    def require(self, task, run, agent_id, digest, *, leased):
        """Check trusted task/run metadata and principal before a mutation."""
        entry = next((row for row in self.assignments if row.agent_id == agent_id), None)
        pinned = is_pinned_task(task.input_data)
        if not pinned and entry is None and not self.has_key(digest):
            return
        # Scoped credentials cannot fall back to legacy claims or impersonate
        # another registered worker. Absence of a policy never allows a pin.
        if not pinned or not leased or entry is None or entry.key_sha256 != digest:
            raise ConflictError("Native worker assignment unavailable")
        try:
            run_input = run.input_data
            if type(run_input) is not dict or type(task.input_data) is not dict:
                raise ValueError("Missing workflow provenance")
            node = task.input_data.get("workflow_node_id")
            if task.node_id != node or type(node) is not str:
                raise ValueError("Invalid task node identity")
            scope = AssignmentScope.parse({
                "project_id": run.project_id, "workspace_id": run.workspace_id,
                "workflow_version_id": run_input.get("_workflow_version_id"), "node_id": node,
            })
            if scope not in entry.scopes or not task_matches_binding(
                {"input_data": task.input_data}, entry.binding, published=True, revision=entry.revision
            ):
                raise ValueError("Assignment mismatch")
        except (ValueError, TypeError):
            raise ConflictError("Native worker assignment unavailable") from None


def read_claim_policy(path: str | None) -> NativeClaimPolicy:
    if path is None:
        return NativeClaimPolicy()
    try:
        candidate = Path(path)
        if not candidate.is_absolute() or any(p.is_symlink() for p in (candidate, *candidate.parents)):
            raise ValueError("Invalid private assignment path")
        entry = os.lstat(candidate)
        if (not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1
                or entry.st_mode & 0o077 or not 1 <= entry.st_size <= 262144
                or (hasattr(os, "geteuid") and entry.st_uid != os.geteuid())):
            raise ValueError("Invalid private assignment file")
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            checked = os.fstat(fd)
            if ((checked.st_dev, checked.st_ino) != (entry.st_dev, entry.st_ino)
                    or not stat.S_ISREG(checked.st_mode) or checked.st_nlink != 1
                    or checked.st_mode & 0o077
                    or (hasattr(os, "geteuid") and checked.st_uid != os.geteuid())):
                raise ValueError("Assignment file changed")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(262145)
        finally:
            os.close(fd)
        if len(raw) > 262144:
            raise ValueError("Assignment file too large")
        return NativeClaimPolicy.parse(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique))
    except (OSError, ValueError, TypeError, UnicodeError):
        raise ValueError("Private native assignment policy unavailable or invalid") from None
