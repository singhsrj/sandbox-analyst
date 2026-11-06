"""Our E2B backend: langchain-e2b's sandbox plus a compatibility fix and abuse guards.

1. Compatibility (langchain-e2b 0.0.6 + deepagents 0.6.x): `AsyncE2BSandbox` calls
   `self._map_edit_error(...)` when an `edit_file` fails, but deepagents exposes that helper only as
   a module-level function, so the run crashed with AttributeError. We provide the method. Remove
   it once upstream agrees (tests/sandbox/test_e2b_backend.py fails when it stops being needed).

2. Abuse guards for model-written commands (measured in tests/sandbox/test_abuse_live.py):
   * every command runs under a per-user process limit, so a naive fork bomb fails instead of
     taking the sandbox down (without it, the sandbox stopped answering for good);
   * command output returned to the model is capped (a command printed 3 MB in a probe; that
     would burn the token budget in one step);
   * after a command times out, a quick health check runs; a sandbox that no longer answers is
     marked unhealthy and SandboxManager replaces it on the next turn.
   The guards are not a security boundary (the user has sudo inside the VM). The boundary is the
   VM itself: no network, no secrets, short lifetime, killed when idle.
"""

from __future__ import annotations

from deepagents.backends.protocol import EditResult, ExecuteResponse
from deepagents.backends.sandbox import _map_edit_error
from langchain_e2b import AsyncE2BSandbox

MAX_PROCESSES = 512
MAX_OUTPUT_CHARS = 30_000
HEALTH_TIMEOUT_SECONDS = 8
TIMEOUT_EXIT_CODE = 124


def guarded(command: str) -> str:
    """Prefix a command with the per-user process limit (inherited by everything it starts)."""
    return f"ulimit -u {MAX_PROCESSES} 2>/dev/null; {command}"


def cap_output(output: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    if len(output) <= limit:
        return output, False
    head = output[: limit // 2]
    tail = output[-limit // 4 :]
    note = (
        f"\n\n... [output truncated: {len(output):,} characters in total; showing the first "
        f"{len(head):,} and the last {len(tail):,}. Write large results to a file instead.] ...\n\n"
    )
    return head + note + tail, True


class SafeAsyncE2BSandbox(AsyncE2BSandbox):
    unhealthy: bool = False

    @staticmethod
    def _map_edit_error(error: str, file_path: str, old_string: str) -> EditResult:
        return _map_edit_error(error, file_path, old_string)

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - same signature as the base class
    ) -> ExecuteResponse:
        result = await super().aexecute(guarded(command), timeout=timeout)
        output, truncated = cap_output(result.output)
        if result.exit_code == TIMEOUT_EXIT_CODE and not await self._responds():
            self.unhealthy = True
            output += (
                "\n[The sandbox stopped responding after this command. It will be replaced "
                "with a fresh one on the next turn; files in it are lost.]"
            )
        return ExecuteResponse(
            output=output, exit_code=result.exit_code, truncated=truncated or result.truncated
        )

    async def _responds(self) -> bool:
        probe = await super().aexecute("echo ok", timeout=HEALTH_TIMEOUT_SECONDS)
        return bool(probe.exit_code == 0 and probe.output.strip() == "ok")
