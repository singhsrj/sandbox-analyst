"""The normal-mode approval heuristic: flags table dumps and cartesian joins, nothing else."""

from __future__ import annotations

import pytest

from app.security.sql_risk import assess_query


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM analytics.orders",
        "SELECT order_id, total_amount FROM analytics.order_items",
        "SELECT o.*, p.* FROM analytics.orders o, analytics.payments p",
        "SELECT * FROM analytics.orders o CROSS JOIN analytics.order_items i LIMIT 10",
        "SELECT review_text, rating FROM analytics.reviews",
        "SELECT * FROM analytics.orders o JOIN analytics.customers c ON c.customer_id = o.customer_id",
    ],
)
def test_dumps_and_cartesian_joins_are_flagged(sql: str) -> None:
    result = assess_query(sql)
    assert result.flagged and result.reasons


@pytest.mark.parametrize(
    "sql",
    [
        # aggregations over the whole table are normal analysis
        "SELECT date_trunc('month', order_date) m, sum(total_amount) FROM analytics.orders GROUP BY 1",
        "SELECT count(*) FROM analytics.order_items",
        "SELECT DISTINCT status FROM analytics.orders",
        # filtered or limited reads
        "SELECT * FROM analytics.orders WHERE order_date >= '2025-03-01'",
        "SELECT * FROM analytics.reviews LIMIT 50",
        # small tables
        "SELECT * FROM analytics.products",
        "SELECT * FROM analytics.customers",
        # joins with conditions
        "SELECT o.order_id, p.amount FROM analytics.orders o JOIN analytics.payments p "
        "ON p.order_id = o.order_id WHERE o.status = 'delivered'",
        # CROSS JOIN onto a one-row CTE is a common, harmless idiom
        "WITH t AS (SELECT sum(total_amount) s FROM analytics.orders) "
        "SELECT o.region_id, sum(o.total_amount) / t.s FROM analytics.orders o CROSS JOIN t "
        "GROUP BY o.region_id, t.s",
        # the outer query reads a CTE, the CTE aggregates
        "WITH daily AS (SELECT order_date::date d, count(*) n FROM analytics.orders GROUP BY 1) "
        "SELECT * FROM daily",
        # unparseable SQL is left to the validator
        "SELEC nonsense FROM",
    ],
)
def test_normal_analysis_is_not_flagged(sql: str) -> None:
    assert not assess_query(sql).flagged


def test_window_aggregates_do_not_count_as_aggregation() -> None:
    sql = "SELECT order_id, sum(total_amount) OVER (ORDER BY order_date) FROM analytics.orders"
    assert assess_query(sql).flagged


def test_same_query_always_gets_the_same_answer() -> None:
    """LangChain re-runs the predicate on resume; it must be deterministic."""
    sql = "SELECT * FROM analytics.payments"
    assert assess_query(sql) == assess_query(sql)
