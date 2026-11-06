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
    """Pool shared by the store and LangGraph's checkpointer (needs autocommit + dict rows)."""
    return AsyncConnectionPool(
        settings.secret("app_database_url"),
        min_size=1,
        max_size=6,
        open=False,
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
