"""Integration tests against the live Neon database: can analyst_ro ever write?

Skipped automatically when database credentials are not configured (e.g. in CI).
Every attack below is expected to FAIL at the database, independent of any SQL validator.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import errors

from app.config import get_settings

pytestmark = pytest.mark.integration

_settings = get_settings()
_have_db = all(
    getattr(_settings, name) is not None
    for name in ("admin_database_url", "analyst_database_url", "app_database_url")
)
skip_without_db = pytest.mark.skipif(not _have_db, reason="Neon credentials not configured")


def _connect(name: str) -> psycopg.Connection:
    url = getattr(_settings, name)
    assert url is not None
    return psycopg.connect(url.get_secret_value(), connect_timeout=30, autocommit=True)


@pytest.fixture
def analyst() -> Iterator[psycopg.Connection]:
    """Connection through Neon's pooler. The pooler reuses server connections WITHOUT resetting
    session state (see docs/decisions.md ADR-009), so reset before and after every test."""
    with _connect("analyst_database_url") as conn:
        conn.execute("RESET ALL")
        try:
            yield conn
        finally:
            conn.execute("RESET ALL")


@pytest.fixture
def app() -> Iterator[psycopg.Connection]:
    with _connect("app_database_url") as conn:
        yield conn


@skip_without_db
def test_connects_as_the_expected_roles(
    analyst: psycopg.Connection, app: psycopg.Connection
) -> None:
    assert analyst.execute("SELECT current_user").fetchone() == ("analyst_ro",)
    assert app.execute("SELECT current_user").fetchone() == ("app_rw",)


@skip_without_db
def test_analyst_can_read_every_analytics_table(analyst: psycopg.Connection) -> None:
    for table in (
        "regions",
        "marketing_campaigns",
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "reviews",
    ):
        count = analyst.execute(f"SELECT count(*) FROM analytics.{table}").fetchone()  # noqa: S608
        assert count is not None and count[0] > 0, table


@skip_without_db
def test_role_level_settings_are_applied_through_the_pooler(analyst: psycopg.Connection) -> None:
    assert analyst.execute("SHOW default_transaction_read_only").fetchone() == ("on",)
    assert analyst.execute("SHOW statement_timeout").fetchone() == ("15s",)
    assert analyst.execute("SHOW search_path").fetchone() == ("analytics",)


@skip_without_db
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO analytics.regions VALUES (99, 'Hacked')",
        "UPDATE analytics.orders SET total_amount = 0",
        "DELETE FROM analytics.customers",
        "TRUNCATE analytics.orders",
        "DROP TABLE analytics.orders",
        "ALTER TABLE analytics.orders ADD COLUMN x int",
        "CREATE TABLE analytics.evil (x int)",
        "CREATE TABLE public.evil (x int)",
        "CREATE SCHEMA evil",
        "CREATE ROLE evil LOGIN",
        "GRANT ALL ON analytics.orders TO PUBLIC",
        "COMMENT ON TABLE analytics.orders IS 'pwned'",
        "COPY analytics.orders TO PROGRAM 'echo hi'",
    ],
)
def test_writes_and_ddl_are_denied(analyst: psycopg.Connection, statement: str) -> None:
    with pytest.raises((errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction)):
        analyst.execute(statement)


@skip_without_db
def test_privileges_hold_even_if_the_session_turns_read_only_off(
    analyst: psycopg.Connection,
) -> None:
    """The session CAN override default_transaction_read_only, so privileges are what protect us."""
    analyst.execute("SET default_transaction_read_only = off")
    assert analyst.execute("SHOW default_transaction_read_only").fetchone() == ("off",)
    with pytest.raises(errors.InsufficientPrivilege):
        analyst.execute("INSERT INTO analytics.regions VALUES (99, 'Hacked')")
    with pytest.raises(errors.InsufficientPrivilege):
        analyst.execute("DELETE FROM analytics.orders")


@skip_without_db
@pytest.mark.parametrize(
    "table", ["app.anything", "public.schema_migrations", "neon_auth.users_sync"]
)
def test_analyst_cannot_read_non_analytics_schemas(analyst: psycopg.Connection, table: str) -> None:
    with pytest.raises((errors.InsufficientPrivilege, errors.UndefinedTable)):
        analyst.execute(f"SELECT * FROM {table}")  # noqa: S608


@skip_without_db
def test_statement_timeout_cancels_slow_queries(analyst: psycopg.Connection) -> None:
    analyst.execute("SET statement_timeout = '500ms'")
    with pytest.raises(errors.QueryCanceled):
        analyst.execute("SELECT pg_sleep(5)")


@skip_without_db
def test_app_role_cannot_touch_analytics(app: psycopg.Connection) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        app.execute("SELECT * FROM analytics.orders LIMIT 1")


@skip_without_db
def test_app_role_can_use_its_own_schema(app: psycopg.Connection) -> None:
    app.execute("CREATE TABLE app._probe (x int)")
    try:
        app.execute("INSERT INTO app._probe VALUES (1)")
        assert app.execute("SELECT x FROM app._probe").fetchone() == (1,)
    finally:
        app.execute("DROP TABLE IF EXISTS app._probe")
