"""Saved database connections in `app.connections` (role app_rw).

Same ownership rule as threads: every read and write is scoped by `owner_id`, and another
person's connection behaves exactly like one that does not exist. Connections in the recycle bin
(`deleted_at` set) are only visible to `list_for` (so the owner can restore them) and to the
purge job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


class ConnectionNotFound(LookupError):
    """No such connection for this owner (or it is in the recycle bin)."""


@dataclass(frozen=True)
class ConnectionRecord:
    connection_id: str
    owner_id: str
    engine: str
    name: str
    host: str
    port: int
    database: str
    username: str
    schema_name: str
    tls_mode: str
    secret_ciphertext: bytes
    key_id: str
    notes: str
    catalog: dict[str, Any]
    checks: list[dict[str, Any]]
    checked_at: datetime
    consented_at: datetime
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @property
    def usable(self) -> bool:
        return self.deleted_at is None and all(c.get("ok") for c in self.checks)

    def public(self, trash_days: int) -> dict[str, Any]:
        """What the owner's browser may see. Never the password or its ciphertext."""
        tables = self.catalog.get("tables", [])
        return {
            "connection_id": self.connection_id,
            "engine": self.engine,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "schema": self.schema_name,
            "tls_mode": self.tls_mode,
            "notes": self.notes,
            "usable": self.usable,
            "checks": self.checks,
            "checked_at": self.checked_at.isoformat(),
            "table_count": len(tables),
            "skipped_tables": self.catalog.get("skipped", []),
            "created_at": self.created_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "purge_at": (self.deleted_at + timedelta(days=trash_days)).isoformat()
            if self.deleted_at
            else None,
        }


_COLUMNS = (
    "connection_id::text AS connection_id, owner_id, engine, name, host, port, database, "
    "username, schema_name, tls_mode, secret_ciphertext, key_id, notes, catalog, checks, "
    "checked_at, consented_at, created_at, updated_at, deleted_at"
)


def _record(row: dict[str, Any]) -> ConnectionRecord:
    row = dict(row)
    row["secret_ciphertext"] = bytes(row["secret_ciphertext"])
    return ConnectionRecord(**row)


def _json(value: Any) -> Jsonb:
    return Jsonb(value)


class ConnectionStore:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def count_active(self, owner_id: str) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM app.connections "
                "WHERE owner_id = %s AND deleted_at IS NULL",
                (owner_id,),
            )
            row = cast(dict[str, Any], await cur.fetchone())
        return int(row["n"])

    async def insert(self, record: ConnectionRecord) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.connections (connection_id, owner_id, engine, name, host, port, "
                "database, username, schema_name, tls_mode, secret_ciphertext, key_id, notes, "
                "catalog, checks, checked_at, consented_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    record.connection_id,
                    record.owner_id,
                    record.engine,
                    record.name,
                    record.host,
                    record.port,
                    record.database,
                    record.username,
                    record.schema_name,
                    record.tls_mode,
                    record.secret_ciphertext,
                    record.key_id,
                    record.notes,
                    _json(record.catalog),
                    _json(record.checks),
                    record.checked_at,
                    record.consented_at,
                ),
            )

    async def list_for(self, owner_id: str) -> list[ConnectionRecord]:
        """The owner's connections, including those in the recycle bin."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM app.connections WHERE owner_id = %s "  # noqa: S608 - constant column list
                "ORDER BY deleted_at NULLS FIRST, created_at",
                (owner_id,),
            )
            rows = cast(list[dict[str, Any]], await cur.fetchall())
        return [_record(r) for r in rows]

    async def get(
        self, connection_id: str, owner_id: str, *, include_trashed: bool = False
    ) -> ConnectionRecord:
        query = f"SELECT {_COLUMNS} FROM app.connections WHERE connection_id = %s AND owner_id = %s"  # noqa: S608 - constant column list
        if not include_trashed:
            query += " AND deleted_at IS NULL"
        async with self._pool.connection() as conn:
            cur = await conn.execute(query, (connection_id, owner_id))
            row = cast(dict[str, Any] | None, await cur.fetchone())
        if row is None:
            raise ConnectionNotFound(connection_id)
        return _record(row)

    async def update_details(
        self, connection_id: str, owner_id: str, *, name: str | None, notes: str | None
    ) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE app.connections SET name = coalesce(%s, name), "
                "notes = coalesce(%s, notes), updated_at = now() "
                "WHERE connection_id = %s AND owner_id = %s AND deleted_at IS NULL",
                (name, notes, connection_id, owner_id),
            )
        if cur.rowcount == 0:
            raise ConnectionNotFound(connection_id)

    async def update_inspection(
        self,
        connection_id: str,
        owner_id: str,
        *,
        checks: list[dict[str, Any]],
        catalog: dict[str, Any] | None,
        secret: tuple[bytes, str] | None = None,
    ) -> None:
        """Save a new check result; a new catalog snapshot and password when given."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE app.connections SET checks = %s, checked_at = now(), updated_at = now(), "
                "catalog = coalesce(%s, catalog), "
                "secret_ciphertext = coalesce(%s, secret_ciphertext), "
                "key_id = coalesce(%s, key_id) "
                "WHERE connection_id = %s AND owner_id = %s AND deleted_at IS NULL",
                (
                    _json(checks),
                    _json(catalog) if catalog is not None else None,
                    secret[0] if secret else None,
                    secret[1] if secret else None,
                    connection_id,
                    owner_id,
                ),
            )
        if cur.rowcount == 0:
            raise ConnectionNotFound(connection_id)

    async def trash(self, connection_id: str, owner_id: str) -> list[str]:
        """Move to the recycle bin. Returns the ids of the threads that are now hidden."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE app.connections SET deleted_at = now(), updated_at = now() "
                "WHERE connection_id = %s AND owner_id = %s AND deleted_at IS NULL",
                (connection_id, owner_id),
            )
            if cur.rowcount == 0:
                raise ConnectionNotFound(connection_id)
            return await self._thread_ids(conn, connection_id)

    async def restore(self, connection_id: str, owner_id: str, trash_days: int) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE app.connections SET deleted_at = NULL, updated_at = now() "
                "WHERE connection_id = %s AND owner_id = %s AND deleted_at IS NOT NULL "
                "AND deleted_at > now() - make_interval(days => %s)",
                (connection_id, owner_id, trash_days),
            )
        if cur.rowcount == 0:
            raise ConnectionNotFound(connection_id)

    async def expired(self, trash_days: int) -> list[tuple[str, list[str]]]:
        """Connections in the recycle bin for longer than `trash_days`, with their thread ids."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT connection_id::text AS connection_id FROM app.connections "
                "WHERE deleted_at IS NOT NULL AND deleted_at <= now() - make_interval(days => %s) "
                "ORDER BY deleted_at LIMIT 100",
                (trash_days,),
            )
            ids = [r["connection_id"] for r in cast(list[dict[str, Any]], await cur.fetchall())]
            return [(cid, await self._thread_ids(conn, cid)) for cid in ids]

    async def purge(self, connection_id: str) -> None:
        """Delete for good (threads and runs go with it: ON DELETE CASCADE)."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "DELETE FROM app.connections WHERE connection_id = %s AND deleted_at IS NOT NULL",
                (connection_id,),
            )

    @staticmethod
    async def _thread_ids(conn: Any, connection_id: str) -> list[str]:
        cur = await conn.execute(
            "SELECT thread_id FROM app.threads WHERE connection_id = %s", (connection_id,)
        )
        return [r["thread_id"] for r in cast(list[dict[str, Any]], await cur.fetchall())]
