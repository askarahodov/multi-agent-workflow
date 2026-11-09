"""Regression checks for the read-only P0 onboarding preflight."""
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import urlsplit


from scripts.check_onboarding_health import CHECKS, probe, validate_base_url


class Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = BytesIO(body)

    def read(self, limit: int) -> bytes:
        return self._body.read(limit)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_all_backend_lists_are_checked_through_one_origin():
    urls = []

    def opener(req, *, timeout):
        assert timeout == 5
        urls.append(req.full_url)
        kind = next(k for _, path, k in CHECKS if req.full_url.endswith(path))
        return Response(200, b'[]' if kind == 'list' else b'{"items":[]}')

    success, report = probe('http://127.0.0.1:5173', opener=opener)
    assert success
    assert len(urls) == len(CHECKS)
    assert all(url.startswith('http://127.0.0.1:5173/api/v1/') for url in urls)
    assert all('PASS' in line for line in report)


def test_one_500_is_reported_without_leaking_upstream_details():
    secret = 'SENSITIVE-API-KEY-CANARY'

    def opener(req, *, timeout):
        if req.full_url.endswith('/providers'):
            raise HTTPError(req.full_url, 500, 'server ' + secret, {}, None)
        kind = next(k for _, path, k in CHECKS if req.full_url.endswith(path))
        return Response(200, b'[]' if kind == 'list' else b'{"items":[]}')

    success, report = probe('http://localhost:5173', opener=opener)
    assert not success
    assert len(report) == len(CHECKS)
    assert sum('FAIL HTTP 500' in line for line in report) == 1
    assert secret not in '\n'.join(report)


def test_proxy_html_200_cannot_masquerade_as_backend_success():
    success, report = probe('http://localhost:5173', opener=lambda req, timeout: Response(200, b'<html>spa</html>'))
    assert not success
    assert all('invalid JSON' in line for line in report)


def test_preflight_rejects_untrusted_or_sensitive_target_urls():
    urls = (
        'https://example.com', 'http://localhost:5173/api/v1',
        'http://user:password@localhost:5173',
        'http://localhost:5173/?api_key=SECRET',
        'file:///etc/passwd', 'http://localhost:badport',
    )
    for url in urls:
        try:
            validate_base_url(url)
        except ValueError:
            continue
        raise AssertionError("unsafe URL was accepted")

if __name__ == '__main__':
    test_all_backend_lists_are_checked_through_one_origin()
    test_one_500_is_reported_without_leaking_upstream_details()
    test_proxy_html_200_cannot_masquerade_as_backend_success()
    test_preflight_rejects_untrusted_or_sensitive_target_urls()
    print('Onboarding preflight regressions: PASS')
