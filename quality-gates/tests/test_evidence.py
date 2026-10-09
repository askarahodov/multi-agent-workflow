"""Tests for the auditable evidence store."""

from __future__ import annotations

from quality_gates.evidence import EvidenceStore, checksum_file


def test_store_and_verify_roundtrip(tmp_path):
    store = EvidenceStore(tmp_path / "ev")
    meta = store.store("t1", "run1", "unit", "check", {"passed": True, "n": 3})
    assert meta["checksum"]  # 64 hex chars
    assert store.verify(meta["path"])
    doc = store.read(meta["path"])
    assert doc is not None
    assert doc["passed"] is True
    assert doc["n"] == 3


def test_tampered_document_fails_verification(tmp_path):
    store = EvidenceStore(tmp_path / "ev")
    meta = store.store("t1", "run1", "unit", "check", {"passed": True})
    path = tmp_path / "ev" / meta["path"]
    # Mutate the stored document without updating its checksum.
    raw = path.read_text().replace('"passed": true', '"passed": false')
    path.write_text(raw)
    assert store.verify(meta["path"]) is False
    assert store.read(meta["path"]) is None


def test_missing_or_malformed_document_not_verified(tmp_path):
    store = EvidenceStore(tmp_path / "ev")
    assert store.verify("t1/run1/does_not_exist.json") is False


def test_checksum_file_changes_when_content_changes(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello world")
    before = checksum_file(p)
    p.write_bytes(b"changed")
    after = checksum_file(p)
    assert before != after
