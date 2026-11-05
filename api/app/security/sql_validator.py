"""Validate model-written SQL before it ever reaches the database.

This is the FIRST of two independent layers (the second is the `analyst_ro` role, which only holds
SELECT on the `analytics` schema, see db/roles.sql). Rules, enforced on the parsed AST so comment
tricks and odd formatting do not matter:

  * exactly one statement, and it must be a query (SELECT / UNION / INTERSECT / EXCEPT, with CTEs)
  * no DML/DDL/COPY/SET/etc. anywhere in the tree (this also catches data-modifying CTEs)
  * no SELECT ... INTO, no row locks (FOR UPDATE / FOR SHARE)
  * every table must be one of the known `analytics` tables (or a CTE defined in the query);
    system catalogs, `information_schema`, other schemas and table functions are rejected
  * function calls must be known to sqlglot or on a small allowlist; unknown ones such as
    pg_sleep, pg_read_file or dblink are rejected

Errors are written for the model to read and fix its query, not just to say "no".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ANALYTICS_SCHEMA = "analytics"
ANALYTICS_TABLES = frozenset(
    {
        "regions",
        "marketing_campaigns",
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "reviews",
    }
)

MAX_SQL_CHARS = 20_000

_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# Anything that changes state, changes settings, runs code or is otherwise not a plain read.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "AlterTable",
        "TruncateTable",
        "Copy",
        "Set",
        "SetItem",
        "Command",
        "Use",
        "Grant",
        "Revoke",
        "Transaction",
        "Commit",
        "Rollback",
        "Analyze",
        "Describe",
        "Show",
        "Pragma",
        "Kill",
        "LoadData",
        "Into",
        "Lock",
        "Comment",
        "Declare",
        "Refresh",
        "Cache",
        "Uncache",
        "Attach",
        "Detach",
    )
    if hasattr(exp, name)
)

# Functions sqlglot does not model as typed expressions but that are safe, read-only and common in
# analysis. Everything else that parses as an "anonymous" function is rejected.
ALLOWED_ANONYMOUS_FUNCTIONS = frozenset(
    {
        "age",
        "bool_and",
        "bool_or",
        "btrim",
        "cbrt",
        "concat_ws",
        "corr",
        "covar_pop",
        "covar_samp",
        "date_part",
        "div",
        "initcap",
        "justify_days",
        "left",
        "lpad",
        "ltrim",
        "make_date",
        "mode",
        "regexp_match",
        "regexp_matches",
        "regexp_replace",
        "regr_intercept",
        "regr_r2",
        "regr_slope",
        "right",
        "rpad",
        "rtrim",
        "split_part",
        "stddev_pop",
        "stddev_samp",
        "to_char",
        "to_date",
        "to_timestamp",
        "trunc",
        "var_pop",
        "var_samp",
        "width_bucket",
    }
)


class SqlValidationError(ValueError):
    """The SQL was rejected. The message is safe to show to the model and the user."""


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    tables: frozenset[str] = field(default_factory=frozenset)  # analytics tables referenced


def _ident(node: exp.Expression | None) -> str:
    if node is None:
        return ""
    name = node.name
    quoted = bool(isinstance(node, exp.Identifier) and node.args.get("quoted"))
    return name if quoted else name.lower()


def _visible_ctes(table: exp.Table) -> set[str]:
    """CTE names that a table reference can legitimately resolve to, following PostgreSQL scoping.

    A (non-recursive) CTE body can only see CTEs defined BEFORE it in the same WITH clause, never
    itself. A reference to its own name therefore resolves to a REAL table, which is how
    `WITH pg_shadow AS (SELECT * FROM pg_shadow) ...` would otherwise slip past a naive check.
    """
    visible: set[str] = set()
    child: Any = table
    parent: Any = table.parent
    while parent is not None:
        if isinstance(parent, exp.CTE) and isinstance(parent.parent, exp.With):
            siblings = parent.parent.expressions
            index = next(i for i, c in enumerate(siblings) if c is parent)
            visible |= {_ident(c.args.get("alias")) for c in siblings[:index]}
        elif isinstance(parent, exp.Query):
            with_clause = parent.args.get("with_") or parent.args.get("with")
            if isinstance(with_clause, exp.With) and child is not with_clause:
                visible |= {_ident(c.args.get("alias")) for c in with_clause.expressions}
        child, parent = parent, parent.parent
    return visible


def validate_select(sql: str) -> ValidatedQuery:
    """Return the validated query, or raise `SqlValidationError` with a fixable message."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlValidationError("The query is empty. Provide a single SELECT statement.")
    if "\x00" in sql:
        raise SqlValidationError("The query contains a NUL byte.")
    if len(sql) > MAX_SQL_CHARS:
        raise SqlValidationError(f"The query is too long (max {MAX_SQL_CHARS} characters).")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise SqlValidationError(
            f"The query could not be parsed as PostgreSQL: {str(exc).splitlines()[0][:200]}"
        ) from exc

    if len(statements) != 1:
        raise SqlValidationError(
            "Exactly one SQL statement is allowed; remove the extra statements/semicolons."
        )
    tree = statements[0]

    if not isinstance(tree, _ALLOWED_ROOTS):
        raise SqlValidationError(
            f"Only SELECT queries are allowed (got {type(tree).__name__.upper()}). "
            "This tool is read-only."
        )

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlValidationError(
                f"{type(node).__name__.upper()} is not allowed. Only plain read-only SELECT "
                "queries (optionally with CTEs) can be run."
            )

    for with_clause in tree.find_all(exp.With):
        if with_clause.args.get("recursive"):
            raise SqlValidationError(
                "WITH RECURSIVE is not allowed. Use a plain CTE or window functions."
            )

    referenced: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = _ident(table.this)
        schema = _ident(table.args.get("db"))
        catalog = _ident(table.args.get("catalog"))
        if not name or not isinstance(table.this, exp.Identifier):
            raise SqlValidationError(
                "Table functions and unnamed table sources are not allowed in FROM/JOIN."
            )
        if catalog:
            raise SqlValidationError("Cross-database references are not allowed.")
        if not schema and name in _visible_ctes(table):
            continue  # resolves to a CTE that is in scope at this point
        if schema and schema != ANALYTICS_SCHEMA:
            raise SqlValidationError(
                f"Schema '{schema}' is not accessible. Only the '{ANALYTICS_SCHEMA}' schema can "
                "be queried."
            )
        if name not in ANALYTICS_TABLES:
            raise SqlValidationError(
                f"Unknown table '{name}' (a CTE can only reference CTEs defined before it). "
                f"Available tables: {', '.join(sorted(ANALYTICS_TABLES))}."
            )
        referenced.add(name)

    for func in tree.find_all(exp.Anonymous):
        fname = str(func.name).lower()
        if fname not in ALLOWED_ANONYMOUS_FUNCTIONS:
            raise SqlValidationError(
                f"Function '{fname}' is not allowed. Use standard aggregate, date, string and math "
                "functions only."
            )

    return ValidatedQuery(sql=sql.strip().rstrip(";").strip(), tables=frozenset(referenced))
