"""Security regression tests for SEC-004: auth_config encryption at rest."""

from __future__ import annotations

import json
import os

import pytest

from agent_management.crypto import decrypt_auth_config, encrypt_auth_config, is_encrypted
from agent_management.services import ProviderService
from agent_management.models import Provider


class TestAuthConfigEncryption:
    """Tests for envelope encryption of provider auth_config."""

    def test_encrypt_decrypt_roundtrip(self):
        """Encryption + decryption returns original plaintext."""
        plaintext = {"api_key": "sk-test-123", "token": "secret-token", "extra": "data"}
        envelope = encrypt_auth_config(plaintext)
        assert is_encrypted(envelope)
        decrypted = decrypt_auth_config(envelope)
        assert decrypted == plaintext

    def test_encrypt_empty_dict_returns_empty(self):
        """Empty plaintext returns empty envelope (no encryption needed)."""
        assert encrypt_auth_config({}) == {}

    def test_decrypt_empty_dict_returns_empty(self):
        """Empty envelope returns empty plaintext."""
        assert decrypt_auth_config({}) == {}

    def test_encrypted_envelope_structure(self):
        """Envelope has expected v1 structure with all required fields."""
        plaintext = {"api_key": "sk-test"}
        envelope = encrypt_auth_config(plaintext)
        assert envelope["v"] == 1
        assert "dek" in envelope
        assert "dek_nonce" in envelope
        assert "nonce" in envelope
        assert "ct" in envelope
        # All values should be base64 strings
        for key in ("dek", "dek_nonce", "nonce", "ct"):
            import base64
            base64.b64decode(envelope[key])  # should not raise

    def test_different_plaintexts_produce_different_ciphertexts(self):
        """Each encryption uses fresh DEK/nonce -> different ciphertexts."""
        plaintext = {"api_key": "same-key"}
        env1 = encrypt_auth_config(plaintext)
        env2 = encrypt_auth_config(plaintext)
        assert env1["ct"] != env2["ct"]
        assert env1["nonce"] != env2["nonce"]
        assert env1["dek"] != env2["dek"]
        # But both decrypt to same plaintext
        assert decrypt_auth_config(env1) == plaintext
        assert decrypt_auth_config(env2) == plaintext

    def test_legacy_plaintext_passthrough(self):
        """Non-envelope dict (legacy/plaintext) is returned as-is for migration."""
        legacy = {"api_key": "plaintext-key"}
        # is_encrypted returns False for non-envelope
        assert not is_encrypted(legacy)
        # decrypt_auth_config passes through
        assert decrypt_auth_config(legacy) == legacy

    def test_wrong_version_raises(self):
        """Envelope with unsupported version raises ValueError."""
        envelope = {"v": 999, "dek": "a", "dek_nonce": "b", "nonce": "c", "ct": "d"}
        with pytest.raises(ValueError, match="Unsupported envelope version"):
            decrypt_auth_config(envelope)


class TestProviderServiceEncryptionIntegration:
    """Integration tests: ProviderService encrypts on write, decrypts in build_adapter."""

    @pytest.mark.asyncio
    async def test_create_provider_encrypts_auth_config(self, harness):
        """Created provider has encrypted auth_config in database."""
        service = harness.service.providers
        provider = await service.create_provider({
            "name": "encrypt-test",
            "type": "openrouter",
            "auth_config": {"api_key": "sk-live-secret", "org_id": "org-123"},
        })
        # Verify stored value is encrypted envelope
        assert is_encrypted(provider.auth_config)
        assert provider.auth_config["v"] == 1

    @pytest.mark.asyncio
    async def test_get_provider_returns_encrypted_not_plaintext(self, harness):
        """get_provider returns Provider with encrypted auth_config (not decrypted)."""
        service = harness.service.providers
        created = await service.create_provider({
            "name": "get-test",
            "type": "mock",
            "auth_config": {"api_key": "should-not-leak"},
        })
        provider = await service.get_provider(created.id)
        # Stored value remains encrypted
        assert is_encrypted(provider.auth_config)

    @pytest.mark.asyncio
    async def test_build_adapter_decrypts_for_use(self, harness):
        """build_adapter receives decrypted auth_config for adapter construction."""
        service = harness.service.providers
        provider = await service.create_provider({
            "name": "adapter-test",
            "type": "mock",
            "auth_config": {"reply": "decrypted-works", "prompt_tokens": 42},
        })
        # build_adapter should work with decrypted config
        adapter = service.build_adapter(provider)
        # MockProvider uses config keys directly
        assert adapter.config.get("reply") == "decrypted-works"
        assert adapter.config.get("prompt_tokens") == 42

    @pytest.mark.asyncio
    async def test_update_provider_re_encrypts_auth_config(self, harness):
        """Updating auth_config re-encrypts with fresh DEK."""
        service = harness.service.providers
        provider = await service.create_provider({
            "name": "update-test",
            "type": "mock",
            "auth_config": {"api_key": "old-key"},
        })
        old_envelope = provider.auth_config

        updated = await service.update_provider(provider.id, {"auth_config": {"api_key": "new-key"}})
        # New envelope should be different (fresh DEK/nonce)
        assert is_encrypted(updated.auth_config)
        assert updated.auth_config["ct"] != old_envelope["ct"]
        assert updated.auth_config["nonce"] != old_envelope["nonce"]

        # Decrypted value should be new
        adapter = service.build_adapter(updated)
        assert adapter.config.get("api_key") == "new-key"

    @pytest.mark.asyncio
    async def test_api_response_excludes_auth_config(self, app):
        """REST API never returns auth_config in responses (envelope or plaintext)."""
        import httpx
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Create provider with auth_config
            r = await client.post("/api/v1/providers", json={
                "name": "api-test",
                "type": "openrouter",
                "auth_config": {"api_key": "sk-secret-should-not-appear"},
            })
            assert r.status_code == 201
            body = r.json()
            # auth_config must not be in response
            assert "auth_config" not in body
            assert "api_key" not in str(body)

            # List also excludes
            r = await client.get("/api/v1/providers")
            assert r.status_code == 200
            for item in r.json()["items"]:
                assert "auth_config" not in item

            # Get single also excludes
            r = await client.get(f"/api/v1/providers/{body['id']}")
            assert r.status_code == 200
            assert "auth_config" not in r.json()

    @pytest.mark.asyncio
    async def test_mock_provider_offline_tests_still_work(self, harness):
        """Existing mock provider offline tests continue to pass."""
        service = harness.service.providers
        provider = await service.create_provider({
            "name": "mock-offline",
            "type": "mock",
            "auth_config": {"reply": "hello", "prompt_tokens": 10, "completion_tokens": 5},
        })
        adapter = service.build_adapter(provider)
        from agent_management.providers import MockProvider
        assert isinstance(adapter, MockProvider)
        result = await adapter.complete([{"role": "user", "content": "hi"}])
        assert result.content == "hello"
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 5


class TestEncryptionKeyRotation:
    """Tests for KEK rotation scenarios."""

    def test_encryption_with_env_key(self, monkeypatch):
        """When AUTH_ENCRYPTION_KEY is set, it is used as KEK."""
        import base64
        # 32-byte key
        test_key = base64.b64encode(b"x" * 32).decode()
        monkeypatch.setenv("AUTH_ENCRYPTION_KEY", test_key)

        # Clear module cache to force re-derivation
        import importlib
        import agent_management.crypto as crypto
        importlib.reload(crypto)

        plaintext = {"api_key": "test-with-env-key"}
        envelope = crypto.encrypt_auth_config(plaintext)
        decrypted = crypto.decrypt_auth_config(envelope)
        assert decrypted == plaintext

    def test_dev_default_kek_works_without_env(self, monkeypatch):
        """Without AUTH_ENCRYPTION_KEY, dev default KEK works (not for production)."""
        monkeypatch.delenv("AUTH_ENCRYPTION_KEY", raising=False)

        import importlib
        import agent_management.crypto as crypto
        importlib.reload(crypto)

        plaintext = {"api_key": "test-dev-default"}
        envelope = crypto.encrypt_auth_config(plaintext)
        decrypted = crypto.decrypt_auth_config(envelope)
        assert decrypted == plaintext