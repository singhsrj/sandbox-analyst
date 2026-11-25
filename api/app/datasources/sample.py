"""The sample e-commerce database: schema `analytics` on Neon, queried as `analyst_ro`.

Its safety does not depend on this module: the role can only SELECT from `analytics` (ADR-009),
and the validator only allows the eight known tables. This class just routes the tools to it.
"""

from __future__ import annotations

import time

from app.config import Settings
from app.datasources.base import Catalog, Column, Table
from app.db.analyst import QueryResult, fetch_catalog, run_readonly
from app.security.sql_risk import LARGE_TABLES
from app.security.sql_validator import SAMPLE_SCOPE, ValidatedQuery

CATALOG_TTL_SECONDS = 300

SAMPLE_NOTES = """\
- Revenue means orders.total_amount for orders with status = 'delivered' (cancelled orders are
  not revenue) unless the user defines it differently. State the definition you used.
- Real data is messy: look for NULLs, duplicate customers (same email) and duplicate payments,
  and say how they affect your numbers."""

# Our own fixed catalog queries (never model-written). Only ordinary tables of the schema.
_TABLES_SQL = (
    "SELECT c.relname, GREATEST(c.reltuples, 0)::bigint, "
    "coalesce(obj_description(c.oid, 'pg_class'), '') "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = %s AND c.relkind = 'r' ORDER BY c.relname"
)
_COLUMNS_SQL = (
    "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, "
    "coalesce(col_description(a.attrelid, a.attnum), '') "
    "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = %s AND c.relkind = 'r' AND a.attnum > 0 "
    "AND NOT a.attisdropped ORDER BY c.relname, a.attnum"
)
_KEYS_SQL = (
    "SELECT c.relname, pg_get_constraintdef(k.oid) FROM pg_constraint k "
    "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = %s AND c.relkind = 'r' AND k.contype IN ('p', 'f') "
    "ORDER BY c.relname, k.contype DESC, k.oid"  # primary key first, then in creation order
)

# The sample's schema only changes with a migration, so one process-wide copy is enough.
_cache: dict[str, tuple[float, Catalog]] = {}


class SampleSource:
    scope = SAMPLE_SCOPE
    large_tables = LARGE_TABLES
    description = "an e-commerce company"
    engine_name = "Postgres"
    notes = SAMPLE_NOTES

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def catalog(self) -> Catalog:
        cached = _cache.get("sample")
        if cached is not None and time.monotonic() - cached[0] < CATALOG_TTL_SECONDS:
            return cached[1]
        catalog = await self._load_catalog()
        _cache["sample"] = (time.monotonic(), catalog)
        return catalog

    async def run_readonly(self, query: ValidatedQuery) -> QueryResult:
        return await run_readonly(query, self._settings)

    async def _load_catalog(self) -> Catalog:
        schema = self.scope.schema
        tables = await fetch_catalog(self._settings, _TABLES_SQL, (schema,))
        columns = await fetch_catalog(self._settings, _COLUMNS_SQL, (schema,))
        keys = await fetch_catalog(self._settings, _KEYS_SQL, (schema,))
        cols_by_table: dict[str, list[Column]] = {}
        for table, name, type_, nullable, note in columns:
            cols_by_table.setdefault(table, []).append(Column(name, type_, bool(nullable), note))
        keys_by_table: dict[str, list[str]] = {}
        for table, definition in keys:
            keys_by_table.setdefault(table, []).append(definition)
        return Catalog(
            schema=schema,
            tables=tuple(
                Table(
                    name=name,
                    approx_rows=int(rows),
                    description=desc,
                    columns=tuple(cols_by_table.get(name, [])),
                    keys=tuple(keys_by_table.get(name, [])),
                )
                # Only allowlisted tables: anything else in the schema can't be queried anyway.
                for name, rows, desc in tables
                if name in self.scope.tables
            ),
        )
