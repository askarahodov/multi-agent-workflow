"""Loopback HTTPS gateway in a separate OS process: verified TLS and durable fences."""
from __future__ import annotations

import asyncio
import os
import socket
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from orchestration_server.attempt_leases import AttemptLeaseService
from test_native_contract_pipeline import runtime, tool


def tls_material(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "server.crt", tmp_path / "server.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    os.chmod(key_path, 0o600)
    return cert_path, key_path


@pytest.mark.asyncio
async def test_real_tls_gateway_subprocess_restart_replay_and_revoke(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(runtime["task"].id, runtime["agent"].id)
    service = AttemptLeaseService(runtime["factory"], ttl_seconds=60)
    lease = await service.issue(attempt.id, runtime["agent"].id)
    db = tmp_path / "orchestration.sqlite3"
    os.chmod(db, 0o600)
    cert, private_key = tls_material(tmp_path)
    gateway_key = tmp_path / "gateway.key"
    gateway_key.write_text("test-gateway-key-unique-12345678901234567890", encoding="ascii")
    os.chmod(gateway_key, 0o600)
    env = {**os.environ,
        "MAW_GATEWAY_WORKSPACE_ROOT": str(runtime["workspace"]),
        "MAW_GATEWAY_ORCHESTRATION_SQLITE": str(db),
        "MAW_GATEWAY_LEDGER_SQLITE": str(runtime["ledger"].path),
        "MAW_GATEWAY_KEY_FILE": str(gateway_key),
    }
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    address = f"https://localhost:{port}"
    payload = {
        "run_id": runtime["run"].id, "task_id": runtime["task"].id,
        "attempt_id": attempt.id, "agent_id": runtime["agent"].id,
        "lease_token": lease.token,
        "event": tool("write_file", "tls-process-once",
                      path="out/tls-process.txt", content="FIRST"),
    }

    async def boot():
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn",
            "agent_management.trusted_fs_gateway:trusted_gateway_from_env",
            "--factory", "--host", "127.0.0.1", "--port", str(port),
            "--ssl-certfile", str(cert), "--ssl-keyfile", str(private_key),
            "--no-proxy-headers",
            env=env, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with httpx.AsyncClient(
                base_url=address, verify=str(cert), trust_env=False,
                timeout=0.5, headers={"X-Gateway-Key": gateway_key.read_text()},
            ) as client:
                for _ in range(60):
                    if process.returncode is not None:
                        raise AssertionError("Gateway exited before serving TLS")
                    try:
                        resp = await client.post("/v1/filesystem/dispatch", json={})
                        if resp.status_code in (400, 401):
                            return process
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        pass
                    await asyncio.sleep(0.1)
            raise AssertionError("Gateway did not start an authenticated TLS listener")
        except BaseException:
            process.terminate()
            await process.wait()
            raise

    async def stop(process):
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=8)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    process = await boot()
    try:
        # TLS trust checks must fail before any model tool is dispatched.
        # A certificate from an independent test CA is not trusted.
        foreign_dir = tmp_path / "untrusted-ca"
        foreign_dir.mkdir()
        untrusted_ca, _ = tls_material(foreign_dir)
        async with httpx.AsyncClient(
            base_url=address, verify=str(untrusted_ca), trust_env=False,
            timeout=3, headers={"X-Gateway-Key": gateway_key.read_text()},
        ) as rejected_client:
            with pytest.raises(httpx.ConnectError):
                await rejected_client.post("/v1/filesystem/dispatch", json=payload)

        # The authorized certificate is valid for localhost only, not IP SAN.
        async with httpx.AsyncClient(
            base_url=f"https://127.0.0.1:{port}", verify=str(cert),
            trust_env=False, timeout=3,
            headers={"X-Gateway-Key": gateway_key.read_text()},
        ) as wrong_hostname_client:
            with pytest.raises(httpx.ConnectError):
                await wrong_hostname_client.post("/v1/filesystem/dispatch", json=payload)

        assert not (runtime["workspace"] / "out" / "tls-process.txt").exists()
        async with httpx.AsyncClient(
            base_url=address, verify=str(cert), trust_env=False,
            headers={"X-Gateway-Key": gateway_key.read_text()},
        ) as client:
            first = await client.post("/v1/filesystem/dispatch", json=payload)
            assert first.status_code == 200 and first.json()["ok"] is True
    finally:
        await stop(process)
    artifact = runtime["workspace"] / "out" / "tls-process.txt"
    assert artifact.read_text() == "FIRST"

    process = await boot()
    try:
        async with httpx.AsyncClient(
            base_url=address, verify=str(cert), trust_env=False,
            headers={"X-Gateway-Key": gateway_key.read_text()},
        ) as client:
            replay = {**payload, "event": tool("write_file", "tls-process-once",
                       path="out/tls-process.txt", content="REPLAY")}
            duplicate = await client.post("/v1/filesystem/dispatch", json=replay)
            assert duplicate.status_code == 200
            assert duplicate.json()["error_code"] == "DUPLICATE_CALL"
            assert artifact.read_text() == "FIRST"
            assert await service.revoke(attempt.id)
            late = {**payload, "event": tool("write_file", "tls-after-revoke",
                    path="out/tls-denied.txt", content="NEVER")}
            denied = await client.post("/v1/filesystem/dispatch", json=late)
            assert denied.json()["error_code"] == "ATTEMPT_FENCED"
            assert not (runtime["workspace"] / "out" / "tls-denied.txt").exists()
    finally:
        await stop(process)
