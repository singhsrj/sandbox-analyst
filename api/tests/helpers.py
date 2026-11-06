"""Small helpers shared by tests."""

from __future__ import annotations

from typing import Any

from app.config import Settings


def make_settings(**values: Any) -> Settings:
    """Settings built only from the given values (never from a developer's .env)."""
    return Settings(_env_file=None, **values)
