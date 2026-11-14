"""Run every golden question's reference SQL and show the results (no model involved).

The expected answers in evals/golden/questions.yaml come from here. The SQL runs as the read-only
`analyst_ro` role and through the same validator the agent uses, so a reference query can never
use anything the agent is not allowed to.

When a question has `cross_check_sql` (a second, independently written query), both run and must
agree within CROSS_CHECK_TOLERANCE; any disagreement is reported and the exit code is 1. One query
can be wrong in ways that look right; two different ones are rarely wrong in the same way.

Usage:  uv run python -m evals.golden_check [--batch N] [--markdown PATH]
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import yaml

from app.config import get_settings
from app.security.sql_validator import validate_select

GOLDEN = Path(__file__).parent / "golden" / "questions.yaml"
CROSS_CHECK_TOLERANCE = 1e-4  # relative; absorbs cent-level rounding of order totals


def load(batch: int | None = None) -> list[dict[str, Any]]:
    data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    questions: list[dict[str, Any]] = data["questions"]
    return [q for q in questions if batch is None or q.get("batch") == batch]


def fmt(value: Any) -> str:
    if isinstance(value, Decimal | float):
        return f"{float(value):,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def run(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    validated = validate_select(sql)
    url = get_settings().secret("analyst_database_url")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '30s'")
        cur = conn.execute(validated.sql)
        columns = [d.name for d in cur.description or []]
        return columns, cur.fetchall()


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, int | float | Decimal) and isinstance(b, int | float | Decimal):
        x, y = float(a), float(b)
        return abs(x - y) <= max(CROSS_CHECK_TOLERANCE * max(abs(x), abs(y)), 1e-9)
    return str(a) == str(b)


def disagreement(first: list[tuple[Any, ...]], second: list[tuple[Any, ...]]) -> str | None:
    """Why two result sets differ (compared row by row, in their ORDER BY order), or None."""
    if len(first) != len(second):
        return f"{len(first)} rows vs {len(second)} rows"
    for i, (r1, r2) in enumerate(zip(first, second, strict=True)):
        if len(r1) != len(r2):
            return f"row {i + 1}: {len(r1)} columns vs {len(r2)}"
        for v1, v2 in zip(r1, r2, strict=True):
            if not _same(v1, v2):
                return f"row {i + 1}: {fmt(v1)} vs {fmt(v2)}"
    return None


def table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", type=int)
    parser.add_argument("--markdown", help="write a review sheet to this path")
    args = parser.parse_args()

    out: list[str] = []
    mismatches: list[str] = []
    for q in load(args.batch):
        heading = f"### {q['id']} ({q['category']}, {q['difficulty']})"
        out.append(f"{heading}\n\n**{q['question'].strip()}**\n")
        if q.get("reference_sql"):
            columns, rows = run(q["reference_sql"])
            out.append(table(columns, rows) + "\n")
            if q.get("cross_check_sql"):
                _, check_rows = run(q["cross_check_sql"])
                why = disagreement(rows, check_rows)
                if why:
                    mismatches.append(f"{q['id']}: {why}")
                    out.append(f"**CROSS-CHECK MISMATCH:** {why}\n")
                else:
                    out.append("_Cross-check: a second, independent query agrees._\n")
        else:
            out.append(f"_No SQL: the right answer is a {q['expected']['kind']}._\n")
    text = "\n".join(out)
    print(text)
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
    if mismatches:
        print("\nCross-check mismatches:\n  " + "\n  ".join(mismatches), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
