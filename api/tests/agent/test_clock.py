"""The clock tool: the user's local date and time from a client-supplied timezone."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agent.clock import describe_now, normalize_timezone
from app.artifacts import ArtifactStore
from app.config import get_settings
from app.tools.analyst_tools import ToolContext, build_tools

NOW = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Asia/Kolkata", "Asia/Kolkata"),
        ("America/New_York", "America/New_York"),
        (None, "UTC"),
        ("", "UTC"),
        ("Mars/Olympus_Mons", "UTC"),
        ("../../etc/passwd", "UTC"),
        ("A" * 200, "UTC"),
    ],
)
def test_unknown_or_missing_timezones_fall_back_to_utc(name: str | None, expected: str) -> None:
    assert normalize_timezone(name) == expected


def test_the_date_is_local_to_the_user_not_the_server() -> None:
    # 20:00 UTC is already the next day in Kolkata
    text = describe_now("Asia/Kolkata", NOW)
    assert "Saturday, 14 November 2026, 01:30" in text
    assert "UTC+05:30" in text and "2026-11-14T01:30:00+05:30" in text
    assert "Friday, 13 November 2026, 15:00" in describe_now("America/New_York", NOW)


async def test_the_tool_uses_the_timezone_from_its_context(tmp_path: Path) -> None:
    async def no_sandbox() -> Any:
        raise AssertionError("the clock must not touch the sandbox")

    ctx = ToolContext(
        settings=get_settings(),
        get_sandbox=no_sandbox,
        artifacts=ArtifactStore(tmp_path, "t"),
        timezone="Asia/Kolkata",
    )
    tool = next(t for t in build_tools(ctx) if t.name == "current_datetime")
    text = await tool.ainvoke({})
    assert "Asia/Kolkata" in text and "$(date)" in text  # the warning against shell syntax
