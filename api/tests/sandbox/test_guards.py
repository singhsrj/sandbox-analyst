"""The sandbox abuse guards, without a real sandbox."""

from __future__ import annotations

from typing import Any

import pytest
from deepagents.backends.protocol import ExecuteResponse
from langchain_e2b import AsyncE2BSandbox

from app.sandbox.e2b_backend import (
    MAX_OUTPUT_CHARS,
    MAX_PROCESSES,
    SafeAsyncE2BSandbox,
    cap_output,
    guarded,
)


def test_commands_run_under_a_process_limit() -> None:
    assert guarded("python3 a.py") == f"ulimit -u {MAX_PROCESSES} 2>/dev/null; python3 a.py"


def test_short_output_is_untouched_and_long_output_keeps_head_and_tail() -> None:
    assert cap_output("hello") == ("hello", False)
    text = "H" * 50_000 + "T" * 50_000
    capped, truncated = cap_output(text)
    assert truncated and capped.startswith("H") and capped.endswith("T")
    assert "100,000 characters in total" in capped and len(capped) < MAX_OUTPUT_CHARS + 300


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Make the upstream aexecute return scripted responses; record the commands it got."""
    script: list[Any] = []

    async def fake(
        self: Any,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - mirrors the real signature
    ) -> ExecuteResponse:
        script.append(command)
        response: ExecuteResponse = responses.pop(0)
        return response

    responses: list[ExecuteResponse] = []
    monkeypatch.setattr(AsyncE2BSandbox, "aexecute", fake)
    script.append(responses)  # index 0: the queue to fill
    return script


def make_sandbox() -> SafeAsyncE2BSandbox:
    return SafeAsyncE2BSandbox.__new__(SafeAsyncE2BSandbox)  # no real sandbox needed


async def test_a_timeout_with_a_dead_sandbox_marks_it_unhealthy(scripted: list[Any]) -> None:
    queue = scripted[0]
    queue += [
        ExecuteResponse(output="Command timed out after 5 seconds", exit_code=124),
        ExecuteResponse(output="Command timed out after 8 seconds", exit_code=124),  # health
    ]
    sandbox = make_sandbox()
    result = await sandbox.aexecute("bomb", timeout=5)
    assert sandbox.unhealthy and "replaced with a fresh one" in result.output
    assert scripted[1].endswith("bomb") and scripted[2].endswith("echo ok")


async def test_a_timeout_with_a_healthy_sandbox_is_just_a_timeout(scripted: list[Any]) -> None:
    scripted[0] += [
        ExecuteResponse(output="Command timed out after 5 seconds", exit_code=124),
        ExecuteResponse(output="ok\n", exit_code=0),
    ]
    sandbox = make_sandbox()
    result = await sandbox.aexecute("python3 -c 'while True: pass'", timeout=5)
    assert not sandbox.unhealthy and result.exit_code == 124


async def test_large_output_is_capped_and_flagged(scripted: list[Any]) -> None:
    scripted[0].append(ExecuteResponse(output="x" * 200_000, exit_code=0))
    result = await make_sandbox().aexecute("cat big.csv")
    assert result.truncated and len(result.output) < MAX_OUTPUT_CHARS + 300
