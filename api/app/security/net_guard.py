"""SSRF guard for users' database hosts.

A user types a host name and the server connects to it. Without a guard that is a way into our
own network: the EC2 metadata service (169.254.169.254, which hands out credentials), the Docker
network the API sits on, localhost, or anything else in the VPC.

Rules:
  * the host must be a syntactically valid DNS name or an IP literal; ports 1024-65535 only
  * we resolve it ourselves, and EVERY address it resolves to must be globally routable
    (no loopback, private, link-local, CGNAT, multicast, reserved or unspecified addresses,
    including IPv4 hidden inside IPv6 such as ::ffff:10.0.0.1 or 2002:0a00::/24)
  * the caller connects to the address we checked (libpq `hostaddr`), never re-resolving the name,
    so DNS rebinding (public at check time, private at connect time) cannot work. The name is
    still used for TLS certificate verification
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable

MIN_PORT, MAX_PORT = 1024, 65535
RESOLVE_TIMEOUT_SECONDS = 5.0

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*\.?$")

Resolver = Callable[[str, int], Awaitable[list[str]]]


class HostNotAllowed(ValueError):
    """The host or port cannot be used. The message is safe to show to the user."""


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    if addr.sixtofour is not None:
        return addr.sixtofour
    if addr.teredo is not None:
        return addr.teredo[1]
    return None


def is_public_address(text: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        addr: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            text.split("%", 1)[0]  # drop an IPv6 zone id
        )
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        inner = _embedded_ipv4(addr)
        if inner is not None and not is_public_address(str(inner)):
            return False
    return bool(
        addr.is_global
        and not addr.is_private
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_multicast
        and not addr.is_reserved
        and not addr.is_unspecified
    )


def check_host_syntax(host: str, port: int) -> str:
    host = host.strip()
    if not (MIN_PORT <= port <= MAX_PORT):
        raise HostNotAllowed(f"Use a port between {MIN_PORT} and {MAX_PORT} (Postgres: 5432).")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if not _HOSTNAME.match(host):
        raise HostNotAllowed("That is not a valid host name.")
    return host.rstrip(".")


async def resolve_public(
    host: str,
    port: int,
    *,
    resolver: Resolver = system_resolver,
    allow_private: bool = False,
) -> str:
    """Return the one address to connect to, or raise HostNotAllowed."""
    host = check_host_syntax(host, port)
    try:
        addresses = await asyncio.wait_for(resolver(host, port), RESOLVE_TIMEOUT_SECONDS)
    except (OSError, TimeoutError) as exc:
        raise HostNotAllowed(f"Could not find the host '{host}'. Check the name.") from exc
    if not addresses:
        raise HostNotAllowed(f"Could not find the host '{host}'. Check the name.")
    if not allow_private and not all(is_public_address(a) for a in addresses):
        raise HostNotAllowed(
            "That host points to a private or reserved network address. Only databases reachable "
            "over the public internet can be connected."
        )
    return addresses[0]
