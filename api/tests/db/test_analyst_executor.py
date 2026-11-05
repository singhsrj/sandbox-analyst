"""run_readonly against the live database: caps, timeouts and no leaked session state."""

from __future__ import annotations

import psycopg
import pytest

from app.config import get_settings
from app.db.analyst import run_readonly
from app.security.sql_validator import validate_select

pytestmark = pytest.mark.integration
settings = get_settings()
live = pytest.mark.skipif(settings.analyst_database_url is None, reason="Neon not configured")

CROSS_JOIN = "SELECT count(*) FROM analytics.order_items a CROSS JOIN analytics.order_items b"


@live
async def test_returns_typed_columns_and_rows() -> None:
    result = await run_readonly(
        validate_select("SELECT region_id, region_name FROM analytics.regions ORDER BY 1"), settings
    )
    assert result.columns == ["region_id", "region_name"]
    assert result.dtypes == ["int2", "text"]
    assert result.row_count == 5 and not result.truncated
    assert result.to_csv_bytes().decode().splitlines()[0] == "region_id,region_name"


@live
async def test_row_cap_truncates_instead_of_loading_everything() -> None:
    capped = settings.model_copy(update={"sql_max_rows": 50})
    result = await run_readonly(validate_select("SELECT * FROM analytics.order_items"), capped)
    assert result.row_count == 50 and result.truncated


@live
async def test_statement_timeout_cancels_and_leaves_no_state_behind() -> None:
    quick = settings.model_copy(update={"sql_statement_timeout_ms": 300})
    with pytest.raises(psycopg.errors.QueryCanceled):
        await run_readonly(validate_select(CROSS_JOIN), quick)
    # ADR-009: SET LOCAL must not leak through the pooler into the next connection.
    async with await psycopg.AsyncConnection.connect(
        settings.secret("analyst_database_url"), prepare_threshold=None
    ) as conn:
        cur = await conn.execute("SHOW statement_timeout")
        assert await cur.fetchone() == ("15s",)
        cur = await conn.execute("SHOW transaction_read_only")
        assert await cur.fetchone() == ("on",)
