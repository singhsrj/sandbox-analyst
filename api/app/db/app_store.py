"""Threads and run history in the `app` schema (role app_rw, direct Neon connection).

Ownership rule: every read/write is scoped by `owner_id`. A thread id that belongs to someone
else behaves exactly like a thread that does not exist (no information leak).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.config import Settings


class ThreadNotFound(LookupError):
    """No such thread for this owner (also raised when it belongs to someone else)."""


@dataclass(frozen=True)
class ThreadInfo:
    thread_id: str
    title: str
    sandbox_id: str | None
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def make_pool(settings: Settings) -> AsyncConnectionPool[Any]:
    """Pool shared by the store and LangGraph's checkpointer (needs autocommit + dict rows).

    Neon closes idle connections (found live: `AdminShutdown` on the first request after a quiet
    spell), so every connection is checked when it is handed out and idle ones are recycled early.
    """
    return AsyncConnectionPool(
        settings.secret("app_database_url"),
        min_size=1,
        max_size=6,
        open=False,
        check=AsyncConnectionPool.check_connection,
        max_idle=120,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
    )


def _title(question: str) -> str:
    one_line = " ".join(question.split())
    return one_line if len(one_line) <= 80 else one_line[:79] + "…"


class AppStore:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def ensure_thread(self, thread_id: str, owner_id: str, question: str) -> ThreadInfo:
        """Create the thread for this owner, or return it. Someone else's thread -> not found."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.threads (thread_id, owner_id, title) VALUES (%s, %s, %s) "
                "ON CONFLICT (thread_id) DO NOTHING",
                (thread_id, owner_id, _title(question)),
            )
            cur = await conn.execute(
                "SELECT thread_id, title, sandbox_id, created_at, updated_at FROM app.threads "
                "WHERE thread_id = %s AND owner_id = %s",
                (thread_id, owner_id),
            )
            row = cast(dict[str, Any] | None, await cur.fetchone())
        if row is None:
            raise ThreadNotFound(thread_id)
        return ThreadInfo(**row)

    async def get_thread(self, thread_id: str, owner_id: str) -> ThreadInfo:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT thread_id, title, sandbox_id, created_at, updated_at FROM app.threads "
                "WHERE thread_id = %s AND owner_id = %s",
                (thread_id, owner_id),
            )
            row = cast(dict[str, Any] | None, await cur.fetchone())
        if row is None:
            raise ThreadNotFound(thread_id)
        return ThreadInfo(**row)

    async def list_threads(self, owner_id: str, limit: int = 50) -> list[ThreadInfo]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT thread_id, title, sandbox_id, created_at, updated_at FROM app.threads "
                "WHERE owner_id = %s ORDER BY updated_at DESC LIMIT %s",
                (owner_id, limit),
            )
            return [ThreadInfo(**row) for row in cast(list[dict[str, Any]], await cur.fetchall())]

    async def set_sandbox_id(self, thread_id: str, sandbox_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE app.threads SET sandbox_id = %s WHERE thread_id = %s",
                (sandbox_id, thread_id),
            )

    async def delete_thread(self, thread_id: str, owner_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM app.threads WHERE thread_id = %s AND owner_id = %s",
                (thread_id, owner_id),
            )
            return bool(cur.rowcount > 0)

    async def save_run(
        self,
        *,
        thread_id: str,
        question: str,
        status: str,
        provider: str,
        model: str,
        final_answer: str,
        chunks: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> str:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO app.runs (thread_id, question, status, provider, model, final_answer, "
                "chunks, summary) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING run_id",
                (
                    thread_id,
                    question,
                    status,
                    provider,
                    model,
                    final_answer,
                    Jsonb(chunks, dumps=lambda o: json.dumps(o, default=str)),
                    Jsonb(summary, dumps=lambda o: json.dumps(o, default=str)),
                ),
            )
            row = cast(dict[str, Any] | None, await cur.fetchone())
            await conn.execute(
                "UPDATE app.threads SET updated_at = now() WHERE thread_id = %s", (thread_id,)
            )
        if row is None:  # INSERT ... RETURNING always yields a row
            raise RuntimeError("run was not saved")
        return str(row["run_id"])

    async def last_run(self, thread_id: str) -> dict[str, Any] | None:
        """Status and summary of the thread's newest run (used to find pending approvals)."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT run_id, question, status, summary FROM app.runs WHERE thread_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            )
            row = cast(dict[str, Any] | None, await cur.fetchone())
        if row is not None:
            row["run_id"] = str(row["run_id"])
        return row

    # ------------------------------------------------------------------ budgets
    async def record_usage(self, *, owner_id: str, thread_id: str, total_tokens: int) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.usage_ledger (owner_id, thread_id, total_tokens) "
                "VALUES (%s, %s, %s)",
                (owner_id, thread_id, max(0, int(total_tokens))),
            )

    async def tokens_used_last_day(self, owner_id: str | None = None) -> int:
        """Tokens spent in the last 24 hours, by one owner or (owner_id=None) by everyone."""
        query = (
            "SELECT coalesce(sum(total_tokens), 0) AS used FROM app.usage_ledger "
            "WHERE created_at > now() - interval '24 hours'"
        )
        params: tuple[Any, ...] = ()
        if owner_id is not None:
            query += " AND owner_id = %s"
            params = (owner_id,)
        async with self._pool.connection() as conn:
            cur = await conn.execute(query, params)
            row = cast(dict[str, Any] | None, await cur.fetchone())
        return int(row["used"]) if row else 0

    async def list_runs(self, thread_id: str, owner_id: str) -> list[dict[str, Any]]:
        await self.get_thread(thread_id, owner_id)  # ownership check
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT run_id, question, status, provider, model, final_answer, chunks, summary, "
                "created_at FROM app.runs WHERE thread_id = %s ORDER BY created_at",
                (thread_id,),
            )
            rows = cast(list[dict[str, Any]], await cur.fetchall())
        for row in rows:
            row["run_id"] = str(row["run_id"])
            row["created_at"] = row["created_at"].isoformat()
        return rows
