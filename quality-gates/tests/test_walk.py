"""Tests for the shared workspace traversal helper (``walk.iter_files``).

These lock in the fix for venv-scan pollution: a virtualenv, VCS metadata or
verification-scratch dir anywhere in the scanned tree must be pruned *during*
traversal (``os.walk`` ``dirnames`` mutation), so it can neither slow the scan
nor poison a gate's findings.
"""

from __future__ import annotations

from quality_gates.gates.walk import iter_files


def _make_tree(root) -> None:
    (root / "app.py").write_text("print('hi')\n")
    (root / "src").mkdir()
    (root / "src" / "mod.py").write_text("x = 1\n")
    # a virtualenv nested inside a verification scratch dir
    (root / ".verify" / "v" / "venv" / "lib" / "python3.12" / "site-packages").mkdir(
        parents=True
    )
    (root / ".verify" / "v" / "venv" / "lib" / "python3.12" / "site-packages" / "evil.py").write_text(
        "SECRET = 'AKIA' + 'X' * 16\n"
    )
    # a standalone virtualenv at the root (the common case)
    (root / "venv").mkdir()
    (root / "venv" / "bin").mkdir()
    (root / "venv" / "bin" / "activate").write_text("echo spam\n")
    # a .git dir and VCS metadata
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    # an egg-info dir (matched by suffix rule)
    (root / "demo.egg-info").mkdir()
    (root / "demo.egg-info" / "PKG-INFO").write_text("Metadata-Version: 2.1\n")
    # bytecode cache
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.cpython-312.pyc").write_text("\x00")


def test_iter_files_prunes_venv_verify_git_and_egg_info(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    _make_tree(root)
    files = {str(p.relative_to(root)) for p in iter_files(root)}
    assert "app.py" in files
    assert "src/mod.py" in files
    # pruned subtrees are never descended into
    assert not any(f.startswith(".verify") for f in files)
    assert not any("site-packages" in f for f in files)
    assert not any(f.startswith("venv") for f in files)
    assert not any(f.startswith(".git") for f in files)
    assert not any("egg-info" in f for f in files)
    assert not any("__pycache__" in f for f in files)


def test_iter_files_exts_filter(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.py").write_text("x\n")
    (root / "b.ts").write_text("y\n")
    (root / "c.txt").write_text("z\n")
    py = {p.name for p in iter_files(root, exts={".py"})}
    assert py == {"a.py"}
