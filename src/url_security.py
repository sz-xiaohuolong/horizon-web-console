"""SSRF-safe HTTP URL validation and request execution."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

SYSTEM_DNS_TIMEOUT = 2.0


async def _resolve_https(hostname: str) -> set[str]:
    """系统 DNS 不可用时，沿 HTTP 代理查询公网 DNS，仍校验全部地址。"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            async def query(kind: str) -> set[str]:
                response = await client.get(
                    "https://dns.google/resolve",
                    params={"name": hostname, "type": kind, "edns_client_subnet": "0.0.0.0/0"},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("Status") != 0:
                    raise ValueError("DNS 查询未成功")
                return {str(row["data"]) for row in payload.get("Answer", []) if row.get("type") in {1, 28}}

            answers = await asyncio.wait_for(asyncio.gather(query("A"), query("AAAA")), timeout=6.0)
            return set().union(*answers)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, asyncio.TimeoutError) as exc:
        raise UnsafeURLError(f"无法安全解析主机名：{hostname}") from exc


class UnsafeURLError(ValueError):
    """Raised when a URL may target a non-public network resource."""


def validate_http_url(url: str) -> str:
    """Validate the non-network portions of an HTTP(S) URL."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError(f"Invalid URL: {exc}") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURLError("URL must use http or https")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URL must not contain embedded credentials")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeURLError("URL port is out of range")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeURLError("localhost destinations are not allowed")
    return url


async def _resolve_hostname(hostname: str, port: int) -> set[str]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM),
                timeout=SYSTEM_DNS_TIMEOUT,
            )
        except (socket.gaierror, asyncio.TimeoutError):
            return await _resolve_https(hostname)
        return {str(result[4][0]) for result in results}
    return {str(literal)}


async def validate_public_http_url(url: str) -> str:
    """Resolve a URL hostname and require every result to be globally routable."""
    validate_http_url(url)
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    addresses = await _resolve_hostname(
        hostname.rstrip("."), parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    )
    if not addresses:
        raise UnsafeURLError(f"Hostname resolved to no addresses: {hostname}")

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise UnsafeURLError(f"Resolver returned an invalid address: {address}") from exc
        if (
            not ip.is_global
            or ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeURLError(f"Destination resolves to a non-public address: {address}")
    return url


async def safe_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_redirects: int = 10,
    **kwargs,
) -> httpx.Response:
    """Make a request after validating the initial URL and each redirect hop."""
    current_method = method.upper()
    current_url = url
    current_kwargs = kwargs

    for redirect_count in range(max_redirects + 1):
        await validate_public_http_url(current_url)
        request = getattr(client, current_method.lower())
        response = await request(current_url, follow_redirects=False, **current_kwargs)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response

        location = response.headers.get("location")
        if not location:
            return response
        if redirect_count == max_redirects:
            raise UnsafeURLError("Too many redirects")

        current_url = urljoin(current_url, location)
        if response.status_code == 303 or (
            response.status_code in {301, 302} and current_method == "POST"
        ):
            current_method = "GET"
            current_kwargs = {
                key: value
                for key, value in current_kwargs.items()
                if key not in {"content", "data", "files", "json"}
            }

    raise UnsafeURLError("Too many redirects")
