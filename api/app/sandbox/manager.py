"""One E2B sandbox per conversation thread: created lazily, reused, always cleaned up.

Security posture of every sandbox (the code inside is model-written, i.e. untrusted):
  * internet access OFF (`allow_internet_access=False`): no exfiltration, no pip install
  * no secrets: nothing from our environment is passed in (`envs` is never set)
  * short lifetime: the E2B-side timeout kills it even if our process dies
  * per-command timeout: runaway loops are killed, the sandbox stays usable
  * process limit and output cap per command; a sandbox that stops answering is replaced
    (app/sandbox/e2b_backend.py)
  * template `code-interpreter-v1` ships pandas/matplotlib/numpy/scipy, so no network is needed

Lifecycle: created on the first message of a thread (never when merely viewing it), reused for
later turns (files from earlier turns stay available), reconnected after an API restart when its
id is known, killed by the idle reaper and on shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from types import TracebackType
from typing import TYPE_CHECKING

import e2b

from app.config import Settings

if TYPE_CHECKING:  # deepagents is heavy to import; see app/agent/factory.py
    from app.sandbox.e2b_backend import SafeAsyncE2BSandbox

logger = logging.getLogger(__name__)

WORKDIR = "/home/user"
DATA_DIR = f"{WORKDIR}/data"
OUTPUT_DIR = f"{WORKDIR}/outputs"


class SandboxManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sandboxes: dict[str, tuple[e2b.AsyncSandbox, SafeAsyncE2BSandbox]] = {}
        self._last_used: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task[None] | None = None

    async def get(
        self, thread_id: str, *, known_sandbox_id: str | None = None
    ) -> SafeAsyncE2BSandbox:
        """Return this thread's sandbox, creating (or reconnecting to) it on first use."""
        async with self._lock:
            self._last_used[thread_id] = time.monotonic()
            existing = self._sandboxes.get(thread_id)
            if existing is not None:
                raw, backend = existing
                if backend.unhealthy:  # e.g. wedged by a fork bomb: replace it
                    logger.warning("replacing unhealthy sandbox id=%s", raw.sandbox_id)
                    self._sandboxes.pop(thread_id, None)
                    await _kill(raw)
                    known_sandbox_id = None  # do not reconnect to the broken one
                elif await raw.is_running():
                    await raw.set_timeout(self._settings.sandbox_timeout_seconds)
                    return backend
                else:
                    self._sandboxes.pop(thread_id, None)  # expired: fall through and recreate
            reconnected = await self._reconnect(known_sandbox_id) if known_sandbox_id else None
            if reconnected is not None:
                raw = reconnected
            else:
                raw = await e2b.AsyncSandbox.create(
                    template=self._settings.sandbox_template,
                    timeout=self._settings.sandbox_timeout_seconds,
                    allow_internet_access=False,
                    metadata={"app": "sandbox-analyst", "thread_id": thread_id[:60]},
                    api_key=self._settings.secret("e2b_api_key"),
                )
                logger.info("sandbox created id=%s thread=%s", raw.sandbox_id, thread_id)
            from app.sandbox.e2b_backend import SafeAsyncE2BSandbox

            backend = SafeAsyncE2BSandbox(
                sandbox=raw,
                workdir=WORKDIR,
                timeout=self._settings.sandbox_command_timeout_seconds,
            )
            await raw.commands.run(f"mkdir -p {DATA_DIR} {OUTPUT_DIR}", timeout=30)
            self._sandboxes[thread_id] = (raw, backend)
            return backend

    async def _reconnect(self, sandbox_id: str) -> e2b.AsyncSandbox | None:
        """Re-attach to a sandbox that outlived an API restart; None if it is gone."""
        try:
            raw = await e2b.AsyncSandbox.connect(
                sandbox_id,
                timeout=self._settings.sandbox_timeout_seconds,
                api_key=self._settings.secret("e2b_api_key"),
            )
        except Exception:  # not found / expired: the caller creates a fresh one
            return None
        logger.info("sandbox reconnected id=%s", sandbox_id)
        return raw

    def sandbox_id(self, thread_id: str) -> str | None:
        entry = self._sandboxes.get(thread_id)
        return entry[0].sandbox_id if entry else None

    async def close(self, thread_id: str) -> None:
        self._last_used.pop(thread_id, None)
        entry = self._sandboxes.pop(thread_id, None)
        if entry is not None:
            await _kill(entry[0])

    async def close_all(self) -> None:
        self.stop_reaper()
        entries = list(self._sandboxes.values())
        self._sandboxes.clear()
        self._last_used.clear()
        await asyncio.gather(*(_kill(raw) for raw, _ in entries))

    @property
    def active_threads(self) -> list[str]:
        return list(self._sandboxes)

    # ---------------------------------------------------------------- idle reaper
    async def reap_idle(self, idle_seconds: float, *, now: float | None = None) -> list[str]:
        """Kill sandboxes not used for `idle_seconds`. Returns the thread ids reaped."""
        current = time.monotonic() if now is None else now
        stale = [
            t
            for t in list(self._sandboxes)
            if current - self._last_used.get(t, 0.0) >= idle_seconds
        ]
        for thread_id in stale:
            logger.info("reaping idle sandbox thread=%s", thread_id)
            await self.close(thread_id)
        return stale

    def start_reaper(self, interval_seconds: float = 30.0) -> None:
        if self._reaper is not None:
            return

        async def loop() -> None:
            while True:
                await asyncio.sleep(interval_seconds)
                try:
                    await self.reap_idle(self._settings.sandbox_idle_seconds)
                except Exception:  # keep reaping even if one pass fails
                    logger.exception("idle reaper pass failed")

        self._reaper = asyncio.create_task(loop(), name="sandbox-reaper")

    def stop_reaper(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            self._reaper = None

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
    with contextlib.suppress(Exception):  # cleanup must never raise; E2B's timeout is the backstop
        await raw.kill()
        logger.info("sandbox killed id=%s", raw.sandbox_id)
