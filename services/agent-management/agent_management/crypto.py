"""Envelope encryption for provider auth_config at rest.

Encryption model (envelope / hybrid):
- KEK (Key Encryption Key): derived from environment variable AUTH_ENCRYPTION_KEY
  (base64-encoded 32-byte key). Rotated via env; if missing, a development
  default is derived from a fixed salt (NOT for production use).
- DEK (Data Encryption Key): per-provider random 32-byte key, generated on
  first write. Encrypted with KEK and stored alongside ciphertext.
- AEAD: AES-256-GCM (via cryptography.hazmat.primitives.ciphers.aead.AESGCM)
  provides confidentiality + integrity. Nonce is 12 random bytes per encryption.

Storage format (JSON in auth_config column):
{
  "v": 1,
  "dek": "<base64(encrypted_dek)>",
  "nonce": "<base64(nonce)>",
  "ct": "<base64(ciphertext)>",
  "tag": "<base64(auth_tag)>"
}

On read (build_adapter only): decrypt DEK with KEK, then decrypt payload.
On write (create/update): generate new DEK, encrypt payload, encrypt DEK with KEK.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


# Module-level KEK cache (derived once per process)
_KEK: Optional[bytes] = None


def _get_kek() -> bytes:
    """Derive or load the Key Encryption Key (KEK).

    Production: set AUTH_ENCRYPTION_KEY to a base64-encoded 32-byte value.
    Example: `openssl rand -base64 32`

    Development: if not set, derive from a fixed salt (INSECURE, not for prod).
    """
    global _KEK
    if _KEK is not None:
        return _KEK

    env_key = os.environ.get("AUTH_ENCRYPTION_KEY")
    if env_key:
        try:
            _KEK = base64.b64decode(env_key)
            if len(_KEK) != 32:
                raise ValueError("AUTH_ENCRYPTION_KEY must decode to 32 bytes")
            return _KEK
        except Exception as exc:
            raise RuntimeError(f"Invalid AUTH_ENCRYPTION_KEY: {exc}") from exc

    # DEVELOPMENT ONLY: deterministic KEK from fixed salt
    # DO NOT USE IN PRODUCTION - set AUTH_ENCRYPTION_KEY instead
    salt = b"agent-management-dev-salt-v1"
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"auth-config-kek",
    )
    _KEK = hkdf.derive(b"dev-only-not-for-production")
    return _KEK


def _encrypt_dek(dek: bytes) -> tuple[bytes, bytes]:
    """Encrypt a DEK with the KEK using AES-256-GCM.

    Returns (encrypted_dek, nonce).
    """
    kek = _get_kek()
    aesgcm = AESGCM(kek)
    nonce = os.urandom(12)
    # Encrypt DEK with empty associated data
    encrypted = aesgcm.encrypt(nonce, dek, None)
    # AESGCM returns ciphertext || tag concatenated
    return encrypted, nonce


def _decrypt_dek(encrypted_dek: bytes, nonce: bytes) -> bytes:
    """Decrypt a DEK with the KEK using AES-256-GCM."""
    kek = _get_kek()
    aesgcm = AESGCM(kek)
    return aesgcm.decrypt(nonce, encrypted_dek, None)


def encrypt_auth_config(plaintext: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt an auth_config dict for storage.

    Returns the envelope format dict ready for JSON serialization.
    """
    if not plaintext:
        return {}

    # Generate fresh DEK per encryption
    dek = os.urandom(32)
    aesgcm = AESGCM(dek)
    nonce = os.urandom(12)

    # Serialize plaintext to JSON bytes
    pt_bytes = json.dumps(plaintext, sort_keys=True, separators=(",", ":")).encode()

    # Encrypt payload with DEK
    ciphertext = aesgcm.encrypt(nonce, pt_bytes, None)

    # Encrypt DEK with KEK
    encrypted_dek, dek_nonce = _encrypt_dek(dek)

    return {
        "v": 1,
        "dek": base64.b64encode(encrypted_dek).decode(),
        "dek_nonce": base64.b64encode(dek_nonce).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ciphertext).decode(),
    }


def decrypt_auth_config(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt an auth_config envelope back to plaintext dict."""
    if not envelope:
        return {}

    # Support legacy plaintext (v0) for migration
    if "v" not in envelope:
        return envelope  # Assume already plaintext (migration path)

    if envelope.get("v") != 1:
        raise ValueError(f"Unsupported envelope version: {envelope.get('v')}")

    try:
        encrypted_dek = base64.b64decode(envelope["dek"])
        dek_nonce = base64.b64decode(envelope["dek_nonce"])
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["ct"])

        # Decrypt DEK
        dek = _decrypt_dek(encrypted_dek, dek_nonce)

        # Decrypt payload
        aesgcm = AESGCM(dek)
        pt_bytes = aesgcm.decrypt(nonce, ciphertext, None)

        return json.loads(pt_bytes)
    except Exception as exc:
        raise ValueError(f"Failed to decrypt auth_config: {exc}") from exc


def is_encrypted(envelope: Dict[str, Any]) -> bool:
    """Check if a stored value is in encrypted envelope format."""
    return isinstance(envelope, dict) and envelope.get("v") == 1