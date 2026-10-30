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


def test_evidence_store_rejects_parent_and_absolute_paths(tmp_path):
    import pytest
    from quality_gates.errors import EvidenceStorageError

    store = EvidenceStore(tmp_path / "evidence")
    outside = tmp_path / "outside"
    outside.mkdir()
    for task, run in [
        ("../outside", "run1"),
        (str(outside), "run1"),
        ("safe", "../../outside"),
    ]:
        with pytest.raises(EvidenceStorageError, match="escapes storage root"):
            store.store(task, run, "unit", "check", {"passed": True})
    assert list(outside.iterdir()) == []

    meta = store.store("safe", "run-ok", "unit", "check", {"passed": True})
    valid = meta["path"]
    for path in ("../outside/missing.json", str(outside / "missing.json"), "../../etc/passwd"):
        assert store.verify(path) is False
        assert store.read(path) is None
    assert store.verify(valid) is True
    assert store.read(valid)["passed"] is True


def test_evidence_store_blocks_symlink_escape_for_write_and_read(tmp_path):
    import pytest
    from quality_gates.errors import EvidenceStorageError

    root = tmp_path / "evidence"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "redirect").symlink_to(outside, target_is_directory=True)
    store = EvidenceStore(root)

    with pytest.raises(EvidenceStorageError, match="escapes storage root"):
        store.store("redirect", "run1", "unit", "check", {"passed": True})
    assert list(outside.iterdir()) == []

    valid_doc = store.store("safe", "run2", "unit", "check", {"passed": True})
    (root / "safe" / "run2" / "unit_check.json").unlink()
    (outside / "unit_check.json").write_text('{"passed":true}')
    (root / "safe" / "run2" / "unit_check.json").symlink_to(outside / "unit_check.json")
    assert store.verify(valid_doc["path"]) is False
    assert store.read(valid_doc["path"]) is None


def test_evidence_category_rejects_unsafe_filename_segments_before_io(tmp_path):
    import pytest
    from quality_gates.errors import EvidenceStorageError

    root = tmp_path / "evidence"
    store = EvidenceStore(root)
    for category in ("..", ".", "../escape", "unit/../../escape", "/absolute", "unit\\\\sneaky",
                     "", "unit.name", "unit:secret", "x" * 33):
        with pytest.raises(EvidenceStorageError, match="invalid evidence category"):
            store.store("task", "run", category, "safe", {"passed": True})
        assert not root.exists(), category

    for category in ("unit", "release_prep", "security-check"):
        meta = store.store("task", "run", category, "safe", {"passed": True})
        assert meta["path"] == f"task/run/{category}_safe.json"
        assert store.verify(meta["path"])
        assert store.read(meta["path"])["passed"] is True
