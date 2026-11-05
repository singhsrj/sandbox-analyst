"""Load the deterministic synthetic dataset into the analytics schema.

Usage: uv run python -m db.seed
Runs as the admin role. Truncates and reloads every analytics table, so it is safe to re-run and
always yields identical data (same seed). Run `python -m db.migrate` first.
"""

from __future__ import annotations

import psycopg

from app.config import get_settings
from db.generate import Dataset, generate

COLUMNS = {
    "regions": ("region_id", "region_name"),
    "marketing_campaigns": (
        "campaign_id",
        "campaign_name",
        "channel",
        "start_date",
        "end_date",
        "budget_usd",
    ),
    "customers": (
        "customer_id",
        "full_name",
        "email",
        "region_id",
        "segment",
        "signup_date",
        "acquisition_campaign_id",
    ),
    "products": ("product_id", "product_name", "category", "price_usd", "cost_usd"),
    "orders": ("order_id", "customer_id", "region_id", "order_date", "status", "total_amount"),
    "order_items": (
        "order_item_id",
        "order_id",
        "product_id",
        "quantity",
        "unit_price",
        "discount_pct",
        "is_returned",
    ),
    "payments": ("payment_id", "order_id", "amount", "method", "status", "paid_at"),
    "reviews": ("review_id", "product_id", "customer_id", "rating", "review_text", "created_at"),
}


def load(conn: psycopg.Connection, dataset: Dataset) -> dict[str, int]:
    tables = dataset.tables()
    with conn.transaction():
        conn.execute(
            "TRUNCATE "
            + ", ".join(f"analytics.{t}" for t in reversed(list(tables)))
            + " RESTART IDENTITY"
        )
        for table, rows in tables.items():
            cols = ", ".join(COLUMNS[table])
            with (
                conn.cursor() as cur,
                cur.copy(f"COPY analytics.{table} ({cols}) FROM STDIN") as cp,
            ):
                for row in rows:
                    cp.write_row(row)
    conn.execute("ANALYZE")
    return {table: len(rows) for table, rows in tables.items()}


def main() -> None:
    settings = get_settings()
    dataset = generate()
    with psycopg.connect(settings.secret("admin_database_url"), autocommit=True) as conn:
        counts = load(conn, dataset)
    for table, n in counts.items():
        print(f"{table:22s} {n:>8,}")
    print(f"{'total':22s} {sum(counts.values()):>8,}")


if __name__ == "__main__":
    main()
