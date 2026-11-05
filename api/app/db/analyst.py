"""Run validated, read-only SQL as the `analyst_ro` role and summarise the result.

Safety properties (see docs/decisions.md ADR-009):
  * connects with ANALYST_DATABASE_URL (role analyst_ro: SELECT on analytics only)
  * every query runs inside ONE explicit transaction using `SET LOCAL` only, because Neon's pooler
    reuses server connections without resetting session state
  * the transaction is always rolled back, never committed
  * rows are streamed through a server-side cursor and capped, so a huge result can never exhaust
    memory; the cap and statement timeout come from settings, not from the prompt
  * prepared statements are disabled (PgBouncer transaction pooling)
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql as pgsql

from app.config import Settings
from app.security.sql_validator import ValidatedQuery

MAX_CELL_CHARS = 80


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    dtypes: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool  # more rows existed than the row cap
    row_cap: int

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_csv_bytes(self) -> bytes:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        return buffer.getvalue().encode("utf-8")

    def preview(self, n: int) -> list[list[str]]:
        return [[_cell(v) for v in row] for row in self.rows[:n]]


def _cell(value: Any) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"


def _connect(settings: Settings) -> Any:
    return psycopg.AsyncConnection.connect(
        settings.secret("analyst_database_url"),
        autocommit=False,
        prepare_threshold=None,
        connect_timeout=30,
    )


async def run_readonly(query: ValidatedQuery, settings: Settings) -> QueryResult:
    """Execute a validated query. Raises psycopg errors (e.g. QueryCanceled on timeout)."""
    cap = settings.sql_max_rows
    async with await _connect(settings) as conn:
        try:
            await conn.execute("SET TRANSACTION READ ONLY")
            await conn.execute(
                pgsql.SQL("SET LOCAL statement_timeout = {}").format(
                    pgsql.Literal(f"{int(settings.sql_statement_timeout_ms)}ms")
                )
            )
            await conn.execute("SET LOCAL search_path = analytics")
            async with conn.cursor(name="analyst_query") as cur:
                await cur.execute(query.sql)
                fetched = await cur.fetchmany(cap + 1)
                description = cur.description or []
            names = [col.name for col in description]
            dtypes = [_type_name(conn, col.type_code) for col in description]
        finally:
            await conn.rollback()
    return QueryResult(
        columns=names,
        dtypes=dtypes,
        rows=[tuple(r) for r in fetched[:cap]],
        truncated=len(fetched) > cap,
        row_cap=cap,
    )


def _type_name(conn: Any, oid: int) -> str:
    info = conn.adapters.types.get(oid)
    return str(info.name) if info is not None else f"oid:{oid}"


async def fetch_catalog(settings: Settings, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
    """Run one of OUR fixed catalog queries (list/describe). Never used with model-written SQL."""
    async with await _connect(settings) as conn:
        try:
            await conn.execute("SET TRANSACTION READ ONLY")
            await conn.execute("SET LOCAL statement_timeout = '10s'")
            cur = await conn.execute(query, params)
            return list(await cur.fetchall())
        finally:
            await conn.rollback()
