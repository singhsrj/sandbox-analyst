"""Tool behaviour. Rejections need no database or sandbox; the live tests need both."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.artifacts import ArtifactStore
from app.config import Settings, get_settings
from app.sandbox.manager import SandboxManager
from app.tools.analyst_tools import ToolContext, build_tools

CROSS_JOIN = "SELECT count(*) FROM analytics.order_items a CROSS JOIN analytics.order_items b"


def _tools(
    settings: Settings, tmp_path: Path, manager: SandboxManager | None = None
) -> tuple[dict[str, Any], ToolContext]:
    async def no_sandbox() -> Any:
        raise AssertionError("the sandbox must not be touched for rejected input")

    ctx = ToolContext(
        settings=settings,
        get_sandbox=(lambda: manager.get("t")) if manager else no_sandbox,
        artifacts=ArtifactStore(tmp_path, "t"),
    )
    return {t.name: t for t in build_tools(ctx)}, ctx


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE analytics.orders",
        "SELECT 1; SELECT 2",
        "SELECT * FROM pg_shadow",
        "SELECT pg_sleep(9)",
    ],
)
async def test_run_sql_rejects_unsafe_queries_before_touching_anything(
    query: str, tmp_path: Path
) -> None:
    tools, ctx = _tools(Settings(_env_file=None), tmp_path)
    out = await tools["run_sql"].ainvoke({"query": query, "output_file": "x.csv"})
    assert out.startswith("SQL REJECTED:")
    assert ctx.sql_log[-1]["status"] == "rejected"


@pytest.mark.parametrize("name", ["../x.csv", "a b.csv", "x.txt", "", "x/y.csv", "a" * 80 + ".csv"])
async def test_run_sql_rejects_bad_output_file_names(name: str, tmp_path: Path) -> None:
    tools, _ = _tools(Settings(_env_file=None), tmp_path)
    out = await tools["run_sql"].ainvoke({"query": "SELECT 1", "output_file": name})
    assert out.startswith("SQL REJECTED: output_file")


async def test_describe_table_rejects_unknown_and_injected_names(tmp_path: Path) -> None:
    tools, _ = _tools(Settings(_env_file=None), tmp_path)
    for bad in (
        "secrets",
        "orders; DROP TABLE x",
        "pg_shadow",
        "../orders",
        "public.schema_migrations",
    ):
        out = await tools["describe_table"].ainvoke({"table_name": bad})
        assert out.startswith("Unknown table")


async def test_export_artifact_refuses_paths_outside_the_sandbox_home(tmp_path: Path) -> None:
    tools, _ = _tools(Settings(_env_file=None), tmp_path)
    for bad in ("/etc/passwd", "/home/user/../../etc/passwd", "/root/.ssh/id_rsa"):
        out = await tools["export_artifact"].ainvoke({"path": bad})
        assert out.startswith("EXPORT REJECTED")


_live = get_settings()
live = pytest.mark.skipif(
    not (_live.analyst_database_url and _live.e2b_api_key), reason="Neon/E2B not configured"
)


@pytest.mark.integration
@live
async def test_list_and_describe_tables_against_the_real_database(tmp_path: Path) -> None:
    tools, _ = _tools(_live, tmp_path)
    listing = await tools["list_tables"].ainvoke({})
    for table in ("orders", "customers", "reviews", "regions"):
        assert f"- {table} (" in listing
    described = await tools["describe_table"].ainvoke({"table_name": "orders"})
    assert "status text NOT NULL -- delivered | cancelled" in described
    assert "FOREIGN KEY" in described and "Sample rows" in described


@pytest.mark.integration
@live
async def test_run_sql_puts_the_full_csv_in_the_sandbox_and_returns_only_a_summary(
    tmp_path: Path,
) -> None:
    roomy = _live.model_copy(update={"sql_max_rows": 100_000})  # above the 50,021 orders
    async with SandboxManager(roomy) as manager:
        tools, ctx = _tools(roomy, tmp_path, manager)
        out = await tools["run_sql"].ainvoke(
            {
                "query": "SELECT order_id, total_amount FROM analytics.orders ORDER BY order_id",
                "output_file": "orders_all.csv",
            }
        )
        assert out.startswith("OK: 50,021 rows x 2 columns saved to /home/user/data/orders_all.csv")
        assert len(out) <= _live.max_tool_output_chars  # a summary, never the bulk data
        sandbox = await manager.get("t")
        lines = await sandbox.aexecute("wc -l < /home/user/data/orders_all.csv")
        assert lines.output.strip() == "50022"  # header + every row reached the sandbox
        assert ctx.sql_log[-1]["status"] == "ok"


@pytest.mark.integration
@live
async def test_row_cap_is_reported_to_the_model(tmp_path: Path) -> None:
    capped = _live.model_copy(update={"sql_max_rows": 100})
    async with SandboxManager(capped) as manager:
        tools, _ = _tools(capped, tmp_path, manager)
        out = await tools["run_sql"].ainvoke(
            {"query": "SELECT * FROM analytics.order_items", "output_file": "items.csv"}
        )
        assert "100 rows" in out and "WARNING: result was cut at the 100-row cap" in out


@pytest.mark.integration
@live
async def test_sql_errors_and_timeouts_come_back_as_text_the_model_can_act_on(
    tmp_path: Path,
) -> None:
    quick = _live.model_copy(update={"sql_statement_timeout_ms": 300})
    async with SandboxManager(quick) as manager:
        tools, _ = _tools(quick, tmp_path, manager)
        bad_column = await tools["run_sql"].ainvoke(
            {"query": "SELECT nope FROM analytics.orders", "output_file": "a.csv"}
        )
        assert bad_column.startswith("SQL ERROR:") and "nope" in bad_column
        slow = await tools["run_sql"].ainvoke({"query": CROSS_JOIN, "output_file": "b.csv"})
        assert slow.startswith("SQL TIMEOUT:")
