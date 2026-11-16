from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from app.profiling.profiler import (
    column_kind,
    feature_importance,
    infer_relationships,
    profile_column,
    profile_dataset,
    summary_facts,
)


def _shop() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(0)
    customers = pd.DataFrame(
        {
            "customer_id": range(1, 101),
            "email": [f"user{i}@example.com" for i in range(1, 101)],
            "segment": rng.choice(["Standard", "Budget", "Premium"], 100),
        }
    )
    amounts = rng.gamma(2.0, 50.0, 400)
    amounts[:4] = [5000, 4800, 4700, 4600]  # planted outliers
    orders = pd.DataFrame(
        {
            "order_id": range(1, 401),
            "customer_id": rng.integers(1, 101, 400),
            "order_date": pd.date_range("2025-01-01", periods=400, freq="D"),
            "status": rng.choice(["delivered", "cancelled"], 400, p=[0.9, 0.1]),
            "total_amount": amounts,
            "rating": rng.integers(1, 6, 400),
        }
    )
    return {"customers": customers, "orders": orders}


@pytest.mark.parametrize(
    ("name", "values", "kind"),
    [
        ("order_id", [1, 2, 3], "id"),
        ("amount", [1.5, 2.0, 9.0], "numeric"),
        ("is_returned", [True, False, True], "boolean"),
        ("flag", [0, 1, 1], "boolean"),
        (
            "created_at",
            pd.Series(pd.to_datetime(["2025-01-01", "2025-02-01"])).reindex(range(3)),
            "datetime",
        ),
        ("signup", ["2025-01-01", "2025-03-04", "2024-12-31"], "datetime"),
        ("status", ["a", "b", "a"], "categorical"),
        ("contact", ["x@y.com", "a@b.org", "q@w.io"], "pii"),
        ("full_name", ["Ann Lee", "Bo Chan", "Cy Dee"], "pii"),
        ("comment", ["word " * 20, "other " * 15, "more " * 12], "text"),
    ],
)
def test_column_kinds(name: str, values: list[object], kind: str) -> None:
    assert column_kind(name, pd.Series(values)) == kind


def test_numeric_column_has_stats_histogram_and_iqr_outliers() -> None:
    col = profile_column("total_amount", _shop()["orders"]["total_amount"])
    assert col["kind"] == "numeric" and col["missing"] == 0
    assert col["stats"]["min"] <= col["stats"]["median"] <= col["stats"]["max"]
    assert sum(b["count"] for b in col["histogram"]) == 400
    assert col["outliers"]["count"] >= 4
    assert col["outliers"]["examples"][0] == 5000  # most extreme first


def test_small_integer_columns_get_one_bar_per_value() -> None:
    col = profile_column("rating", _shop()["orders"]["rating"])
    assert [b["start"] for b in col["histogram"]] == [1, 2, 3, 4, 5]


def test_keys_with_few_values_get_top_values_but_unique_ids_do_not() -> None:
    orders = _shop()["orders"]
    region = profile_column("region_id", pd.Series([1, 2, 3, 1, 2] * 20))
    assert region["kind"] == "id" and len(region["top_values"]) == 3
    assert "top_values" not in profile_column("order_id", orders["order_id"])


def test_pii_columns_never_expose_values() -> None:
    col = profile_column("email", _shop()["customers"]["email"])
    assert col["kind"] == "pii" and col["example"] is None
    assert "top_values" not in col and col["distinct"] == 100


def test_categorical_top_values_fold_the_tail_into_other() -> None:
    series = pd.Series([f"v{i % 15}" for i in range(150)])
    top = profile_column("code", series)["top_values"]
    assert len(top) == 11 and top[-1]["other"] is True
    assert sum(t["count"] for t in top) == 150


def test_datetime_timeline_and_missing_values() -> None:
    series = pd.Series(pd.date_range("2024-01-01", periods=500, freq="D")).astype("datetime64[ns]")
    series = series.mask(series.index % 10 == 5)
    col = profile_column("created_at", series)
    assert col["missing"] == 50 and col["missing_pct"] == 10.0
    assert col["timeline"]["unit"] == "month"
    assert col["date_range"]["min"].startswith("2024-01-01")


def test_relationships_are_inferred_from_contained_unique_keys() -> None:
    rels = infer_relationships(_shop())
    assert rels == [
        {
            "from_table": "orders",
            "from_column": "customer_id",
            "to_table": "customers",
            "to_column": "customer_id",
            "kind": "inferred",
            "match_pct": 100.0,
        }
    ]


def test_feature_importance_finds_the_planted_signal() -> None:
    rng = np.random.default_rng(1)
    n = 2000
    category = rng.choice(["toys", "books", "garden"], n)
    returned = (category == "toys") & (rng.random(n) < 0.6)
    frame = pd.DataFrame(
        {
            "is_returned": returned,
            "category": category,
            "noise": rng.normal(size=n),
            "order_id": range(n),
        }
    )
    fi = feature_importance(frame, "is_returned", label="lines")
    assert fi is not None and fi["task"] == "classification"
    assert fi["scores"][0]["feature"] == "category"
    assert "order_id" not in {s["feature"] for s in fi["scores"]}  # ids are not features


def test_dataset_profile_is_json_and_summary_facts_hide_pii() -> None:
    profile = profile_dataset(_shop(), dataset_id="t", name="Test shop", source="upload")
    text = json.dumps(profile)  # must be plain JSON: no NaN, numpy or timestamps
    assert "NaN" not in text and "example.com" not in text
    assert profile["dataset"]["rows"] == 500 and profile["relationships"]
    orders = next(t for t in profile["tables"] if t["name"] == "orders")
    assert orders["correlations"]["columns"] == ["total_amount", "rating"]
    facts = summary_facts(profile)
    assert "orders" in facts and "example.com" not in facts
