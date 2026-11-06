"""Sandbox abuse tests against the REAL E2B sandbox (skipped without an E2B key).

What model-written code might try, and what we require to happen:
  * exfiltrate data: DNS, HTTP and HTTPS by hostname or raw IP, UDP DNS by IP -> nothing gets out
  * read our secrets: no secret VALUE (not just name) appears anywhere in the sandbox environment
  * exhaust memory / disk -> the attempt fails and the sandbox keeps working
  * fork bomb -> stopped by the process limit; the sandbox keeps working
  * flood the output -> the model gets a capped, clearly marked excerpt
  * a sandbox that stops answering -> marked unhealthy and replaced on the next turn

Probe notes (2026-11-06): raw TCP connects to public IPs are ACCEPTED by E2B's local egress proxy
but no request or response passes (HTTP: empty reply, TLS: EOF). The tests therefore check what
matters, that no application traffic gets through, instead of the TCP handshake.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.config import get_settings
from app.sandbox.e2b_backend import MAX_OUTPUT_CHARS, SafeAsyncE2BSandbox
from app.sandbox.manager import SandboxManager

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(get_settings().e2b_api_key is None, reason="E2B key not configured"),
]


@pytest.fixture
async def manager() -> AsyncIterator[SandboxManager]:
    async with SandboxManager(get_settings()) as m:
        yield m


@pytest.fixture
async def sandbox(manager: SandboxManager) -> SafeAsyncE2BSandbox:
    return await manager.get("test-abuse")


@pytest.mark.parametrize(
    "command",
    [
        "getent hosts example.com",
        "curl -sS -m 6 https://example.com",
        "curl -sS -m 6 -k https://1.1.1.1/",
        "curl -sS -m 6 http://1.1.1.1/",
        "python3 -c \"import urllib.request; urllib.request.urlopen('http://1.1.1.1/', timeout=5)\"",
        # a raw UDP DNS query to a public resolver must get no answer
        'python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); '
        "s.settimeout(4); s.sendto(bytes.fromhex('abcd0100000100000000000007657861"
        "6d706c6503636f6d0000010001'), ('8.8.8.8', 53)); s.recvfrom(512)\"",
    ],
)
async def test_no_application_traffic_leaves_the_sandbox(
    sandbox: SafeAsyncE2BSandbox, command: str
) -> None:
    result = await sandbox.aexecute(command, timeout=15)
    assert result.exit_code != 0, result.output


async def test_no_secret_value_is_visible_anywhere_in_the_sandbox(
    sandbox: SafeAsyncE2BSandbox,
) -> None:
    settings = get_settings()
    secrets = [
        getattr(settings, name).get_secret_value()
        for name in (
            "bedrock_api_key",
            "groq_api_key",
            "e2b_api_key",
            "analyst_database_url",
            "app_database_url",
            "admin_database_url",
            "langfuse_secret_key",
            "langfuse_public_key",
            "demo_access_code",
            "session_token_secret",
        )
        if getattr(settings, name) is not None
    ]
    assert secrets, "no secrets configured: the test would prove nothing"
    dump = await sandbox.aexecute(
        "env; cat /proc/*/environ 2>/dev/null | tr '\\0' '\\n'; "
        "ls -la /home/user; cat /home/user/.bashrc /home/user/.profile 2>/dev/null",
        timeout=30,
    )
    for value in secrets:
        assert value not in dump.output
        assert value[:12] not in dump.output  # not even a prefix


async def test_memory_and_disk_exhaustion_fail_and_the_sandbox_survives(
    sandbox: SafeAsyncE2BSandbox,
) -> None:
    memory = await sandbox.aexecute("python3 -c 'bytearray(64 * 1024**3)'", timeout=30)
    assert memory.exit_code != 0 and "MemoryError" in memory.output
    disk = await sandbox.aexecute("fallocate -l 500G /home/user/fill", timeout=30)
    assert disk.exit_code != 0 and "No space left" in disk.output
    await sandbox.aexecute("rm -f /home/user/fill")
    assert (await sandbox.aexecute("echo alive")).output.strip() == "alive"


async def test_a_fork_bomb_is_stopped_and_the_sandbox_survives(
    sandbox: SafeAsyncE2BSandbox,
) -> None:
    bomb = await sandbox.aexecute("timeout 10 bash -c 'f(){ f | f & }; f'; sleep 2", timeout=40)
    assert not sandbox.unhealthy, bomb.output
    assert (await sandbox.aexecute("echo alive", timeout=20)).output.strip() == "alive"


async def test_huge_output_is_capped_before_it_reaches_the_model(
    sandbox: SafeAsyncE2BSandbox,
) -> None:
    flood = await sandbox.aexecute("head -c 3000000 /dev/zero | tr '\\0' 'a'", timeout=60)
    assert flood.truncated and len(flood.output) < MAX_OUTPUT_CHARS + 500
    assert "output truncated: 3,000,000 characters" in flood.output


async def test_an_unresponsive_sandbox_is_replaced_on_the_next_turn(
    manager: SandboxManager, sandbox: SafeAsyncE2BSandbox
) -> None:
    first_id = manager.sandbox_id("test-abuse")
    sandbox.unhealthy = True  # what a timed-out command plus a failed health check sets
    replacement = await manager.get("test-abuse")
    assert replacement is not sandbox and manager.sandbox_id("test-abuse") != first_id
    assert (await replacement.aexecute("echo fresh")).output.strip() == "fresh"
