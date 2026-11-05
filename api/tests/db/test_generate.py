"""Planted insights must actually be present in the generated data (no database needed)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import pytest

from db import planted as P
from db.generate import Dataset, generate


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return generate()


def _monthly_revenue(ds: Dataset) -> dict[tuple[int, int], float]:
    revenue: dict[tuple[int, int], float] = defaultdict(float)
    for o in ds.orders:
        if o.status == "delivered":
            revenue[(o.order_date.year, o.order_date.month)] += o.total_amount
    return revenue


def test_generation_is_deterministic(ds: Dataset) -> None:
    assert generate() == ds
    assert generate(seed=P.SEED + 1) != ds


def test_dataset_size_fits_free_tier(ds: Dataset) -> None:
    total = sum(len(rows) for rows in ds.tables().values())
    assert 100_000 <= total <= 300_000


def test_revenue_dip_in_march_2025(ds: Dataset) -> None:
    rev = _monthly_revenue(ds)
    neighbours = (rev[(2025, 2)] + rev[(2025, 4)]) / 2
    assert rev[(2025, 3)] < 0.85 * neighbours


def test_dip_is_caused_by_the_outage_region(ds: Dataset) -> None:
    south = 1 + P.REGION_NAMES.index(P.OUTAGE_REGION)
    outage_days = (P.OUTAGE_END - P.OUTAGE_START).days + 1

    def per_day(start: date, end: date) -> float:
        days = (end - start).days + 1
        n = sum(
            1 for o in ds.orders if o.region_id == south and start <= o.order_date.date() <= end
        )
        return n / days

    during = per_day(P.OUTAGE_START, P.OUTAGE_END)
    before = per_day(P.OUTAGE_START - timedelta(days=14), P.OUTAGE_START - timedelta(days=1))
    assert outage_days == 27
    assert during < 0.1 * before


def test_high_return_category(ds: Dataset) -> None:
    category = {p.product_id: p.category for p in ds.products}
    total: Counter[str] = Counter()
    returned: Counter[str] = Counter()
    for item in ds.order_items:
        total[category[item.product_id]] += 1
        returned[category[item.product_id]] += item.is_returned
    rates = {c: returned[c] / total[c] for c in total}
    assert rates[P.HIGH_RETURN_CATEGORY] > 0.25
    assert all(r < 0.10 for c, r in rates.items() if c != P.HIGH_RETURN_CATEGORY)


def test_high_churn_segment(ds: Dataset) -> None:
    last_order: dict[int, datetime] = {}
    for o in ds.orders:
        last_order[o.customer_id] = o.order_date
    seen: Counter[str] = Counter()
    churned: Counter[str] = Counter()
    for c in ds.customers:
        if c.signup_date < P.CHURN_SIGNUP_BEFORE and c.customer_id in last_order:
            seen[c.segment] += 1
            churned[c.segment] += last_order[c.customer_id].date() < P.CHURN_CUTOFF
    rates = {s: churned[s] / seen[s] for s in seen}
    assert rates[P.HIGH_CHURN_SEGMENT] > 0.5
    assert all(r < 0.35 for s, r in rates.items() if s != P.HIGH_CHURN_SEGMENT)


def test_holiday_seasonality(ds: Dataset) -> None:
    rev = _monthly_revenue(ds)
    for year in (2024, 2025):
        other = [v for (y, m), v in rev.items() if y == year and m not in P.SEASON_PEAK_MONTHS]
        mean_other = sum(other) / len(other)
        assert rev[(year, 11)] > 1.3 * mean_other
        assert rev[(year, 12)] > 1.3 * mean_other


def test_messy_data_is_present(ds: Dataset) -> None:
    assert sum(c.email is None for c in ds.customers) == P.NULL_EMAIL_CUSTOMERS
    emails = Counter(c.email for c in ds.customers if c.email)
    assert sum(1 for n in emails.values() if n > 1) == P.DUPLICATE_CUSTOMERS
    assert sum(p.cost_usd is None for p in ds.products) == P.NULL_COST_PRODUCTS
    assert sum(r.rating is None for r in ds.reviews) >= P.NULL_RATING_REVIEWS - 5
    keys = Counter((p.order_id, p.amount, p.status) for p in ds.payments if p.status == "captured")
    assert sum(1 for n in keys.values() if n > 1) == P.DUPLICATE_PAYMENTS


def test_injection_reviews_present(ds: Dataset) -> None:
    texts = {r.review_text for r in ds.reviews}
    assert set(P.INJECTION_REVIEW_TEXTS) <= texts


def test_referential_integrity(ds: Dataset) -> None:
    customers = {c.customer_id for c in ds.customers}
    orders = {o.order_id for o in ds.orders}
    products = {p.product_id for p in ds.products}
    assert all(o.customer_id in customers for o in ds.orders)
    assert all(i.order_id in orders and i.product_id in products for i in ds.order_items)
    assert all(p.order_id in orders for p in ds.payments)
    assert all(r.product_id in products and r.customer_id in customers for r in ds.reviews)


def test_order_totals_match_line_items(ds: Dataset) -> None:
    sums: dict[int, float] = defaultdict(float)
    for i in ds.order_items:
        sums[i.order_id] += round(i.quantity * i.unit_price * (1 - i.discount_pct / 100), 2)
    assert all(abs(o.total_amount - sums[o.order_id]) < 0.02 for o in ds.orders)
