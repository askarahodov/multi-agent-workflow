"""Real-Docker smoke for the opt-in QA executor (no provider credentials).

This does not test the signed QA control-plane or prove a hostile-code sandbox.
"""
from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Load this leaf module without importing the full quality_gates package,
# which otherwise requires the API/SQLAlchemy test dependencies.
_module = runpy.run_path(
    str(ROOT / "quality-gates" / "quality_gates" / "isolated_tester.py")
)
isolated_test = _module["isolated_test"]
SandboxError = _module["SandboxError"]


def main() -> int:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker executable required")
    # CI pulls a trusted base image first. Use its immutable local image ID,
    # rather than allowing a mutable tag in the test invocation.
    subprocess.run([docker, "pull", "python:3.12-slim"], check=True, timeout=180)
    image = subprocess.check_output(
        [docker, "image", "inspect", "--format={{.Id}}", "python:3.12-slim"],
        text=True, timeout=15,
    ).strip()
    probe = """
import os, pathlib, socket
assert os.geteuid() == 65534
assert not pathlib.Path('/run/secrets').exists()
try:
    pathlib.Path('/src/should-not-write').write_text('BAD')
except OSError:
    pass
else:
    raise AssertionError('checkout unexpectedly writable')
p = pathlib.Path('/tmp/qa-probe')
p.write_text('ok')
assert p.read_text() == 'ok'
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not any(k.startswith(('AWS_', 'OPENROUTER_', 'MAW_', 'QG_'))
               for k in os.environ)
assert pathlib.Path('/proc/net/route').read_text().count('eth0') == 0
print('ISOLATED_QA_DOCKER_SMOKE_OK')
"""
    with tempfile.TemporaryDirectory(prefix="maw-docker-smoke-") as tmp:
        # Keep a fake QA signing secret outside the only allowed source mount.
        # Verify the test container cannot read the host-side secret path.
        secret = Path(tmp).parent / (Path(tmp).name + "-qa-signing-secret")
        secret.write_text("FAKE_QA_SIGNING_SECRET_FOR_ISOLATION_TEST")
        secret.chmod(0o600)
        try:
            return run_checks(Path(tmp), secret, image, docker, probe)
        finally:
            secret.unlink(missing_ok=True)


def run_checks(checkout: Path, host_secret: Path, image: str, docker: str, probe: str) -> int:
    probe += f"""
assert not pathlib.Path({str(host_secret)!r}).exists()
"""
    result = isolated_test(
        ("python", "-c", probe), checkout, image,
        docker=docker, timeout=45,
    )
    if result.returncode != 0 or "ISOLATED_QA_DOCKER_SMOKE_OK" not in result.stdout:
        print(json.dumps({
            "exit": result.returncode,
            "stdout_tail": result.stdout[-500:],
            "stderr_tail": result.stderr[-500:],
        }))
        return 1
    print("ISOLATED_QA_DOCKER_SMOKE_OK")

    def qa_containers() -> set[str]:
        output = subprocess.check_output(
            [docker, "ps", "-a", "--filter", "name=maw-qa-", "--format={{.Names}}"],
            text=True, timeout=15,
        )
        return set(output.splitlines())

    before = qa_containers()
    try:
        isolated_test(
            ("python", "-c", "import time; time.sleep(30)"),
            checkout, image, docker=docker, timeout=4,
        )
    except SandboxError as exc:
        if "timed out and container removed" not in str(exc):
            raise
    else:
        raise AssertionError("Sandbox test unexpectedly completed before timeout")
    if qa_containers() - before:
        raise RuntimeError("Timed-out QA containers remain; cleanup failed")
    print("ISOLATED_QA_DOCKER_TIMEOUT_CLEANUP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
