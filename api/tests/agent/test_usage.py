from __future__ import annotations

import pytest

from app.agent import usage
from app.agent.usage import BudgetExceeded, StepLimitExceeded, UsageTracker


def test_sums_tokens_and_models_across_calls() -> None:
    t = UsageTracker(max_tokens=10_000)
    t._record("model-a", 100, 20)
    t._record("model-b", 50, 5)
    t._record("model-a", 10, 1)
    s = t.summary
    assert (s.llm_calls, s.input_tokens, s.output_tokens, s.total_tokens) == (3, 160, 26, 186)
    assert s.models == ["model-a", "model-b"]


def test_cost_is_unknown_without_a_verified_price() -> None:
    t = UsageTracker(max_tokens=10_000)
    t._record("unpriced-model", 1000, 1000)
    assert t.summary.cost_usd is None


def test_cost_is_computed_only_when_every_model_has_a_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(usage, "load_prices", lambda: {"priced": (1.0, 2.0)})
    t = UsageTracker(max_tokens=10**9)
    t._record("priced", 1_000_000, 500_000)
    assert t.summary.cost_usd == pytest.approx(2.0)
    t._record("unpriced", 10, 10)
    assert t.summary.cost_usd is None  # never report a partial/guessed total


def test_token_budget_stops_the_run() -> None:
    t = UsageTracker(max_tokens=100)
    t._record("m", 60, 10)
    with pytest.raises(BudgetExceeded, match="Token budget"):
        t._record("m", 30, 10)


def test_step_limit_counts_model_calls() -> None:
    t = UsageTracker(max_tokens=10**9, max_llm_calls=2)
    t._record("m", 1, 1)
    t._record("m", 1, 1)
    with pytest.raises(StepLimitExceeded):
        t._record("m", 1, 1)


def test_cost_budget_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(usage, "load_prices", lambda: {"m": (10.0, 10.0)})
    t = UsageTracker(max_tokens=10**9, max_cost_usd=1.0)
    with pytest.raises(BudgetExceeded, match="Cost budget"):
        t._record("m", 100_000, 100_000)  # $2.00


def test_tracker_propagates_errors_so_langchain_does_not_swallow_them() -> None:
    assert UsageTracker.raise_error is True


def test_shipped_price_table_has_no_invented_numbers() -> None:
    assert usage.load_prices() == {}


def test_calls_that_report_no_usage_are_counted_not_hidden() -> None:
    t = UsageTracker(max_tokens=100)
    t._record("m", 10, 5)
    t._record("m", 0, 0, reported=False)
    assert t.summary.calls_without_usage == 1 and t.summary.as_dict()["calls_without_usage"] == 1
