"""Tests for the shared SQLite persistence / Memory store (task item (d))."""

from __future__ import annotations

import pytest

from tools.storage import LevelError, MemoryStore


@pytest.fixture
def mem():
    store = MemoryStore()
    yield store
    store.close()


def test_write_and_get(mem):
    entry = mem.write("agent", "instructions", {"role": "assistant", "text": "hi"})
    assert entry["key"] == "instructions"
    assert entry["version"] == 1
    got = mem.get("agent", "instructions")
    assert got["value"]["text"] == "hi"


def test_invalid_level_rejected(mem):
    with pytest.raises(LevelError):
        mem.write("bogus", "k", "v")


def test_overwrite_bumps_version_and_histories(mem):
    e1 = mem.write("task", "draft", {"v": 1})
    e2 = mem.write("task", "draft", {"v": 2}, scope_id=None)
    assert e2["version"] == 2
    history = mem.versions(e1["id"])
    assert [h["version"] for h in history] == [1]
    assert history[0]["value"] == {"v": 1}


def test_scope_isolation(mem):
    mem.write("task", "key", {"owner": "a"}, scope_id="task-1")
    mem.write("task", "key", {"owner": "b"}, scope_id="task-2")
    assert mem.get("task", "key", scope_id="task-1")["value"]["owner"] == "a"
    assert mem.get("task", "key", scope_id="task-2")["value"]["owner"] == "b"


def test_fts_search(mem):
    mem.write("agent", "fact", "the sky is blue")
    mem.write("agent", "fact2", "paris is the capital of france")
    assert [r["key"] for r in mem.search("blue")] == ["fact"]
    assert [r["key"] for r in mem.search("paris")] == ["fact2"]


def test_search_scoped_by_level(mem):
    mem.write("agent", "note", "alpha marker")
    mem.write("project", "note", "beta marker", scope_id="p1")
    assert all(r["level"] == "project" for r in mem.search("marker", level="project"))
    assert all(r["level"] == "agent" for r in mem.search("marker", level="agent"))


def test_delete(mem):
    mem.write("agent", "k", "v")
    assert mem.delete("agent", "k") is True
    assert mem.delete("agent", "k") is False
    assert mem.get("agent", "k") is None


def test_memory_not_instruction_priority(mem):
    """Entries are plain stored facts; must never be auto-ranked above
    instructions (safety property, ADR-013 §2.2)."""
    mem.write("global", "priority", "HIGH")
    got = mem.get("global", "priority")
    assert got and got["key"] == "priority" and got["value"] == "HIGH"
    # No field in the returned entry can be interpreted as an instruction rank.
    assert "instruction_rank" not in got
    assert "instructions" not in got


def test_file_backed_store(tmp_path):
    db = tmp_path / "mem.db"
    store = MemoryStore(db)
    try:
        store.write("task", "k", {"n": 1})
        # A fresh MemoryStore over the same file sees the data.
        store2 = MemoryStore(db)
        try:
            assert store2.get("task", "k")["value"] == {"n": 1}
        finally:
            store2.close()
    finally:
        store.close()