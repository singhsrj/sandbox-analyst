"""Shared test setup."""

from __future__ import annotations

import pytest

from app.config import Settings


def _setting_env_names() -> set[str]:
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias
        if alias is not None:
            for choice in getattr(alias, "choices", [alias]):
                names.add(str(choice).upper())
    return names


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on whatever secrets or settings the developer's shell has.

    Tests that build `Settings(_env_file=None)` see a clean slate and set what they need.
    (Integration tests use `get_settings()`, which is read once at import time, before this runs.)
    """
    for name in _setting_env_names():
        monkeypatch.delenv(name, raising=False)
