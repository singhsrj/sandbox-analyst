"""Cost/size heuristic that decides which queries need a human's approval in "normal" mode.

Approval modes (ADR-022):
  * off    - never ask (CLI, evals)
  * normal - ask only when this module flags the query
  * strict - ask before every run_sql call

The validator (sql_validator.py) decides what is ALLOWED; this module only decides what deserves
a second look because it is likely to be slow, expensive or to return a misleading, truncated
result. It is deliberately simple and deterministic: LangChain re-runs the predicate when a paused
run resumes, so the same query must always get the same answer.

Flags:
  * a join with no join condition (ON/USING) onto a large table: a cartesian product
  * the query returns raw rows of a large table with no WHERE, GROUP BY, aggregate, DISTINCT or
    LIMIT: the result would be cut at the row cap and look complete when it is not
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# Tables bigger than the default 10,000-row result cap (counts: docs/dataset.md, M1 seed).
LARGE_TABLES = frozenset({"order_items", "orders", "payments", "reviews"})


@dataclass(frozen=True)
class RiskAssessment:
    flagged: bool
    reasons: list[str] = field(default_factory=list)


def _table_name(node: exp.Expression | None) -> str | None:
    if isinstance(node, exp.Table) and isinstance(node.this, exp.Identifier):
        return node.name.lower()
    return None


def _cte_names(tree: exp.Expr) -> set[str]:
    return {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}


def _is_aggregated(select: exp.Select) -> bool:
    if select.args.get("group") or select.args.get("distinct"):
        return True
    for projection in select.expressions:
        for func in projection.find_all(exp.AggFunc):
            # An aggregate inside a window (OVER ...) does not collapse rows.
            if not isinstance(func.parent, exp.Window):
                return True
    return False


def _outer_select(tree: exp.Expr) -> exp.Select | None:
    if isinstance(tree, exp.Select):
        return tree
    return None  # UNION / INTERSECT / EXCEPT: judged by their parts' joins only


def assess_query(sql: str) -> RiskAssessment:
    """Flag queries that deserve approval. Unparseable SQL is not flagged: the validator
    rejects it anyway and the model gets that error instead of a pointless approval card."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError:
        return RiskAssessment(False)
    if len(statements) != 1:
        return RiskAssessment(False)
    tree = statements[0]
    ctes = _cte_names(tree)
    reasons: list[str] = []

    for join in tree.find_all(exp.Join):
        if join.args.get("on") is not None or join.args.get("using"):
            continue
        name = _table_name(join.this)
        if name and name not in ctes and name in LARGE_TABLES:
            reasons.append(
                f"joins analytics.{name} without a join condition (cartesian product: the row "
                "count multiplies)"
            )

    select = _outer_select(tree)
    if select is not None:
        source = select.args.get("from_") or select.args.get("from")
        name = _table_name(source.this) if isinstance(source, exp.From) else None
        limit = select.args.get("limit")
        if (
            name
            and name not in ctes
            and name in LARGE_TABLES
            and select.args.get("where") is None
            and limit is None
            and not _is_aggregated(select)
        ):
            reasons.append(
                f"returns raw rows of analytics.{name} with no filter, aggregation or LIMIT (the "
                "result will hit the row cap and be incomplete)"
            )

    return RiskAssessment(bool(reasons), reasons)
