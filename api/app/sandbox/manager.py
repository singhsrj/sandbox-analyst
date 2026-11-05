"""One E2B sandbox per conversation thread: created lazily, reused, always cleaned up.

Security posture of every sandbox (the code inside is model-written, i.e. untrusted):
  * internet access OFF (`allow_internet_access=False`): no exfiltration, no pip install
  * no secrets: nothing from our environment is passed in (`envs` is never set)
  * short lifetime: the E2B-side timeout kills it even if our process dies
  * per-command timeout: runaway loops are killed, the sandbox stays usable
  * template `code-interpreter-v1` ships pandas/matplotlib/numpy/scipy, so no network is needed
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType

import e2b

from app.config import Settings
from app.sandbox.e2b_backend import SafeAsyncE2BSandbox

logger = logging.getLogger(__name__)

WORKDIR = "/home/user"
DATA_DIR = f"{WORKDIR}/data"
OUTPUT_DIR = f"{WORKDIR}/outputs"


class SandboxManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sandboxes: dict[str, tuple[e2b.AsyncSandbox, SafeAsyncE2BSandbox]] = {}
        self._lock = asyncio.Lock()

    async def get(self, thread_id: str) -> SafeAsyncE2BSandbox:
        """Return this thread's sandbox, creating it on first use and extending its lifetime."""
        async with self._lock:
            existing = self._sandboxes.get(thread_id)
            if existing is not None:
                raw, backend = existing
                if await raw.is_running():
                    await raw.set_timeout(self._settings.sandbox_timeout_seconds)
                    return backend
                self._sandboxes.pop(thread_id, None)  # expired: fall through and recreate
            raw = await e2b.AsyncSandbox.create(
                template=self._settings.sandbox_template,
                timeout=self._settings.sandbox_timeout_seconds,
                allow_internet_access=False,
                metadata={"app": "sandbox-analyst", "thread_id": thread_id[:60]},
                api_key=self._settings.secret("e2b_api_key"),
            )
            backend = SafeAsyncE2BSandbox(
                sandbox=raw,
                workdir=WORKDIR,
                timeout=self._settings.sandbox_command_timeout_seconds,
            )
            await raw.commands.run(f"mkdir -p {DATA_DIR} {OUTPUT_DIR}", timeout=30)
            self._sandboxes[thread_id] = (raw, backend)
            logger.info("sandbox created id=%s thread=%s", raw.sandbox_id, thread_id)
            return backend

    async def close(self, thread_id: str) -> None:
        entry = self._sandboxes.pop(thread_id, None)
        if entry is not None:
            await _kill(entry[0])

    async def close_all(self) -> None:
        entries = list(self._sandboxes.values())
        self._sandboxes.clear()
        await asyncio.gather(*(_kill(raw) for raw, _ in entries))

    @property
    def active_threads(self) -> list[str]:
        return list(self._sandboxes)

    async def __aenter__(self) -> SandboxManager:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close_all()


async def _kill(raw: e2b.AsyncSandbox) -> None:
    try:
        await raw.kill()
        logger.info("sandbox killed id=%s", raw.sandbox_id)
    except Exception:  # cleanup must never raise; the E2B-side timeout is the backstop
        logger.exception("failed to kill sandbox id=%s", raw.sandbox_id)
