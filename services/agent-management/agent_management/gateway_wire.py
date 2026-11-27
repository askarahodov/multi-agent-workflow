"""Strict JSON decoding for the existing private trusted gateway wire boundary.

The caller still validates identity, lease, operation shape and authorization.
No schema version, endpoint, credentials, or capability is introduced here.
"""
from __future__ import annotations

import json
from typing import Any


def decode_gateway_json(data: bytes | str) -> Any:
    """Reject ambiguous JSON, including nested duplicate keys and nonfinite values."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate gateway field")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("Nonfinite gateway value")

    try:
        return json.loads(data, object_pairs_hook=unique, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise ValueError("Invalid gateway JSON") from None
