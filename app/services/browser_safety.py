"""Network and input policy for browser workers.

The browser worker must never be usable as an SSRF proxy into the API host,
cloud metadata endpoints, or a tenant's private network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse


class UnsafeBrowserTarget(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    hostname: str


def _normalize_domain(value: str) -> str:
    return value.strip().lower().rstrip(".")


def domain_is_allowed(hostname: str, allowed_domains: list[str]) -> bool:
    host = _normalize_domain(hostname)
    return any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in (_normalize_domain(item) for item in allowed_domains)
        if allowed
    )


def validate_target_syntax(url: str, allowed_domains: list[str] | None = None) -> ValidatedTarget:
    try:
        parsed = urlparse(url)
        host = _normalize_domain(parsed.hostname or "")
    except Exception as exc:
        raise UnsafeBrowserTarget("Invalid URL") from exc
    if parsed.scheme != "https":
        raise UnsafeBrowserTarget("Browser jobs require HTTPS URLs")
    if not host or parsed.username or parsed.password:
        raise UnsafeBrowserTarget("URL must contain a public hostname and no embedded credentials")
    if parsed.port not in (None, 443):
        raise UnsafeBrowserTarget("Only HTTPS port 443 is allowed")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise UnsafeBrowserTarget("Local network targets are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise UnsafeBrowserTarget("Private, loopback, and reserved IP targets are not allowed")
    if allowed_domains and not domain_is_allowed(host, allowed_domains):
        raise UnsafeBrowserTarget("Target hostname is outside this job's allowlist")
    return ValidatedTarget(url=url, hostname=host)


async def validate_public_target(
    url: str,
    allowed_domains: list[str] | None = None,
    *,
    resolver=None,
) -> ValidatedTarget:
    target = validate_target_syntax(url, allowed_domains)
    resolve = resolver or socket.getaddrinfo
    try:
        records = await asyncio.to_thread(resolve, target.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeBrowserTarget("Target hostname could not be resolved") from exc
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise UnsafeBrowserTarget("Target hostname did not resolve to an address")
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise UnsafeBrowserTarget("Target resolved to an invalid address") from exc
        if not address.is_global:
            raise UnsafeBrowserTarget("Target resolves to a private, loopback, or reserved address")
    return target
