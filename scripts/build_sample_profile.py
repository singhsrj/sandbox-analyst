"""Build the static data profile of the sample shop data: api/profiles/sample.json.

    PYTHONPATH=api uv run python scripts/build_sample_profile.py            # with the AI summary
    PYTHONPATH=api uv run python scripts/build_sample_profile.py --no-summary
    PYTHONPATH=api uv run python scripts/build_sample_profile.py --reuse-summary  # keep the old one

Run it again after the sample data changes (db/seed.py). Reads the `analytics` schema as the
read-only `analyst_ro` role (ANALYST_DATABASE_URL), profiles every table with
app/profiling/profiler.py, and asks the configured model for a short summary written ONLY from the
computed profile: no rows, and no values of personal-data columns, are sent to the model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql as pgsql

from app.config import get_settings
from app.profiling.profiler import feature_importance, profile_dataset, summary_facts
from app.security.sql_validator import ANALYTICS_TABLES

OUT = Path(__file__).resolve().parents[1] / "api" / "profiles" / "sample.json"
NUMERIC_TYPES = ("integer", "smallint", "bigint", "numeric", "real", "double precision")

SUMMARY_PROMPT = """You are describing a dataset to a data analyst who is about to query it.
Below is a statistical profile computed from the data (no raw rows). Write a summary of 120-180
words in plain prose (no headings, no bullet points, no markdown): what the data is about, the grain
of the main tables and how they connect, the time span, and 2-3 properties an analyst should know
before querying (skew, outliers, missing values, imbalances). Use only facts from the profile;
do not guess at causes. Do not mention personal data values.

PROFILE
{facts}"""


def _catalog(conn: psycopg.Connection) -> dict[str, Any]:
    tables = conn.execute(
        "SELECT c.relname, coalesce(obj_description(c.oid, 'pg_class'), '') FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'analytics' AND c.relkind = 'r' ORDER BY c.relname"
    ).fetchall()
    columns = conn.execute(
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), "
        "coalesce(col_description(a.attrelid, a.attnum), '') FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'analytics' AND c.relkind = 'r' AND a.attnum > 0 "
        "AND NOT a.attisdropped ORDER BY c.relname, a.attnum"
    ).fetchall()
    fks = conn.execute(
        "SELECT cl.relname, a.attname, rcl.relname, ra.attname FROM pg_constraint k "
        "JOIN pg_class cl ON cl.oid = k.conrelid JOIN pg_class rcl ON rcl.oid = k.confrelid "
        "JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1] "
        "JOIN pg_attribute ra ON ra.attrelid = k.confrelid AND ra.attnum = k.confkey[1] "
        "WHERE k.contype = 'f' AND k.connamespace = 'analytics'::regnamespace "
        "ORDER BY 1, 2"
    ).fetchall()
    types: dict[str, dict[str, str]] = {}
    notes: dict[str, dict[str, str]] = {}
    for table, col, type_, note in columns:
        types.setdefault(table, {})[col] = type_
        notes.setdefault(table, {})[col] = note
    return {
        "descriptions": dict(tables),
        "types": types,
        "notes": notes,
        "relationships": [
            {"from_table": t, "from_column": c, "to_table": rt, "to_column": rc}
            for t, c, rt, rc in fks
        ],
    }


def _load(conn: psycopg.Connection, table: str, types: dict[str, str]) -> pd.DataFrame:
    if table not in ANALYTICS_TABLES:  # names come from the catalog; never trust them blindly
        raise ValueError(f"unexpected table {table!r}")
    cur = conn.execute(
        pgsql.SQL("SELECT * FROM {}.{}").format(
            pgsql.Identifier("analytics"), pgsql.Identifier(table)
        )
    )
    frame = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description or []])
    for col, type_ in types.items():
        if type_.startswith(NUMERIC_TYPES):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        elif type_ == "date" or type_.startswith("timestamp"):
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
        elif type_ == "boolean":
            frame[col] = frame[col].astype("boolean")
    return frame


def _returns_frame(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per order line with what is known about it, to see what relates to returns."""
    items = t["order_items"].merge(t["products"][["product_id", "category"]], on="product_id")
    orders = (
        t["orders"]
        .merge(t["regions"], on="region_id")
        .merge(t["customers"][["customer_id", "segment"]], on="customer_id")
    )
    frame = items.merge(
        orders[["order_id", "order_date", "status", "region_name", "segment"]], on="order_id"
    )
    return frame[
        [
            "is_returned",
            "quantity",
            "unit_price",
            "discount_pct",
            "category",
            "region_name",
            "segment",
            "status",
            "order_date",
        ]
    ].astype({"is_returned": "bool"})


def _summary(facts: str) -> dict[str, Any]:
    from app.agent.models import get_model

    settings = get_settings()
    reply = get_model(settings).invoke(SUMMARY_PROMPT.format(facts=facts))
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    return {"text": _plain(text), "model": settings.model, "ai_generated": True}


def _plain(text: str) -> str:
    """Collapse whitespace and swap the typographic hyphens/spaces models like for plain ones."""
    pairs = (("\u2011", "-"), ("\u2010", "-"), ("\u202f", " "), ("\u00a0", " "))
    for odd, plain in pairs:
        text = text.replace(odd, plain)
    return " ".join(text.split())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-summary", action="store_true", help="skip the model call")
    parser.add_argument(
        "--reuse-summary",
        action="store_true",
        help="keep the summary from the existing file (when only presentation changed)",
    )
    args = parser.parse_args()

    settings = get_settings()
    with psycopg.connect(settings.secret("analyst_database_url"), prepare_threshold=None) as conn:
        conn.read_only = True
        catalog = _catalog(conn)
        tables = {
            name: _load(conn, name, catalog["types"][name]) for name in catalog["descriptions"]
        }

    importance = feature_importance(
        _returns_frame(tables),
        "is_returned",
        label="order lines (order_items joined with products, orders, regions, customers)",
        description="Which properties of an order line tell you most about whether it is returned.",
    )
    profile = profile_dataset(
        tables,
        dataset_id="sample",
        name="Sample shop data",
        source="postgres",
        descriptions=catalog["descriptions"],
        db_types=catalog["types"],
        notes=catalog["notes"],
        relationships=catalog["relationships"],
        importance=importance,
    )
    if args.reuse_summary and OUT.exists():
        profile["summary"] = json.loads(OUT.read_text(encoding="utf-8")).get("summary")
    elif not args.no_summary:
        profile["summary"] = _summary(summary_facts(profile))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(profile, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
