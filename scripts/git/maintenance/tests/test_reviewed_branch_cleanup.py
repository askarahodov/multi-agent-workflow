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
    assert cleanup.TIPS == {
        "qa-sync-test-1792050525": "1f0803be69379ca9ae0fc45583a8a9dc64c82260",
        "test-substance-components-1791965479": "c42b72f109d957f10689ae71a3810859375200ce",
        "test-workflows-1791891554": "3196848c91e6ac567a12e3b79728b3f4ad0ed3c7",
        "wt/t_1fd6385e": "bcda741376023262321b37222e0ee6f84a64e761",
        "wt/t_759fb8e6": "36fc1350a4d2bda507d34c21e513b88759c93763"
    }
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
                "run_id": "123", "purpose": "archive", "batch": cleanup.BATCH}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert cleanup.verify_archive(directory, tip) == manifest
    manifest["batch"] = "completed-first-batch"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="manifest"):
        cleanup.verify_archive(directory, tip)
    manifest["batch"] = cleanup.BATCH
    manifest["purpose"] = "rehearsal"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert cleanup.verify_archive(directory, tip, purpose="rehearsal") == manifest
    with pytest.raises(RuntimeError, match="manifest"):
        cleanup.verify_archive(directory, tip)
    manifest["purpose"] = "archive"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with bundle.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(RuntimeError, match="checksum"):
        cleanup.verify_archive(directory, tip)


def test_rehearsal_cannot_run_on_dispatch_or_foreign_pr(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("GITHUB_REPOSITORY", cleanup.REPO)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    with pytest.raises(RuntimeError, match="Rehearsal requires"):
        cleanup.validate_context(rehearsal=True)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {
        "number": 123, "head": {"repo": {"full_name": "other/repo"}},
        "base": {"repo": {"full_name": cleanup.REPO}, "ref": "main", "sha": "a" * 40}
    }}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/123/merge")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    with pytest.raises(RuntimeError, match="same-repository PR into main"):
        cleanup.validate_context(rehearsal=True)


def test_real_atomic_delete_rejects_stale_lease_without_partial_deletion(tmp_path, monkeypatch):
    import subprocess
    remote = tmp_path / "remote.git"
    repo = tmp_path / "source"
    cleanup.run("git", "init", "--bare", "--initial-branch=main", str(remote))
    cleanup.run("git", "init", "-b", "main", str(repo))
    monkeypatch.chdir(repo)

    def commit(message):
        cleanup.run("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "--allow-empty", "-m", message)
        return cleanup.run("git", "rev-parse", "HEAD").strip()

    main = commit("main")
    cleanup.run("git", "switch", "-c", "fix/first")
    first = commit("first")
    cleanup.run("git", "switch", "-c", "fix/second", "main")
    second = commit("second")
    cleanup.run("git", "remote", "add", "origin", str(remote))
    cleanup.run("git", "push", "origin", "main", "fix/first", "fix/second")
    advanced = commit("concurrent update")
    cleanup.run("git", "push", "origin", "fix/second")
    monkeypatch.setattr(cleanup, "TIPS", {"fix/first": first, "fix/second": second})
    with pytest.raises(subprocess.CalledProcessError):
        cleanup.run(*cleanup.delete_command())
    before = cleanup.refs(cleanup.run("git", "ls-remote", "--heads", "origin"))
    assert before == {"refs/heads/main": main, "refs/heads/fix/first": first,
                      "refs/heads/fix/second": advanced}
    monkeypatch.setattr(cleanup, "TIPS", {"fix/first": first, "fix/second": advanced})
    cleanup.run(*cleanup.delete_command())
    assert cleanup.refs(cleanup.run("git", "ls-remote", "--heads", "origin")) == {
        "refs/heads/main": main
    }


def test_bundle_preserves_disconnected_and_nested_histories(tmp_path, monkeypatch):
    import json
    import subprocess

    repo = tmp_path / "source"
    cleanup.run("git", "init", "-b", "main", str(repo))
    monkeypatch.chdir(repo)

    def commit(message):
        cleanup.run("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "--allow-empty", "-m", message)
        return cleanup.run("git", "rev-parse", "HEAD").strip()

    main = commit("main")
    cleanup.run("git", "switch", "--orphan", "qa-sync-test")
    isolated = commit("independent QA root")
    assert subprocess.run(["git", "merge-base", main, isolated],
                          capture_output=True).returncode == 1
    cleanup.run("git", "switch", "-c", "test-workflows", "main")
    nested = commit("test worktree")
    descendant = commit("test workflow followup")
    monkeypatch.setattr(cleanup, "TIPS", {
        "qa-sync-test": isolated, "wt/t_1234abcd": nested,
        "test-workflows": descendant,
    })
    expected = cleanup.expected_refs(main)
    for ref, sha in expected.items():
        cleanup.run("git", "update-ref", ref, sha)
    directory = tmp_path / "archive"
    directory.mkdir()
    bundle = directory / "branches.bundle"
    cleanup.run("git", "bundle", "create", str(bundle), *expected)
    manifest = {"repository": cleanup.REPO, "baseline": cleanup.BASELINE,
                "main": main, "refs": expected, "sha256": cleanup.digest(bundle),
                "run_id": "456", "purpose": "archive", "batch": cleanup.BATCH}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert cleanup.verify_archive(directory, main) == manifest
