from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.url_security import UnsafeURLError, safe_request, validate_public_http_url


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://192.0.2.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::]/",
        "http://[ff02::1]/",
        "http://[2001:db8::1]/",
    ],
)
def test_rejects_non_public_ip_destinations(url):
    with pytest.raises(UnsafeURLError, match="non-public"):
        _run(validate_public_http_url(url))


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "https://service.localhost./hook",
        "ftp://example.com/file",
        "https://user:secret@example.com/hook",
    ],
)
def test_rejects_unsafe_url_forms(url):
    with pytest.raises(UnsafeURLError):
        _run(validate_public_http_url(url))


def test_rejects_hostname_when_any_resolved_ip_is_private():
    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34", "10.0.0.2"}),
    ):
        with pytest.raises(UnsafeURLError, match="10.0.0.2"):
            _run(validate_public_http_url("https://example.com/hook"))


def test_accepts_public_ipv4_and_ipv6_dns_answers():
    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"}),
    ):
        assert _run(validate_public_http_url("https://example.com/hook"))


def test_redirect_is_validated_before_second_request():
    redirect = MagicMock(
        status_code=302,
        headers={"location": "http://127.0.0.1/admin"},
    )
    client = MagicMock()
    client.get = AsyncMock(return_value=redirect)

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(side_effect=[{"93.184.216.34"}, {"127.0.0.1"}]),
    ):
        with pytest.raises(UnsafeURLError, match="non-public"):
            _run(safe_request(client, "GET", "https://example.com/start"))

    client.get.assert_awaited_once_with(
        "https://example.com/start", follow_redirects=False
    )


def test_public_relative_redirect_is_followed():
    redirect = MagicMock(status_code=301, headers={"location": "/next"})
    success = MagicMock(status_code=200, headers={})
    client = MagicMock()
    client.get = AsyncMock(side_effect=[redirect, success])

    with patch(
        "src.url_security._resolve_hostname",
        new=AsyncMock(return_value={"93.184.216.34"}),
    ):
        result = _run(safe_request(client, "GET", "https://example.com/start"))

    assert result is success
    assert client.get.await_args_list[1].args == ("https://example.com/next",)
    assert client.get.await_args_list[1].kwargs == {"follow_redirects": False}


@pytest.mark.parametrize("ipv6, allowed", [("2606:4700::1111", True), ("fd00::1", False)])
def test_dns_failure_uses_https_answers_without_accepting_private_addresses(ipv6, allowed):
    """代理可达时恢复解析，同时校验 A 和 AAAA 中的每个地址。"""
    def answer(request):
        kind = request.url.params["type"]
        return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 1 if kind == "A" else 28, "data": "93.184.216.34" if kind == "A" else ipv6}]})

    transport = httpx.MockTransport(answer)
    original = httpx.AsyncClient
    with patch("src.url_security.socket.getaddrinfo", side_effect=socket.gaierror()), patch(
        "src.url_security.httpx.AsyncClient", side_effect=lambda **kwargs: original(transport=transport, **kwargs)
    ):
        if allowed:
            assert _run(validate_public_http_url("https://example.org/article"))
        else:
            with pytest.raises(UnsafeURLError, match="non-public"):
                _run(validate_public_http_url("https://example.org/article"))


def test_https_dns_failure_does_not_allow_unverified_destination():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"Status": 2}))
    original = httpx.AsyncClient
    with patch("src.url_security.socket.getaddrinfo", side_effect=socket.gaierror()), patch(
        "src.url_security.httpx.AsyncClient", side_effect=lambda **kwargs: original(transport=transport, **kwargs)
    ):
        with pytest.raises(UnsafeURLError):
            _run(validate_public_http_url("https://example.org/article"))


def test_slow_system_dns_uses_bounded_https_fallback():
    async def stalled_resolver(*args, **kwargs):
        await asyncio.sleep(10)
    with patch('src.url_security.SYSTEM_DNS_TIMEOUT', 0.01), patch(
        'src.url_security.asyncio.to_thread', new=stalled_resolver
    ), patch('src.url_security._resolve_https', new=AsyncMock(return_value={'93.184.216.34'})) as fallback:
        assert _run(validate_public_http_url('https://example.org/article'))
        fallback.assert_awaited_once_with('example.org')
