"""Statistical profile of a dataset (one or more tables), as plain JSON-ready data.

Self-contained on purpose: this file imports only pandas, numpy and scikit-learn and nothing from
`app`, so the same file can be copied into an E2B sandbox to profile an uploaded file there
(uploads are untrusted and are never parsed by the API process). Works with pandas 2 and 3.

Every number here is computed from the data; nothing is written by a model. The AI summary is
added separately and only ever sees this profile, never the rows.

Privacy: columns that hold personal data (names, emails, phone numbers, addresses, or values that
look like emails) get kind "pii": counts only, no example values, no top values.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

PROFILE_VERSION = 1
HISTOGRAM_BINS = 20
TOP_VALUES = 10
MAX_TIMELINE_POINTS = 120
MAX_CORRELATION_COLUMNS = 12
MAX_IMPORTANCE_ROWS = 50_000
OUTLIER_EXAMPLES = 5
MAX_EXAMPLE_CHARS = 60
# A text column is "free text" (no top values) when values are long or nearly all distinct.
FREE_TEXT_MEAN_CHARS = 40
FREE_TEXT_DISTINCT_RATIO = 0.5
CATEGORICAL_MAX_DISTINCT = 50
ID_TOP_VALUES_MAX = 20  # identifier columns with this few values also get top values

_PII_NAME = re.compile(
    r"(^|_)(e?mail|email_address|phone|mobile|full_?name|first_?name|last_?name|surname|"
    r"address|street|postcode|zip_?code|ssn|passport|dob|date_of_birth|ip_address)($|_)",
    re.IGNORECASE,
)
_EMAIL_VALUE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ID_NAME = re.compile(r"(^id$|_id$|^id_|uuid$)", re.IGNORECASE)


# --------------------------------------------------------------------------- helpers


def _num(value: Any, digits: int = 4) -> float | int | None:
    """A JSON-safe number: NaN/inf become None, floats are rounded to `digits` significant."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if f == 0:
        return 0.0
    return round(f, max(0, digits - 1 - math.floor(math.log10(abs(f)))))


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    text = str(value)
    return text if len(text) <= MAX_EXAMPLE_CHARS else text[: MAX_EXAMPLE_CHARS - 1] + "…"


def _is_datetime(series: pd.Series) -> bool:
    return bool(pd.api.types.is_datetime64_any_dtype(series))


def _looks_like_dates(series: pd.Series) -> pd.Series | None:
    """Parse an object column of dates/strings into datetimes when nearly all values parse."""
    sample = series.dropna()
    if sample.empty:
        return None
    first = sample.iloc[0]
    if not isinstance(first, (str, datetime, pd.Timestamp)) and type(first).__name__ != "date":
        return None
    if isinstance(first, str) and not re.match(r"^\d{4}-\d{1,2}-\d{1,2}", first):
        return None
    parsed = pd.to_datetime(series, errors="coerce")
    return parsed if parsed.notna().sum() >= 0.95 * len(sample) else None


def _pii(name: str, series: pd.Series) -> bool:
    if _PII_NAME.search(name):
        return True
    sample = series.dropna().astype(str).head(200)
    return len(sample) > 0 and sample.map(lambda v: bool(_EMAIL_VALUE.match(v))).mean() > 0.5


def column_kind(name: str, series: pd.Series) -> str:
    """One of: id, pii, boolean, datetime, numeric, categorical, text."""
    non_null = series.dropna()
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if _is_datetime(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        if _ID_NAME.search(name):
            return "id"
        unique = non_null.unique()
        if len(unique) <= 2 and set(np.asarray(unique).tolist()) <= {0, 1}:
            return "boolean"
        return "numeric"
    if _pii(name, series):
        return "pii"
    if _ID_NAME.search(name) and non_null.nunique() >= 0.9 * max(len(non_null), 1):
        return "id"
    if _looks_like_dates(series) is not None:
        return "datetime"
    as_text = non_null.astype(str)
    distinct = as_text.nunique()
    if len(as_text) and (
        as_text.str.len().mean() > FREE_TEXT_MEAN_CHARS
        or (
            distinct > CATEGORICAL_MAX_DISTINCT
            and distinct / len(as_text) > FREE_TEXT_DISTINCT_RATIO
        )
    ):
        return "text"
    return "categorical"


def _as_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("float64")


def _as_datetime(series: pd.Series) -> pd.Series:
    if _is_datetime(series):
        return series
    parsed = _looks_like_dates(series)
    return parsed if parsed is not None else pd.to_datetime(series, errors="coerce")


# --------------------------------------------------------------------------- per column


def _numeric_details(values: pd.Series) -> dict[str, Any]:
    v = values.dropna()
    if v.empty:
        return {}
    q1, median, q3 = (float(x) for x in v.quantile([0.25, 0.5, 0.75]))
    out: dict[str, Any] = {
        "stats": {
            "min": _num(v.min()),
            "p25": _num(q1),
            "median": _num(median),
            "mean": _num(v.mean()),
            "p75": _num(q3),
            "max": _num(v.max()),
            "std": _num(v.std()) if len(v) > 1 else None,
            "skew": _num(v.skew()) if len(v) > 2 else None,
        }
    }
    lo, hi = float(v.min()), float(v.max())
    distinct = v.unique()
    if lo == hi:
        out["histogram"] = [{"start": _num(lo), "end": _num(hi), "count": len(v)}]
    elif len(distinct) <= HISTOGRAM_BINS and bool(np.all(np.mod(distinct, 1) == 0)):
        # Few whole-number values (ratings, quantities): one bar per value reads better than bins.
        counts_by_value = v.value_counts().sort_index()
        out["histogram"] = [
            {"start": _num(value), "end": _num(value), "count": int(count)}
            for value, count in counts_by_value.items()
        ]
    else:
        counts, edges = np.histogram(v.to_numpy(), bins=HISTOGRAM_BINS)
        out["histogram"] = [
            {"start": _num(edges[i]), "end": _num(edges[i + 1]), "count": int(c)}
            for i, c in enumerate(counts)
        ]
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mask = (v < lower) | (v > upper)
    flagged = v[mask]
    extremes = flagged.reindex(flagged.sub(median).abs().sort_values(ascending=False).index)
    out["outliers"] = {
        "method": "iqr",
        "lower": _num(lower),
        "upper": _num(upper),
        "count": int(mask.sum()),
        "pct": _num(100 * mask.mean(), 3),
        "examples": [_num(x) for x in extremes.head(OUTLIER_EXAMPLES)],
    }
    return out


def _top_values(series: pd.Series) -> list[dict[str, Any]]:
    v = series.dropna()
    if v.empty:
        return []
    counts = v.astype(str).value_counts()
    total = len(v)
    top = [
        {"value": _text(value), "count": int(count), "pct": _num(100 * count / total, 3)}
        for value, count in counts.head(TOP_VALUES).items()
    ]
    rest = int(counts.iloc[TOP_VALUES:].sum())
    if rest:
        top.append(
            {"value": None, "other": True, "count": rest, "pct": _num(100 * rest / total, 3)}
        )
    return top


def _datetime_details(values: pd.Series) -> dict[str, Any]:
    v = values.dropna()
    if v.empty:
        return {}
    if getattr(v.dt, "tz", None) is not None:
        v = v.dt.tz_convert(None)
    span_days = (v.max() - v.min()).days
    freq, fmt = ("D", "%Y-%m-%d") if span_days <= 92 else ("M", "%Y-%m")
    if span_days > 365 * 10:
        freq, fmt = ("Y", "%Y")
    periods = v.dt.to_period(freq).value_counts().sort_index()
    if len(periods) > MAX_TIMELINE_POINTS:
        periods = periods.iloc[-MAX_TIMELINE_POINTS:]
    return {
        "date_range": {"min": v.min().isoformat(), "max": v.max().isoformat()},
        "timeline": {
            "unit": {"D": "day", "M": "month", "Y": "year"}[freq],
            "points": [{"period": p.strftime(fmt), "count": int(c)} for p, c in periods.items()],
        },
    }


def profile_column(
    name: str,
    series: pd.Series,
    *,
    db_type: str | None = None,
    note: str = "",
    kind: str | None = None,
) -> dict[str, Any]:
    kind = kind or column_kind(name, series)
    rows = len(series)
    missing = int(series.isna().sum())
    non_null = series.dropna()
    col: dict[str, Any] = {
        "name": name,
        "type": db_type or str(series.dtype),
        "kind": kind,
        "note": note,
        "missing": missing,
        "missing_pct": _num(100 * missing / rows, 3) if rows else 0.0,
        "distinct": int(non_null.astype(str).nunique())
        if kind != "numeric"
        else int(non_null.nunique()),
        "example": None if kind == "pii" or non_null.empty else _text(non_null.iloc[0]),
    }
    if kind == "numeric":
        col.update(_numeric_details(_as_float(series)))
    elif kind == "datetime":
        col.update(_datetime_details(_as_datetime(series)))
    elif kind in ("categorical", "boolean") or (
        kind == "id" and col["distinct"] <= ID_TOP_VALUES_MAX
    ):
        # A key with few values (region_id) is effectively a category: its spread is useful.
        col["top_values"] = _top_values(series)
    elif kind == "text":
        lengths = non_null.astype(str).str.len()
        if not lengths.empty:
            col["length"] = {
                "min": int(lengths.min()),
                "mean": _num(lengths.mean(), 3),
                "max": int(lengths.max()),
            }
    return col


# --------------------------------------------------------------------------- per table


def _correlations(frame: pd.DataFrame, columns: list[dict[str, Any]]) -> dict[str, Any] | None:
    numeric = [c["name"] for c in columns if c["kind"] == "numeric"]
    # Keep the columns with the most variation when there are too many to show.
    if len(numeric) > MAX_CORRELATION_COLUMNS:
        spread = {n: float(_as_float(frame[n]).std() or 0) for n in numeric}
        numeric = sorted(numeric, key=lambda n: -spread[n])[:MAX_CORRELATION_COLUMNS]
    if len(numeric) < 2:
        return None
    matrix = frame[numeric].apply(_as_float).corr(method="spearman")
    return {
        "method": "spearman",
        "columns": numeric,
        "matrix": [[_num(matrix.loc[a, b], 3) for b in numeric] for a in numeric],
    }


def profile_table(
    name: str,
    frame: pd.DataFrame,
    *,
    description: str = "",
    db_types: Mapping[str, str] | None = None,
    notes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    db_types = db_types or {}
    notes = notes or {}
    columns = [
        profile_column(col, frame[col], db_type=db_types.get(col), note=notes.get(col, ""))
        for col in frame.columns
    ]
    return {
        "name": name,
        "description": description,
        "rows": len(frame),
        "columns": columns,
        "correlations": _correlations(frame, columns),
    }


# --------------------------------------------------------------------------- relationships


def infer_relationships(tables: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Guess joins between tables: same column name, unique on one side, values contained.

    Used when there are no declared foreign keys (uploaded files). Marked "inferred" with the
    share of child values found in the parent, so the UI can say it is a guess.
    """
    found: list[dict[str, Any]] = []
    names = list(tables)
    for parent in names:
        for col in tables[parent].columns:
            key = tables[parent][col].dropna()
            if key.empty or not key.is_unique or pd.api.types.is_float_dtype(key):
                continue
            keys = set(key.astype(str))
            for child in names:
                if child == parent or col not in tables[child].columns:
                    continue
                values = tables[child][col].dropna().astype(str)
                if values.empty or (values.is_unique and len(values) == len(keys)):
                    continue  # a 1:1 copy of the same key says nothing about direction
                share = values.isin(keys).mean()
                if share >= 0.95:
                    found.append(
                        {
                            "from_table": child,
                            "from_column": col,
                            "to_table": parent,
                            "to_column": col,
                            "kind": "inferred",
                            "match_pct": _num(100 * share, 3),
                        }
                    )
    return found


# --------------------------------------------------------------------------- feature importance


def feature_importance(
    frame: pd.DataFrame,
    target: str,
    *,
    label: str,
    description: str = "",
    seed: int = 0,
) -> dict[str, Any] | None:
    """Mutual information between each column and `target` (classification or regression).

    Mutual information catches non-linear links and works for categorical features; it says how
    much knowing a feature tells you about the target, not that it causes it.
    """
    from sklearn.feature_selection import (  # type: ignore[import-untyped]
        mutual_info_classif,
        mutual_info_regression,
    )

    if target not in frame.columns:
        return None
    data = frame.dropna(subset=[target])
    if len(data) > MAX_IMPORTANCE_ROWS:
        data = data.sample(MAX_IMPORTANCE_ROWS, random_state=seed)
    if len(data) < 30:
        return None
    y_raw = data[target]
    target_kind = column_kind(target, y_raw)
    classify = target_kind in ("boolean", "categorical")

    features: dict[str, np.ndarray] = {}
    discrete: list[bool] = []
    for col in data.columns:
        if col == target:
            continue
        series = data[col]
        kind = column_kind(col, series)
        if kind in ("id", "pii", "text"):
            continue
        if kind == "numeric":
            values = _as_float(series)
            features[col] = values.fillna(values.median()).to_numpy()
            discrete.append(False)
        elif kind == "datetime":
            stamps = _as_datetime(series)
            month = stamps.dt.month.astype("float64")
            features[f"{col} (month)"] = month.fillna(0).to_numpy()
            discrete.append(True)
        else:
            codes, _ = pd.factorize(series.astype(str), use_na_sentinel=True)
            features[col] = codes.astype("float64")
            discrete.append(True)
    if not features:
        return None

    x = np.column_stack(list(features.values()))
    if classify:
        y = pd.factorize(y_raw.astype(str))[0]
        scores = mutual_info_classif(x, y, discrete_features=discrete, random_state=seed)
    else:
        y = _as_float(y_raw).to_numpy()
        scores = mutual_info_regression(x, y, discrete_features=discrete, random_state=seed)
    ranked = sorted(zip(features, scores, strict=True), key=lambda p: -p[1])
    return {
        "table": label,
        "target": target,
        "task": "classification" if classify else "regression",
        "method": "mutual_information",
        "description": description,
        "rows_used": len(data),
        "scores": [{"feature": f, "score": _num(s, 3)} for f, s in ranked],
    }


# --------------------------------------------------------------------------- dataset


def profile_dataset(
    tables: Mapping[str, pd.DataFrame],
    *,
    dataset_id: str,
    name: str,
    source: str,
    descriptions: Mapping[str, str] | None = None,
    db_types: Mapping[str, Mapping[str, str]] | None = None,
    notes: Mapping[str, Mapping[str, str]] | None = None,
    relationships: Sequence[Mapping[str, Any]] | None = None,
    importance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Profile every table. `relationships=None` means "infer them" (no declared keys)."""
    descriptions = descriptions or {}
    db_types = db_types or {}
    notes = notes or {}
    profiled = [
        profile_table(
            table,
            frame,
            description=descriptions.get(table, ""),
            db_types=db_types.get(table),
            notes=notes.get(table),
        )
        for table, frame in tables.items()
    ]
    rels = (
        [dict(r, kind=r.get("kind", "foreign_key")) for r in relationships]
        if relationships is not None
        else infer_relationships(tables)
    )
    return {
        "version": PROFILE_VERSION,
        "dataset": {
            "id": dataset_id,
            "name": name,
            "source": source,
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "tables": len(profiled),
            "rows": sum(t["rows"] for t in profiled),
            "columns": sum(len(t["columns"]) for t in profiled),
        },
        "summary": None,
        "tables": profiled,
        "relationships": rels,
        "feature_importance": dict(importance) if importance else None,
    }


def summary_facts(profile: Mapping[str, Any]) -> str:
    """A compact, row-free text view of a profile: what the AI summary is written from."""
    lines = [f"Dataset: {profile['dataset']['name']} ({profile['dataset']['rows']} rows)"]
    for table in profile["tables"]:
        lines.append(f"\nTable {table['name']} ({table['rows']} rows). {table['description']}")
        for col in table["columns"]:
            bits: list[str] = [col["kind"], f"{col['missing_pct']}% missing"]
            stats = col.get("stats")
            if stats:
                bits.append(f"median {stats['median']}, range {stats['min']}..{stats['max']}")
            if col.get("outliers", {}).get("count"):
                bits.append(f"{col['outliers']['pct']}% outliers")
            if col.get("date_range"):
                bits.append(f"{col['date_range']['min'][:10]}..{col['date_range']['max'][:10]}")
            top: Iterable[dict[str, Any]] = col.get("top_values") or []
            shown = [f"{t['value']} {t['pct']}%" for t in top if not t.get("other")][:4]
            if shown:
                bits.append("top: " + ", ".join(shown))
            lines.append(f"- {col['name']}: " + "; ".join(bits))
    for rel in profile["relationships"]:
        child = f"{rel['from_table']}.{rel['from_column']}"
        lines.append(f"Join: {child} -> {rel['to_table']}.{rel['to_column']}")
    fi = profile.get("feature_importance")
    if fi:
        ranked = ", ".join(f"{s['feature']} {s['score']}" for s in fi["scores"][:6])
        lines.append(f"\nMutual information with {fi['target']} ({fi['table']}): {ranked}")
    return "\n".join(lines)
