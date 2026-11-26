"""SSRF guard: only globally routable addresses, checked by us, pinned for the connection."""

from __future__ import annotations

import pytest

from app.security.net_guard import HostNotAllowed, is_public_address, resolve_public
from tests.helpers import make_settings

BLOCKED = [
    "127.0.0.1",  # loopback
    "10.1.2.3",
    "172.16.0.5",
    "172.28.0.2",  # the API's own Docker network
    "192.168.1.10",
    "169.254.169.254",  # EC2 instance metadata
    "100.64.0.1",  # carrier-grade NAT
    "0.0.0.0",  # noqa: S104 - an address that must be refused
    "224.0.0.1",  # multicast
    "240.0.0.1",  # reserved
    "255.255.255.255",
    "192.0.2.10",  # documentation range
    "::1",
    "fe80::1",
    "fd00:ec2::254",  # EC2 metadata over IPv6
    "fc00::1",
    "::ffff:10.0.0.1",  # IPv4-mapped private
    "::ffff:169.254.169.254",
    "2002:a00:1::",  # 6to4 wrapping 10.0.0.1
    "2001:0:4136:e378:8000:63bf:f5ff:fffe",  # Teredo wrapping 10.0.0.1
    "not-an-ip",
]
ALLOWED = ["8.8.8.8", "52.66.10.20", "2606:4700:4700::1111", "::ffff:8.8.8.8"]


@pytest.mark.parametrize("address", BLOCKED)
def test_non_public_addresses_are_blocked(address: str) -> None:
    assert not is_public_address(address)


@pytest.mark.parametrize("address", ALLOWED)
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_public_address(address)


def fixed(*addresses: str) -> object:
    async def resolver(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolver


async def test_the_checked_address_is_returned_for_pinning() -> None:
    address = await resolve_public("db.example.com", 5432, resolver=fixed("52.66.10.20"))  # type: ignore[arg-type]
    assert address == "52.66.10.20"


async def test_one_private_answer_among_public_ones_is_enough_to_refuse() -> None:
    # A rebinding-style name that returns both: libpq could pick either, so refuse.
    with pytest.raises(HostNotAllowed, match="private or reserved"):
        await resolve_public(
            "evil.example.com",
            5432,
            resolver=fixed("52.66.10.20", "169.254.169.254"),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "169.254.169.254", "[::1]"])
async def test_obvious_internal_hosts_are_refused_with_the_real_resolver(host: str) -> None:
    with pytest.raises(HostNotAllowed):
        await resolve_public(host, 5432)


@pytest.mark.parametrize(
    "host", ["", "a b.com", "db.example.com/x", "-bad.com", "a" * 64 + ".com", "db;rm.com"]
)
async def test_malformed_host_names_are_refused_before_any_lookup(host: str) -> None:
    async def never(host: str, port: int) -> list[str]:
        raise AssertionError("must not resolve")

    with pytest.raises(HostNotAllowed, match="valid host name"):
        await resolve_public(host, 5432, resolver=never)


@pytest.mark.parametrize("port", [22, 80, 443, 1023, 0, 70000])
async def test_low_and_invalid_ports_are_refused(port: int) -> None:
    with pytest.raises(HostNotAllowed, match="port between"):
        await resolve_public("db.example.com", port, resolver=fixed("8.8.8.8"))  # type: ignore[arg-type]


async def test_unknown_hosts_get_a_clear_message() -> None:
    async def nxdomain(host: str, port: int) -> list[str]:
        raise OSError("Name or service not known")

    with pytest.raises(HostNotAllowed, match="Could not find the host"):
        await resolve_public("nope.example.com", 5432, resolver=nxdomain)


async def test_private_hosts_only_with_the_local_testing_switch() -> None:
    address = await resolve_public(
        "localhost",
        5432,
        resolver=fixed("127.0.0.1"),  # type: ignore[arg-type]
        allow_private=True,
    )
    assert address == "127.0.0.1"


def test_the_local_testing_switch_is_refused_in_production() -> None:
    with pytest.raises(ValueError, match="must not be set in production"):
        make_settings(APP_ENV="prod", ALLOW_PRIVATE_CONNECTION_HOSTS="true")
