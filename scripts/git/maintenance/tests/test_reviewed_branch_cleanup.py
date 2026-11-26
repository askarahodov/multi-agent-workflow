import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "reviewed_cleanup", Path(__file__).resolve().parents[1] / "archive-reviewed-branches.py",
)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def snapshot():
    main = "f" * 40
    remote = {"refs/heads/" + n: s for n, s in {**cleanup.TIPS, "main": main}.items()}
    branches = [{"name": n, "protected": n == "main", "commit": {"sha": s}}
                for n, s in {**cleanup.TIPS, "main": main}.items()]
    return branches, [], remote, main


def test_exact_snapshot():
    cleanup.validate_snapshot(*snapshot())


@pytest.mark.parametrize("change", ["main", "tip", "missing", "protected", "head", "base"])
def test_stale_or_active_snapshot_refused(change):
    branches, prs, remote, main = snapshot()
    name = next(iter(cleanup.TIPS))
    row = next(b for b in branches if b["name"] == name)
    if change == "main":
        remote["refs/heads/main"] = "a" * 40
    elif change == "tip":
        remote["refs/heads/" + name] = "a" * 40
    elif change == "missing":
        remote.pop("refs/heads/" + name)
    elif change == "protected":
        row["protected"] = True
    else:
        pr = {"state": "open", "head": {"repo": {"full_name": cleanup.REPO}, "ref": "other"},
              "base": {"repo": {"full_name": cleanup.REPO}, "ref": "main"}}
        pr[change]["ref"] = name
        prs.append(pr)
    with pytest.raises(RuntimeError):
        cleanup.validate_snapshot(branches, prs, remote, main)


def test_atomic_exact_delete_only():
    cmd = cleanup.delete_command()
    assert "--atomic" in cmd
    assert len(cleanup.TIPS) == 10
    assert set(x for x in cmd if x.startswith(":refs/heads/")) == {
        ":refs/heads/" + n for n in cleanup.TIPS
    }
    assert set(x for x in cmd if x.startswith("--force-with-lease=")) == {
        f"--force-with-lease=refs/heads/{n}:{s}" for n, s in cleanup.TIPS.items()
    }
    assert all(not n.startswith(("release/", "hotfix/", "coord/")) and n != "main"
               for n in cleanup.TIPS)


@pytest.mark.parametrize("event,ref", [("pull_request", "refs/heads/main"),
                                      ("schedule", "refs/heads/main"),
                                      ("workflow_dispatch", "refs/heads/feature")])
def test_write_context_fails_closed(monkeypatch, event, ref):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("GITHUB_REPOSITORY", cleanup.REPO)
    with pytest.raises(RuntimeError, match="manual dispatch"):
        cleanup.validate_context()


def test_apply_requires_explicit_confirmation(tmp_path):
    with pytest.raises(RuntimeError, match="confirmation"):
        cleanup.apply(tmp_path, "a" * 40, "123", "yes")


def test_bundle_recoverable_without_source_objects(tmp_path, monkeypatch):
    import json
    repo = tmp_path / "source"
    cleanup.run("git", "init", "-b", "main", str(repo))
    monkeypatch.chdir(repo)
    cleanup.run("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-m", "test baseline")
    tip = cleanup.run("git", "rev-parse", "HEAD").strip()
    monkeypatch.setattr(cleanup, "TIPS", {"fix/example": tip})
    expected = cleanup.expected_refs(tip)
    for ref, sha in expected.items():
        cleanup.run("git", "update-ref", ref, sha)
    directory = tmp_path / "archive"
    directory.mkdir()
    bundle = directory / "branches.bundle"
    cleanup.run("git", "bundle", "create", str(bundle), *expected)
    manifest = {"repository": cleanup.REPO, "baseline": cleanup.BASELINE,
                "main": tip, "refs": expected, "sha256": cleanup.digest(bundle),
                "run_id": "123"}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert cleanup.verify_archive(directory, tip) == manifest
    with bundle.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(RuntimeError, match="checksum"):
        cleanup.verify_archive(directory, tip)
