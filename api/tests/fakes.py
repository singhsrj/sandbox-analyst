"""In-memory stand-ins for the database, sandbox manager and agent (no network needed)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, messages_from_dict

from app.db.app_store import ThreadInfo, ThreadNotFound
from app.db.app_store import _title as make_title

FIXTURE = Path(__file__).parent / "fixtures" / "stream_simple.jsonl"


def recorded_events() -> list[tuple[str, Any]]:
    """The real agent stream recorded in M3 (messages + updates), as LangGraph yields it."""
    events: list[tuple[str, Any]] = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["mode"] == "messages":
            message = messages_from_dict([record["message"]])[0]
            events.append(("messages", (message, {"langgraph_node": record["node"]})))
        else:
            payload = {
                node: (
                    None if update is None else {"messages": messages_from_dict(update["messages"])}
                )
                for node, update in record["payload"].items()
            }
            events.append(("updates", payload))
    return events


class FakeAgent:
    """Plays a scripted event list; can raise mid-stream or hang to simulate failures."""

    def __init__(
        self,
        events: list[tuple[str, Any]],
        final_text: str = "Done.",
        *,
        raise_after: int | None = None,
        error: BaseException | None = None,
        empty_first: bool = False,
    ) -> None:
        self._events = events
        self._final = final_text
        self._raise_after = raise_after
        self._error = error
        self._empty_first = empty_first
        self.calls = 0
        self.inputs: list[str] = []

    async def astream(self, payload: Any, config: Any, stream_mode: Any) -> AsyncIterator[Any]:
        self.calls += 1
        self.inputs.append(payload["messages"][0].content)
        for index, event in enumerate(self._events):
            if self._raise_after is not None and index >= self._raise_after and self._error:
                raise self._error
            yield event

    async def aget_state(self, config: Any) -> Any:
        text = "" if (self._empty_first and self.calls == 1) else self._final
        return SimpleNamespace(values={"messages": [AIMessage(text)]})


class FakeSandboxes:
    def __init__(self) -> None:
        self.closed: list[str] = []
        self.active_threads: list[str] = []

    def sandbox_id(self, thread_id: str) -> str | None:
        return "sbx-fake"

    async def close(self, thread_id: str) -> None:
        self.closed.append(thread_id)


@dataclass
class FakeStore:
    threads: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    sandbox_ids: dict[str, str] = field(default_factory=dict)

    async def ensure_thread(self, thread_id: str, owner_id: str, question: str) -> ThreadInfo:
        row = self.threads.setdefault(thread_id, {"owner": owner_id, "title": make_title(question)})
        if row["owner"] != owner_id:
            raise ThreadNotFound(thread_id)
        return self._info(thread_id)

    def _info(self, thread_id: str) -> ThreadInfo:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        return ThreadInfo(
            thread_id, self.threads[thread_id]["title"], self.sandbox_ids.get(thread_id), now, now
        )

    async def get_thread(self, thread_id: str, owner_id: str) -> ThreadInfo:
        if thread_id not in self.threads or self.threads[thread_id]["owner"] != owner_id:
            raise ThreadNotFound(thread_id)
        return self._info(thread_id)

    async def list_threads(self, owner_id: str, limit: int = 50) -> list[ThreadInfo]:
        return [self._info(t) for t, r in self.threads.items() if r["owner"] == owner_id]

    async def set_sandbox_id(self, thread_id: str, sandbox_id: str) -> None:
        self.sandbox_ids[thread_id] = sandbox_id

    async def delete_thread(self, thread_id: str, owner_id: str) -> bool:
        if self.threads.get(thread_id, {}).get("owner") != owner_id:
            return False
        del self.threads[thread_id]
        return True

    async def save_run(self, **kwargs: Any) -> str:
        self.runs.append(kwargs)
        return f"run-{len(self.runs)}"

    async def list_runs(self, thread_id: str, owner_id: str) -> list[dict[str, Any]]:
        await self.get_thread(thread_id, owner_id)
        return [
            {**r, "run_id": f"run-{i}", "created_at": "2026-01-01T00:00:00+00:00"}
            for i, r in enumerate(self.runs, 1)
            if r["thread_id"] == thread_id
        ]
