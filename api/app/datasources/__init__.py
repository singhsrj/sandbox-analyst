"""Data sources the agent can query (see base.py)."""

from __future__ import annotations

from functools import partial

from app.datasources.base import Catalog, Column, DataSource, Table
from app.datasources.sample import SampleSource
from app.security.sql_risk import RiskAssessment, assess_query

__all__ = ["Catalog", "Column", "DataSource", "SampleSource", "Table", "risk_check"]


def risk_check(source: DataSource) -> partial[RiskAssessment]:
    """The approval gate's risk check for this source: pure in the SQL text, as the gate needs."""
    return partial(
        assess_query,
        large_tables=source.large_tables,
        schema=source.scope.schema,
        dialect=source.scope.dialect,
    )
