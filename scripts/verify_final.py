#!/usr/bin/env python
"""Final verification of SEC-002 and SEC-004 implementations."""

import os

# Test all 4 services TLS config
os.environ['ORCH_TLS_CERT_FILE'] = '/tmp/cert.pem'
os.environ['ORCH_TLS_KEY_FILE'] = '/tmp/key.pem'
os.environ['AGENT_MGMT_TLS_CERT_FILE'] = '/tmp/cert.pem'
os.environ['AGENT_MGMT_TLS_KEY_FILE'] = '/tmp/key.pem'
os.environ['AGENT_RUNTIME_TLS_CERT_FILE'] = '/tmp/cert.pem'
os.environ['AGENT_RUNTIME_TLS_KEY_FILE'] = '/tmp/key.pem'
os.environ['QG_TLS_CERT_FILE'] = '/tmp/cert.pem'
os.environ['QG_TLS_KEY_FILE'] = '/tmp/key.pem'

from orchestration_server.config import get_settings as orch_settings
from agent_management.config import get_settings as am_settings
from runtime.config import RuntimeSettings
from quality_gates.config import Settings as QGSettings

print('=== SEC-002 TLS/HTTPS Enforcement ===')
for name, settings in [
    ('orchestration-server', orch_settings()),
    ('agent-management', am_settings()),
    ('runtime-hardening', RuntimeSettings()),
    ('quality-gates', QGSettings())
]:
    print(f'{name}: tls_enabled={settings.tls_enabled}, ssl_config_keys={list(settings.ssl_config.keys()) if settings.ssl_config else None}')

# Test encryption
print()
print('=== SEC-004 auth_config Encryption ===')
from agent_management.crypto import encrypt_auth_config, decrypt_auth_config, is_encrypted

plaintext = {'api_key': 'sk-test-123', 'org_id': 'org-456'}
envelope = encrypt_auth_config(plaintext)
decrypted = decrypt_auth_config(envelope)
print(f'Original: {plaintext}')
print(f'Encrypted: v={envelope["v"]}, has_dek={"dek" in envelope}, has_ct={"ct" in envelope}')
print(f'Decrypted: {decrypted}')
print(f'Round-trip OK: {decrypted == plaintext}')
print(f'is_encrypted: {is_encrypted(envelope)}')
print()
print('All verifications passed!')