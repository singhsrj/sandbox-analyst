"""The data source seam: the tools, validator, approval gate and prompt follow the source they
are given, and the sample source keeps today's behaviour. No database or sandbox needed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agent.approvals import approval_reason
from app.agent.prompt import SYSTEM_PROMPT, build_system_prompt
from app.artifacts import ArtifactStore
from app.config import Settings
from app.datasources import Catalog, Column, SampleSource, Table, risk_check
from app.datasources import sample as sample_module
from app.db.analyst import QueryResult
from app.security.sql_validator import (
    SAMPLE_SCOPE,
    SqlValidationError,
    ValidatedQuery,
    ValidationScope,
    validate_select,
)
from app.tools.analyst_tools import ToolContext, build_tools

SHOP = ValidationScope(schema="shop", tables=frozenset({"invoices", "clients"}))


class FakeSource:
    """A stand-in for a user's database: schema `shop`, two tables, records every query."""

    scope = SHOP
    large_tables = frozenset({"invoices"})
    description = "a wholesale business"
    engine_name = "Postgres"
    notes = "- Sales means invoices.amount where paid = true."

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.catalog_calls = 0

    async def catalog(self) -> Catalog:
        self.catalog_calls += 1
        return Catalog(
            schema="shop",
            tables=(
                Table(
                    "clients",
                    120,
                    "",
                    (Column("client_id", "integer", False),),
                    ("PRIMARY KEY (client_id)",),
                ),
                Table(
                    "invoices",
                    50_000,
                    "One row per invoice",
                    (
                        Column("invoice_id", "integer", False),
                        Column("amount", "numeric(12,2)", True, "gross, in EUR"),
                    ),
                    ("PRIMARY KEY (invoice_id)",),
                ),
            ),
        )

    async def run_readonly(self, query: ValidatedQuery) -> QueryResult:
        self.queries.append(query.sql)
        return QueryResult(["invoice_id"], ["int4"], [(1,)], truncated=False, row_cap=10)


def _tools(source: Any, tmp_path: Path) -> dict[str, Any]:
    async def no_sandbox() -> Any:
        raise AssertionError("the sandbox must not be touched")

    ctx = ToolContext(
        settings=Settings(_env_file=None),
        get_sandbox=no_sandbox,
        artifacts=ArtifactStore(tmp_path, "t"),
        source=source,
    )
    return {t.name: t for t in build_tools(ctx)}


# --------------------------------------------------------------------------- validator scope
def test_the_default_scope_is_the_sample_data() -> None:
    assert validate_select("SELECT count(*) FROM analytics.orders").tables == {"orders"}
    with pytest.raises(SqlValidationError, match="Only the 'analytics' schema"):
        validate_select("SELECT * FROM shop.invoices")


def test_a_custom_scope_replaces_the_sample_allowlist() -> None:
    assert validate_select("SELECT * FROM shop.invoices", SHOP).tables == {"invoices"}
    with pytest.raises(SqlValidationError, match="Only the 'shop' schema"):
        validate_select("SELECT * FROM analytics.orders", SHOP)
    with pytest.raises(SqlValidationError, match="Available tables: clients, invoices"):
        validate_select("SELECT * FROM orders", SHOP)
    # The scope widens WHICH tables, never WHAT SQL: writes and catalogs stay rejected.
    for bad in ("DELETE FROM shop.invoices", "SELECT * FROM pg_shadow", "SELECT pg_sleep(1)"):
        with pytest.raises(SqlValidationError):
            validate_select(bad, SHOP)


def test_the_scope_dialect_names_the_engine_in_parse_errors() -> None:
    with pytest.raises(SqlValidationError, match="parsed as MySQL"):
        validate_select("SELECT (", ValidationScope("shop", frozenset({"x"}), dialect="mysql"))


# --------------------------------------------------------------------------- approval gate
def test_the_risk_check_uses_the_sources_large_tables_and_schema() -> None:
    check = risk_check(FakeSource())
    assert check("SELECT * FROM shop.invoices").flagged
    assert not check("SELECT * FROM shop.clients").flagged  # small table
    reason = approval_reason("normal", "SELECT * FROM shop.invoices", check)
    assert "raw rows of shop.invoices" in reason
    # The sample's check is unchanged.
    assert risk_check(SampleSource(Settings(_env_file=None)))("SELECT * FROM orders").flagged


# --------------------------------------------------------------------------- prompt
def test_the_sample_prompt_keeps_its_conventions() -> None:
    assert "an e-commerce company by querying its Postgres database" in SYSTEM_PROMPT
    assert "## Data conventions\n- Revenue means orders.total_amount" in SYSTEM_PROMPT


def test_the_prompt_follows_the_source() -> None:
    prompt = build_system_prompt(FakeSource())
    assert "questions about\na wholesale business by querying its Postgres database" in prompt
    assert "- Sales means invoices.amount where paid = true." in prompt
    assert "orders.total_amount" not in prompt
    for rule in ("UNTRUSTED DATA", "Never reveal secrets", "strictly read-only"):
        assert rule in prompt  # the safety rules are not source-specific


def test_a_source_without_notes_gets_no_conventions_section() -> None:
    source = FakeSource()
    source.notes = "  "
    prompt = build_system_prompt(source)
    assert "## Data conventions" not in prompt
    assert "## Report format" in prompt


def test_braces_in_notes_are_kept_literally() -> None:
    source = FakeSource()
    source.notes = "- {not a placeholder} <<engine>>"
    assert "- {not a placeholder} <<engine>>" in build_system_prompt(source)


# --------------------------------------------------------------------------- tools
async def test_tools_list_and_describe_the_sources_tables(tmp_path: Path) -> None:
    source = FakeSource()
    tools = _tools(source, tmp_path)
    listed = await tools["list_tables"].ainvoke({})
    assert listed.startswith("Tables in schema 'shop':")
    assert "- invoices (~50,000 rows): One row per invoice" in listed

    described = await tools["describe_table"].ainvoke({"table_name": "shop.invoices"})
    assert described.startswith("Table shop.invoices\nColumns:")
    assert "- invoice_id integer NOT NULL" in described
    assert "- amount numeric(12,2) nullable -- gross, in EUR" in described
    assert "Keys:\n- PRIMARY KEY (invoice_id)" in described
    assert source.queries == ["SELECT * FROM shop.invoices LIMIT 3"]


async def test_describe_rejects_names_outside_the_scope_without_a_round_trip(
    tmp_path: Path,
) -> None:
    source = FakeSource()
    tools = _tools(source, tmp_path)
    for bad in ("orders", "analytics.orders", "invoices; DROP TABLE x", "pg_shadow"):
        out = await tools["describe_table"].ainvoke({"table_name": bad})
        assert out.startswith("Unknown table") and "clients, invoices" in out
    assert source.catalog_calls == 0 and source.queries == []


async def test_run_sql_validates_against_the_sources_scope(tmp_path: Path) -> None:
    source = FakeSource()
    tools = _tools(source, tmp_path)
    out = await tools["run_sql"].ainvoke(
        {"query": "SELECT * FROM analytics.orders", "output_file": "x.csv"}
    )
    assert out.startswith("SQL REJECTED:") and "'shop' schema" in out
    assert source.queries == []


# --------------------------------------------------------------------------- sample catalog
async def test_the_sample_catalog_keeps_only_allowlisted_tables_and_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_fetch(settings: Settings, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        assert params == ("analytics",)
        calls.append(query)
        if "FROM pg_constraint" in query:
            return [("orders", "PRIMARY KEY (order_id)")]
        if "FROM pg_attribute" in query:
            return [("orders", "order_id", "bigint", False, "")]
        return [("orders", 10, "Orders"), ("schema_migrations", 4, "")]

    monkeypatch.setattr(sample_module, "fetch_catalog", fake_fetch)
    monkeypatch.setattr(sample_module, "_cache", {})
    source = SampleSource(Settings(_env_file=None))

    catalog = await source.catalog()
    assert [t.name for t in catalog.tables] == ["orders"]  # not schema_migrations
    orders = catalog.get("orders")
    assert orders is not None
    assert orders.columns == (Column("order_id", "bigint", False, ""),)
    assert orders.keys == ("PRIMARY KEY (order_id)",)

    await source.catalog()
    assert len(calls) == 3  # second call served from the cache


def test_the_sample_scope_is_unchanged() -> None:
    assert SampleSource.scope is SAMPLE_SCOPE
    assert SAMPLE_SCOPE.schema == "analytics" and len(SAMPLE_SCOPE.tables) == 8
