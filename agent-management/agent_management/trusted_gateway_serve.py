"""Explicit TLS-only trusted gateway server. No network on import."""
from __future__ import annotations

import os
import sys

from .trusted_gateway_cli import validate_local_config


def main() -> int:
    try:
        validate_local_config()
        from .trusted_fs_gateway import trusted_gateway_from_env
        app = trusted_gateway_from_env()
        import uvicorn
        uvicorn.run(
            app, host="0.0.0.0", port=9443,
            ssl_certfile=os.environ["MAW_GATEWAY_TLS_CERT_FILE"],
            ssl_keyfile=os.environ["MAW_GATEWAY_TLS_KEY_FILE"],
            proxy_headers=False, server_header=False,
        )
    except (ValueError, OSError, RuntimeError, KeyError):
        print("Trusted gateway FAIL_CLOSED: check protected TLS/state", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
