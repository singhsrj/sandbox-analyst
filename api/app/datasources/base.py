"""Where the agent's SQL goes: the interface every data source implements.

Today there is one source, the sample e-commerce database (`SampleSource`). A user's own database
will be another implementation of the same protocol, so the tools, the validator, the approval
gate and the prompt never need to know which database a thread is talking to.

A source answers three questions:
  * what may SQL reference? (`scope`, known WITHOUT a database round trip, so bad table names
    and unsafe SQL are rejected before anything is contacted)
  * what does the data look like? (`catalog()`: tables, columns, notes, keys, row estimates)
  * run this validated query read-only (`run_readonly()`)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.db.analyst import QueryResult
from app.security.sql_validator import ValidatedQuery, ValidationScope


class SourceUnavailable(RuntimeError):
    """The database could not be reached or is no longer safe to use. Safe to show the model."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    note: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    approx_rows: int  # -1 = unknown (views)
    description: str
    columns: tuple[Column, ...]
    keys: tuple[str, ...] = ()  # primary/foreign key definitions, e.g. "PRIMARY KEY (order_id)"
    kind: str = "table"  # table | view | materialized view | partitioned table


@dataclass(frozen=True)
class Catalog:
    schema: str
    tables: tuple[Table, ...]
    # Tables left out (names that need quoting, over the table limit), so the UI can say so.
    skipped: tuple[str, ...] = ()

    def get(self, name: str) -> Table | None:
        return next((t for t in self.tables if t.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "skipped": list(self.skipped),
            "tables": [
                {
                    "name": t.name,
                    "approx_rows": t.approx_rows,
                    "description": t.description,
                    "kind": t.kind,
                    "keys": list(t.keys),
                    "columns": [[c.name, c.type, c.nullable, c.note] for c in t.columns],
                }
                for t in self.tables
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Catalog:
        return cls(
            schema=str(data["schema"]),
            skipped=tuple(data.get("skipped", ())),
            tables=tuple(
                Table(
                    name=t["name"],
                    approx_rows=int(t["approx_rows"]),
                    description=t.get("description", ""),
                    kind=t.get("kind", "table"),
                    keys=tuple(t.get("keys", ())),
                    columns=tuple(Column(c[0], c[1], bool(c[2]), c[3]) for c in t["columns"]),
                )
                for t in data["tables"]
            ),
        )


class DataSource(Protocol):
    # What SQL may reference (schema, table allowlist, dialect).
    scope: ValidationScope
    # Tables bigger than the row cap: a raw or cartesian read of one needs a human's approval.
    large_tables: frozenset[str]
    # For the system prompt: what the data is about ("an e-commerce company") and which engine
    # holds it ("Postgres").
    description: str
    engine_name: str
    # Business conventions for the system prompt (definitions, known data-quality issues).
    # Markdown bullet points; empty when there are none.
    notes: str

    async def catalog(self) -> Catalog: ...

    async def run_readonly(self, query: ValidatedQuery) -> QueryResult: ...
