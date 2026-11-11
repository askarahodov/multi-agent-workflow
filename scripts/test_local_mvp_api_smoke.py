"""No-network proxy isolation regression for the local API smoke (#312)."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from scripts import local_mvp_api_smoke as smoke


class LoopbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/v1/failure":
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"secret":"REDACT_THIS"}')
            return
        if self.path == "/api/v1/redirect":
            self.send_response(302)
            self.send_header("Location", "https://example.invalid/outside")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"source":"direct-loopback"}')

    def log_message(self, *_args):
        pass


@pytest.fixture
def loopback_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_loopback_bypasses_broken_corporate_proxy(monkeypatch, loopback_server):
    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    for key in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(key, "")
    assert smoke.request(loopback_server, "GET", "/success") == {
        "source": "direct-loopback",
    }
    with pytest.raises(AssertionError, match="GET /failure: HTTP 503, expected 200") as exc:
        smoke.request(loopback_server, "GET", "/failure")
    assert "REDACT_THIS" not in str(exc.value)
    with pytest.raises(AssertionError, match="GET /redirect: HTTP 302, expected 200"):
        smoke.request(loopback_server, "GET", "/redirect")


def test_remote_host_uses_standard_urllib_opening(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"via":"standard"}'

    calls = []

    def fake_urlopen(req, *, timeout):
        calls.append((req.full_url, timeout))
        return Response()

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    assert smoke.request("https://example.invalid", "GET", "/x") == {
        "via": "standard",
    }
    assert calls == [("https://example.invalid/api/v1/x", 12)]


def test_http_assertion_reports_status_without_response_secrets(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "main", lambda: (
        (_ for _ in ()).throw(AssertionError("POST /projects: HTTP 503, expected 201"))
    ))
    assert smoke.entrypoint() == 1
    assert "POST /projects: HTTP 503, expected 201" in capsys.readouterr().err


def test_unexpected_assertion_and_proxy_error_messages_are_redacted(monkeypatch, capsys):
    for error in (
        AssertionError("request https://PROXY-SECRET@example.invalid/failed"),
        OSError("proxy://PROXY-SECRET@example.invalid"),
    ):
        def fail(error=error):
            raise error

        monkeypatch.setattr(smoke, "main", fail)
        assert smoke.entrypoint() == 1
        printed = capsys.readouterr().err
        assert "PROXY-SECRET" not in printed
