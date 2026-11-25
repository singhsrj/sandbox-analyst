"""In-memory stand-ins for the database, sandbox manager and agent (no network needed)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage, messages_from_dict
from langgraph.types import Command, Interrupt

from app.db.app_store import ThreadInfo, ThreadNotFound, UserInfo
from app.db.app_store import _title as make_title
from app.db.connection_store import ConnectionNotFound, ConnectionRecord

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
        self.resumes: list[Any] = []

    async def astream(self, payload: Any, config: Any, stream_mode: Any) -> AsyncIterator[Any]:
        self.calls += 1
        if isinstance(payload, Command):
            self.resumes.append(payload.resume)
            self.inputs.append("<resume>")
        else:
            self.inputs.append(payload["messages"][0].content)
        for index, event in enumerate(self._events):
            if self._raise_after is not None and index >= self._raise_after and self._error:
                raise self._error
            yield event

    async def aget_state(self, config: Any) -> Any:
        text = "" if (self._empty_first and self.calls == 1) else self._final
        return SimpleNamespace(values={"messages": [AIMessage(text)]}, interrupts=())


class PausingAgent(FakeAgent):
    """First call: shows a run_sql call and pauses for approval. A resume finishes the run."""

    QUERY = "SELECT * FROM analytics.orders"

    def __init__(self, final_text: str = "Answer after approval.") -> None:
        super().__init__([], final_text)
        self.interrupt = Interrupt(
            value={
                "type": "tool_approval",
                "tool_call_id": "call-sql-1",
                "name": "run_sql",
                "args": {"query": self.QUERY, "output_file": "orders.csv"},
                "description": "Flagged for review: returns raw rows of analytics.orders",
            },
            id="intr-1",
        )

    async def astream(self, payload: Any, config: Any, stream_mode: Any) -> AsyncIterator[Any]:
        self.calls += 1
        if isinstance(payload, Command):
            resume: dict[str, Any] = dict(payload.resume or {})
            self.resumes.append(resume)
            decision = resume["intr-1"]
            if decision["type"] == "reject":
                content, status = "User rejected the tool call.", "error"
            else:
                content, status = "OK: 10,000 rows", "success"
            yield (
                "updates",
                {
                    "tools": {
                        "messages": [
                            ToolMessage(
                                content, tool_call_id="call-sql-1", name="run_sql", status=status
                            )
                        ]
                    }
                },
            )
            yield ("updates", {"model": {"messages": [AIMessage(self._final, id="final")]}})
            return
        self.inputs.append(payload["messages"][0].content)
        call = {"name": "run_sql", "args": self.interrupt.value["args"], "id": "call-sql-1"}
        yield ("updates", {"model": {"messages": [AIMessage("", tool_calls=[call], id="m1")]}})
        yield ("updates", {"__interrupt__": (self.interrupt,)})

    async def aget_state(self, config: Any) -> Any:
        paused = not self.resumes
        messages = [AIMessage("" if paused else self._final)]
        return SimpleNamespace(
            values={"messages": messages}, interrupts=(self.interrupt,) if paused else ()
        )


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
    usage: list[tuple[str, int]] = field(default_factory=list)
    # Clerk id -> [our user id, live access]. Our id equals the Clerk id here, to keep tests readable.
    users: dict[str, list[Any]] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    # Connection ids in the recycle bin: their threads are hidden, as in AppStore.
    trashed_connections: set[str] = field(default_factory=set)

    async def user_for(self, provider: str, provider_sub: str) -> UserInfo:
        row = self.users.setdefault(provider_sub, [provider_sub, False])
        return UserInfo(user_id=row[0], live_access=row[1])

    async def grant_live_access(self, user_id: str) -> None:
        for row in self.users.values():
            if row[0] == user_id:
                row[1] = True

    async def add_suggestion(self, body: str) -> None:
        self.suggestions.append(body)

    async def ensure_thread(
        self, thread_id: str, owner_id: str, question: str, connection_id: str | None = None
    ) -> ThreadInfo:
        row = self.threads.setdefault(
            thread_id,
            {"owner": owner_id, "title": make_title(question), "connection_id": connection_id},
        )
        if row["owner"] != owner_id or not self._visible(thread_id):
            raise ThreadNotFound(thread_id)
        return self._info(thread_id)

    def _visible(self, thread_id: str) -> bool:
        return self.threads[thread_id].get("connection_id") not in self.trashed_connections

    def _info(self, thread_id: str) -> ThreadInfo:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        row = self.threads[thread_id]
        return ThreadInfo(
            thread_id,
            row["title"],
            self.sandbox_ids.get(thread_id),
            now,
            now,
            row.get("connection_id"),
        )

    async def get_thread(self, thread_id: str, owner_id: str) -> ThreadInfo:
        if (
            thread_id not in self.threads
            or self.threads[thread_id]["owner"] != owner_id
            or not self._visible(thread_id)
        ):
            raise ThreadNotFound(thread_id)
        return self._info(thread_id)

    async def list_threads(self, owner_id: str, limit: int = 50) -> list[ThreadInfo]:
        return [
            self._info(t)
            for t, r in self.threads.items()
            if r["owner"] == owner_id and self._visible(t)
        ]

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

    async def last_run(self, thread_id: str) -> dict[str, Any] | None:
        mine = [(i, r) for i, r in enumerate(self.runs, 1) if r["thread_id"] == thread_id]
        if not mine:
            return None
        index, run = mine[-1]
        return {
            "run_id": f"run-{index}",
            "question": run["question"],
            "status": run["status"],
            "summary": run["summary"],
        }

    async def record_usage(self, *, owner_id: str, thread_id: str, total_tokens: int) -> None:
        self.usage.append((owner_id, total_tokens))

    async def tokens_used_last_day(self, owner_id: str | None = None) -> int:
        return sum(t for o, t in self.usage if owner_id is None or o == owner_id)

    async def list_runs(self, thread_id: str, owner_id: str) -> list[dict[str, Any]]:
        await self.get_thread(thread_id, owner_id)
        return [
            {**r, "run_id": f"run-{i}", "created_at": "2026-01-01T00:00:00+00:00"}
            for i, r in enumerate(self.runs, 1)
            if r["thread_id"] == thread_id
        ]


class FakeConnectionStore:
    """`ConnectionStore` in memory. Shares the trashed set with a FakeStore when given one, so
    threads of a trashed connection disappear the same way they do in Postgres."""

    def __init__(self, app_store: FakeStore | None = None) -> None:
        self.records: dict[str, ConnectionRecord] = {}
        self.app_store = app_store
        self.purged: list[str] = []
        self._own_trash: set[str] = set()

    def _trashed(self) -> set[str]:
        return self.app_store.trashed_connections if self.app_store else self._own_trash

    async def count_active(self, owner_id: str) -> int:
        return sum(1 for r in self.records.values() if r.owner_id == owner_id and not r.deleted_at)

    async def insert(self, record: ConnectionRecord) -> None:
        self.records[record.connection_id] = record

    async def list_for(self, owner_id: str) -> list[ConnectionRecord]:
        return [r for r in self.records.values() if r.owner_id == owner_id]

    async def get(
        self, connection_id: str, owner_id: str, *, include_trashed: bool = False
    ) -> ConnectionRecord:
        record = self.records.get(connection_id)
        if record is None or record.owner_id != owner_id:
            raise ConnectionNotFound(connection_id)
        if record.deleted_at is not None and not include_trashed:
            raise ConnectionNotFound(connection_id)
        return record

    async def update_details(
        self, connection_id: str, owner_id: str, *, name: str | None, notes: str | None
    ) -> None:
        record = await self.get(connection_id, owner_id)
        self.records[connection_id] = replace(
            record,
            name=name if name is not None else record.name,
            notes=notes if notes is not None else record.notes,
        )

    async def update_inspection(
        self,
        connection_id: str,
        owner_id: str,
        *,
        checks: list[dict[str, Any]],
        catalog: dict[str, Any] | None,
        secret: tuple[bytes, str] | None = None,
    ) -> None:
        record = await self.get(connection_id, owner_id)
        changes: dict[str, Any] = {"checks": checks}
        if catalog is not None:
            changes["catalog"] = catalog
        if secret is not None:
            changes["secret_ciphertext"], changes["key_id"] = secret
        self.records[connection_id] = replace(record, **changes)

    def _thread_ids(self, connection_id: str) -> list[str]:
        if self.app_store is None:
            return []
        return [
            t for t, r in self.app_store.threads.items() if r.get("connection_id") == connection_id
        ]

    async def trash(self, connection_id: str, owner_id: str) -> list[str]:
        record = await self.get(connection_id, owner_id)
        self.records[connection_id] = replace(record, deleted_at=datetime.now(UTC))
        self._trashed().add(connection_id)
        return self._thread_ids(connection_id)

    async def restore(self, connection_id: str, owner_id: str, trash_days: int) -> None:
        record = await self.get(connection_id, owner_id, include_trashed=True)
        cutoff = datetime.now(UTC) - timedelta(days=trash_days)
        if record.deleted_at is None or record.deleted_at <= cutoff:
            raise ConnectionNotFound(connection_id)
        self.records[connection_id] = replace(record, deleted_at=None)
        self._trashed().discard(connection_id)

    async def expired(self, trash_days: int) -> list[tuple[str, list[str]]]:
        cutoff = datetime.now(UTC) - timedelta(days=trash_days)
        return [
            (cid, self._thread_ids(cid))
            for cid, r in self.records.items()
            if r.deleted_at is not None and r.deleted_at <= cutoff
        ]

    async def purge(self, connection_id: str) -> None:
        threads = self._thread_ids(connection_id)
        self.records.pop(connection_id, None)
        self.purged.append(connection_id)
        if self.app_store is not None:
            for thread_id in threads:
                del self.app_store.threads[thread_id]
