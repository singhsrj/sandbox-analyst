"""Orchestrates one chat turn: agent run -> UI stream -> persisted run record.

Pre-flight (`prepare`) runs BEFORE the HTTP response starts so problems become proper status
codes (404 / 409 / 429). Everything after that is reported inside the stream as an `error` chunk,
because the 200 response has already begun.

Cleanup guarantees: whatever happens (success, error, budget stop, client disconnect), the run
is persisted, output files are collected, and the Langfuse trace is flushed. Sandboxes stay alive
for the next turn of the thread and are reaped when idle or on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.factory import build_agent
from app.agent.loop import AgentDriver
from app.agent.models import get_model
from app.agent.outputs import collect_outputs, unverified_file_claims
from app.agent.usage import BudgetExceeded, StepLimitExceeded, UsageTracker
from app.artifacts import ArtifactStore
from app.config import ModelProvider, Settings
from app.db.app_store import AppStore, ThreadInfo
from app.observability import finalize_trace, make_handler
from app.sandbox.manager import SandboxManager
from app.streaming.adapter import Chunk, UIStreamAdapter, coalesce

logger = logging.getLogger(__name__)


class ThreadBusy(RuntimeError):
    """A run is already in progress for this thread."""


class ServerBusy(RuntimeError):
    """Too many runs are in progress overall."""


@dataclass(frozen=True)
class PreparedTurn:
    thread: ThreadInfo
    owner_id: str
    question: str
    provider: ModelProvider
    model: str


def artifact_url(thread_id: str, name: str) -> str:
    return f"/api/threads/{thread_id}/artifacts/{name}"


class ChatService:
    def __init__(
        self,
        settings: Settings,
        store: AppStore,
        sandboxes: SandboxManager,
        checkpointer: BaseCheckpointSaver[Any] | None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._sandboxes = sandboxes
        self._checkpointer = checkpointer
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._active = 0

    @property
    def active_runs(self) -> int:
        return self._active

    # ------------------------------------------------------------------ pre-flight
    async def prepare(
        self,
        *,
        thread_id: str,
        owner_id: str,
        question: str,
        model: str | None = None,
    ) -> PreparedTurn:
        """Validate and register the turn. Raises ThreadNotFound / ThreadBusy / ServerBusy."""
        if self._locks[thread_id].locked():
            raise ThreadBusy(thread_id)
        if self._active >= self._settings.max_concurrent_runs:
            raise ServerBusy()
        thread = await self._store.ensure_thread(thread_id, owner_id, question)
        return PreparedTurn(
            thread=thread,
            owner_id=owner_id,
            question=question,
            provider=self._settings.model_provider,
            model=model or self._settings.model,
        )

    # ------------------------------------------------------------------ the turn
    async def stream(self, turn: PreparedTurn) -> AsyncGenerator[Chunk, None]:
        thread_id = turn.thread.thread_id
        lock = self._locks[thread_id]
        if lock.locked():  # lost a race between prepare() and the first iteration
            yield {"type": "error", "errorText": "A run is already in progress for this thread."}
            return
        async with lock:
            self._active += 1
            try:
                # aclosing: if the consumer goes away, the inner generator is closed right now
                # (so the run is persisted) instead of whenever the garbage collector gets to it.
                async with aclosing(self._run(turn)) as inner:
                    async for chunk in inner:
                        yield chunk
            finally:
                self._active -= 1

    async def _run(self, turn: PreparedTurn) -> AsyncGenerator[Chunk, None]:
        settings = self._settings
        thread_id = turn.thread.thread_id
        adapter = UIStreamAdapter(f"msg-{uuid.uuid4().hex[:12]}")
        sent: list[Chunk] = []
        started = time.monotonic()
        status, error_text = "ok", None
        artifacts = ArtifactStore(settings.artifacts_dir, thread_id)
        sql_log: list[dict[str, Any]] = []
        tracker = UsageTracker(
            max_tokens=settings.max_tokens_per_request,
            max_cost_usd=settings.max_cost_usd_per_request,
            max_llm_calls=settings.max_agent_steps,
        )
        handler = make_handler(settings)
        driver: AgentDriver | None = None
        interrupted: BaseException | None = None
        try:
            for chunk in adapter.start():
                sent.append(chunk)
                yield chunk
            config: RunnableConfig = {
                "callbacks": [tracker] + ([handler] if handler else []),
                "recursion_limit": settings.max_agent_steps * 6 + 20,
                "configurable": {"thread_id": thread_id},
                "metadata": {
                    "langfuse_session_id": thread_id,
                    "langfuse_tags": ["api", turn.provider, turn.model],
                    "model": turn.model,
                    "provider": turn.provider,
                },
                "run_name": "analyst-run",
            }
            agent = await build_agent(
                settings,
                thread_id=thread_id,
                sandboxes=self._sandboxes,
                artifacts=artifacts,
                sql_log=sql_log,
                model=get_model(settings, provider=turn.provider, model=turn.model),
                checkpointer=self._checkpointer,
                known_sandbox_id=turn.thread.sandbox_id,
            )
            sandbox_id = self._sandboxes.sandbox_id(thread_id)
            if sandbox_id and sandbox_id != turn.thread.sandbox_id:
                await self._store.set_sandbox_id(thread_id, sandbox_id)
            driver = AgentDriver(agent, config, turn.question)
            async for mode, payload in driver.events():
                for chunk in adapter.feed(mode, payload):
                    sent.append(chunk)
                    yield chunk
        except (asyncio.CancelledError, GeneratorExit) as exc:
            status, interrupted = "aborted", exc  # client disconnected / cancelled
        except StepLimitExceeded as exc:
            status, error_text = "step_limit", str(exc)
        except BudgetExceeded as exc:
            status, error_text = "budget_exceeded", str(exc)
        except Exception as exc:
            logger.exception("run failed thread=%s", thread_id)
            status, error_text = "error", f"The run failed ({type(exc).__name__})."

        # --- always finish: deliver files, flush trace, persist the run ---
        tail = await asyncio.shield(
            self._finish(
                turn=turn,
                adapter=adapter,
                sent=sent,
                driver=driver,
                tracker=tracker,
                handler=handler,
                artifacts=artifacts,
                sql_log=sql_log,
                status=status,
                error_text=error_text,
                seconds=round(time.monotonic() - started, 1),
            )
        )
        if interrupted is not None:
            raise interrupted
        for chunk in tail:
            yield chunk

    async def _finish(
        self,
        *,
        turn: PreparedTurn,
        adapter: UIStreamAdapter,
        sent: list[Chunk],
        driver: AgentDriver | None,
        tracker: UsageTracker,
        handler: Any,
        artifacts: ArtifactStore,
        sql_log: list[dict[str, Any]],
        status: str,
        error_text: str | None,
        seconds: float,
    ) -> list[Chunk]:
        thread_id = turn.thread.thread_id
        try:
            await collect_outputs(self._sandboxes, thread_id, artifacts)
        except Exception:
            logger.exception("collecting outputs failed")
        delivered = [
            {
                "name": a.name,
                "mime": a.mime,
                "size": a.size,
                "url": artifact_url(thread_id, a.name),
            }
            for a in artifacts.list()
        ]
        final_answer = driver.final_answer if driver else ""
        claims = unverified_file_claims(final_answer, artifacts.all_names())
        trace_id, trace_url = finalize_trace(handler, self._settings)
        usage = tracker.summary.as_dict()
        run_data: dict[str, Any] = {
            "status": status,
            "model": turn.model,
            "provider": turn.provider,
            "usage": usage,
            "seconds": seconds,
            "trace_url": trace_url,
            "empty_reply_nudges": driver.nudges if driver else 0,
            "unverified_file_claims": claims,
            "sql_queries": len(sql_log),
        }
        data_parts: list[Chunk] = []
        if delivered:
            data_parts.append(
                {"type": "data-artifacts", "id": "artifacts", "data": {"items": delivered}}
            )
        data_parts.append({"type": "data-run", "id": "run", "data": run_data})
        tail = adapter.finish(error=error_text, data_parts=data_parts)
        try:
            await self._store.save_run(
                thread_id=thread_id,
                question=turn.question,
                status=status,
                provider=turn.provider,
                model=turn.model,
                final_answer=final_answer,
                chunks=coalesce(sent + tail),
                summary={
                    **run_data,
                    "trace_id": trace_id,
                    "artifacts": delivered,
                    "sql": sql_log,
                    "error": error_text,
                },
            )
        except Exception:
            logger.exception("could not persist run thread=%s", thread_id)
        return tail
