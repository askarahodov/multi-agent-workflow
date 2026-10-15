"""Explicit gateway TLS entrypoint must never serve with invalid local state."""
import os

from agent_management import trusted_gateway_serve


def test_gateway_serve_rejects_unconfigured(monkeypatch, capsys):
    monkeypatch.delenv("MAW_TRUSTED_GATEWAY_ENABLED", raising=False)
    assert trusted_gateway_serve.main() == 3
    assert "FAIL_CLOSED" in capsys.readouterr().err


def test_gateway_serve_does_not_invoke_factory_on_bad_state(monkeypatch):
    from agent_management import trusted_gateway_cli, trusted_fs_gateway

    def reject():
        raise ValueError("private-path-should-not-be-revealed")

    monkeypatch.setattr(trusted_gateway_serve, "validate_local_config", reject)
    monkeypatch.setattr(trusted_fs_gateway, "trusted_gateway_from_env",
                        lambda: (_ for _ in ()).throw(AssertionError("factory invoked")))
    assert trusted_gateway_serve.main() == 3


def test_gateway_serve_rejects_factory_failures_without_leaking(monkeypatch, capsys):
    from agent_management import trusted_fs_gateway
    monkeypatch.setattr(trusted_gateway_serve, "validate_local_config", lambda: None)
    monkeypatch.setattr(trusted_fs_gateway, "trusted_gateway_from_env",
                        lambda: (_ for _ in ()).throw(ValueError("sensitive-sqlite-path")))
    assert trusted_gateway_serve.main() == 3
    captured = capsys.readouterr()
    assert "sensitive-sqlite-path" not in captured.out + captured.err
