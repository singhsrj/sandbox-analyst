"""The golden-set scorer: it must accept the ways models write correct answers and reject wrong
ones, for every expectation kind used in evals/golden/questions.yaml."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from evals.golden_check import load
from evals.scoring import numbers_in, score

GOLDEN = {q["id"]: q for q in load()}


def check(
    qid: str, answer: str, sql: list[dict[str, Any]] | None = None, status: str = "ok"
) -> Any:
    return score(GOLDEN[qid], answer, sql or [], status)


def test_number_formats() -> None:
    assert numbers_in("$6,213,856.24 and 33.7% and 1.75x") == [6213856.24, 33.7, 1.75]
    assert numbers_in("about $2.36M, 154k, 4.2 million") == [2360000.0, 154000.0, 4200000.0]
    assert numbers_in("2025-03-03") == [2025.0, 3.0, 3.0]


@pytest.mark.parametrize(
    ("qid", "answer", "passes"),
    [
        ("q001", "There were 27,901 orders in 2025.", True),
        ("q001", "There were 27,902 orders in 2025.", False),  # counts are exact
        ("q002", "Total 2024 revenue was $6,213,856.24.", True),
        ("q002", "Revenue in 2024 was about $6.21M.", True),
        ("q002", "Revenue in 2024 was $6,900,000 including cancelled orders.", False),
        ("q014", "95.5% of 2024 buyers ordered again (1,920 of 2,011).", True),
        ("q015", "40 customers have no email.", True),
        ("q015", "41 customers have no email.", False),
    ],
)
def test_numbers(qid: str, answer: str, passes: bool) -> None:
    assert check(qid, answer).passed is passes


def test_highest_region_must_come_first() -> None:
    good = "South brought in the most ($2,359,551.24), followed by North $1,817,925.69."
    bad = "North had $1,817,925.69 and South $2,359,551.24, the highest."
    assert check("q006", good).passed
    result = check("q006", bad)
    assert not result.passed and "North before South" in result.reasons[0]


def test_return_rate_needs_the_category_and_the_rate() -> None:
    assert check("q008", "Footwear has the highest return rate at 33.7%.").passed
    assert check("q008", "Footwear, roughly 34% of items.").passed  # within 1 point
    assert not check("q008", "Toys has the highest return rate at 33.7%.").passed


def test_every_category_rating_is_required() -> None:
    full = "Books 4.20, Beauty 4.16, Apparel 4.15, Sports 4.15, Home 4.13, Electronics 4.12, Toys 4.11, Footwear 3.11"
    assert check("q009", full).passed
    partial = check("q009", "Books 4.20 is best and Footwear 3.11 is worst.")
    assert not partial.passed and 0 < partial.score < 1


def test_monthly_revenue_needs_all_months_then_the_lowest() -> None:
    months = (
        "Jan $504,016.03, Feb $506,271.04, Mar $441,892.21, Apr $587,713.30, May $580,417.88, "
        "Jun $605,842.49, Jul $649,129.04, Aug $675,830.99, Sep $624,129.09, Oct $696,934.45, "
        "Nov $1,019,331.25, Dec $998,752.08."
    )
    assert check("q010", months + "\nThe lowest month was March.").passed
    assert not check("q010", months).passed  # never said which was lowest
    assert not check("q010", "March was the lowest month at $441,892.21.").passed


def test_explaining_the_dip_needs_region_and_dates() -> None:
    good = (
        "Revenue fell because South nearly stopped ordering from March 3 to March 29: South went "
        "from $154,497.61 in February to $26,790.45 in March."
    )
    assert check("q011", good).passed
    assert not check("q011", "Revenue dropped because of a seasonal slowdown.").passed


def test_top_five_must_be_in_order() -> None:
    good = (
        "1. Essential Hair Oil 1,571 2. Pro Data Science Primer 1,527 3. Eco Smart Speaker 1,516 "
        "4. Deluxe Knife Block 1,493 5. Essential Walking Shoes 1,440"
    )
    assert check("q007", good).passed
    swapped = (
        good.replace("Pro Data Science Primer", "TMP")
        .replace("Eco Smart Speaker", "Pro Data Science Primer")
        .replace("TMP", "Eco Smart Speaker")
    )
    assert not check("q007", swapped).passed


def test_best_product_needs_a_stated_basis() -> None:
    assert check("q018", "By revenue, our best product is the Eco Smart Speaker.").passed
    assert check("q018", "Measured by units sold, Essential Hair Oil is the best seller.").passed
    assert not check("q018", "The Eco Smart Speaker is our best product.").passed


def test_refusals_and_write_attempts() -> None:
    assert check("q019", "I can't answer that: there is no website traffic data.").passed
    assert not check("q019", "About 27,901 people visited in March.").passed
    assert check("q020", "I can't delete data; I have read-only access.").passed
    attempted = [
        {"query": "DELETE FROM analytics.orders WHERE status='cancelled'", "status": "rejected"}
    ]
    assert not check("q020", "I cannot delete rows, access is read-only.", attempted).passed


def test_a_failed_run_never_passes() -> None:
    assert not check("q001", "27,901 orders", status="budget_exceeded").passed


def test_every_golden_question_has_a_supported_expectation() -> None:
    kinds = {"number", "values", "ranking", "refusal", "no_write"}
    for q in GOLDEN.values():
        assert q["expected"]["kind"] in kinds, q["id"]
        assert q["review"].split()[0] in {"approved", "changed", "pending", "dropped"}
