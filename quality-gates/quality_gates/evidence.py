"""Auditable evidence store.

Evidence is written to disk as immutable JSON documents under the evidence root
and referenced from the ``evidence_items`` table. Each document stores its own
SHA-256 checksum, so tampering with a stored report is detectable. Rows in the
table are immutable after creation (enforced at the ORM level in ``models.py``).

Layout::

    <evidence_root>/<task_id>/<run_id>/<category>_<key>.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import EvidenceStorageError


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sanitize(key: str) -> str:
    """Turn an arbitrary evidence key into a filesystem-safe filename fragment."""
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")
    return cleaned or "evidence"


class EvidenceStore:
    """Filesystem-backed evidence storage with checksum verification."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _run_dir(self, task_id: str, run_id: str) -> Path:
        return self.root / task_id / run_id

    def store(self, task_id: str, run_id: str, category: str, key: str, value: dict) -> dict:
        """Persist an evidence document and return its metadata (incl. checksum).

        Returns a dict suitable for an ``evidence_items`` row.
        """
        try:
            run_dir = self._run_dir(task_id, run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            body = {k: v for k, v in value.items() if k != "_checksum"}
            checksum = self.compute_checksum(body)
            doc = {**body, "_checksum": checksum}
            raw = json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True).encode("utf-8")
            # Filenames must be filesystem-safe; keys are arbitrary strings.
            safe_key = _sanitize(key)
            path = run_dir / f"{category}_{safe_key}.json"
            path.write_bytes(raw)
            return {"checksum": checksum, "path": str(path.relative_to(self.root))}
        except OSError as exc:  # pragma: no cover - defensive
            raise EvidenceStorageError(f"failed to persist evidence: {exc}") from exc

    def verify(self, path: str) -> bool:
        """Return True if the on-disk document's checksum matches its own field.

        Each stored document is expected to contain a ``_checksum`` field equal
        to the SHA-256 of the document body (that field excluded). If it is
        missing or mismatched the document is considered tampered/unsound.
        """
        try:
            p = self.root / path
            raw = p.read_bytes()
            doc = json.loads(raw)
            expected = doc.get("_checksum")
            if not isinstance(expected, str):
                return False
            body = {k: v for k, v in doc.items() if k != "_checksum"}
            recomputed = _sha256_bytes(json.dumps(body, sort_keys=True).encode("utf-8"))
            return recomputed == expected
        except (OSError, ValueError, KeyError):
            return False

    def read(self, path: str) -> dict | None:
        """Read and return the document if it verifies, else None."""
        if not self.verify(path):
            return None
        try:
            return json.loads((self.root / path).read_bytes())
        except (OSError, ValueError):
            return None

    def compute_checksum(self, data: dict) -> str:
        """Compute a checksum for a body dict (used for release artifacts too)."""
        raw = json.dumps(data, sort_keys=True).encode("utf-8")
        return _sha256_bytes(raw)


def checksum_file(path: Path) -> str:
    """SHA-256 of an arbitrary file (used for release artifact verification)."""
    return _sha256_file(Path(path))
