"""Signed, bounded QA receipt exchanged between independent product services.

Only the trusted quality-gates service can produce this when it owns the
dedicated operator secret. The orchestration server verifies and stores it;
neither service trusts model-provided summaries as QA evidence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any

_QA_GATES = ("tester", "reviewer", "security")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"v", "task_id", "attempt_id", "commit_sha",
           "gate_run_ids", "issued_by", "issued_at"}
_MAX_AGE_SECONDS = 3600


class QaAttestationRejected(ValueError):
    """Invalid or expired evidence. Do not expose secrets in error messages."""


def _key_bytes(key: str) -> bytes:
    if type(key) is not str or not key.isascii() or not 32 <= len(key) <= 128:
        raise QaAttestationRejected("Dedicated QA signing key unavailable")
    return key.encode("ascii")


def _canonical(payload: dict[str, Any]) -> bytes:
    if type(payload) is not dict or set(payload) != _FIELDS:
        raise QaAttestationRejected("Invalid QA receipt fields")
    if type(payload["v"]) is not int or payload["v"] != 1:
        raise QaAttestationRejected("Unsupported QA receipt version")
    if any(type(payload[n]) is not str or not _ID.fullmatch(payload[n])
           for n in ("task_id", "attempt_id", "issued_by")):
        raise QaAttestationRejected("Invalid QA receipt identity")
    if type(payload["commit_sha"]) is not str or not _SHA.fullmatch(payload["commit_sha"]):
        raise QaAttestationRejected("Invalid QA Git identity")
    gates = payload["gate_run_ids"]
    if type(gates) is not dict or set(gates) != set(_QA_GATES):
        raise QaAttestationRejected("Incomplete QA gate receipt")
    if any(type(gates[n]) is not str or not _ID.fullmatch(gates[n])
           for n in _QA_GATES):
        raise QaAttestationRejected("Invalid QA run identity")
    if len(set(gates.values())) != len(_QA_GATES):
        raise QaAttestationRejected("Duplicate QA evidence run")
    if type(payload["issued_at"]) is not int or payload["issued_at"] <= 0:
        raise QaAttestationRejected("Invalid QA receipt timestamp")
    return json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
    ).encode("ascii")


def sign_qa_attestation(payload: dict[str, Any], key: str) -> dict[str, Any]:
    body = _canonical(payload)
    mac = hmac.new(_key_bytes(key), body, hashlib.sha256).hexdigest()
    return {**payload, "signature": mac}


def verify_qa_attestation(
    receipt: dict[str, Any], key: str, *, now: int | None = None,
) -> dict[str, Any]:
    if type(receipt) is not dict or set(receipt) != _FIELDS | {"signature"}:
        raise QaAttestationRejected("Invalid QA signature envelope")
    provided = receipt["signature"]
    if type(provided) is not str or not _DIGEST.fullmatch(provided):
        raise QaAttestationRejected("Invalid QA signature")
    payload = {field: receipt[field] for field in _FIELDS}
    body = _canonical(payload)
    current = int(time.time()) if now is None else now
    if current < payload["issued_at"] or current - payload["issued_at"] > _MAX_AGE_SECONDS:
        raise QaAttestationRejected("Expired or future QA receipt")
    correct = hmac.new(_key_bytes(key), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(correct, provided):
        raise QaAttestationRejected("Untrusted QA signature")
    return payload
