"""The current date and time, in the asking user's timezone.

Why this exists: the model has no clock. Asked to date a report, gpt-oss-120b wrote the shell
expression "$(date)" into Markdown, which nothing ever ran, so the user saw it literally.

The timezone is a per-request hint from the client (the browser sends its IANA name, e.g.
"Asia/Kolkata"). It is deliberately not tied to the session or user identity, so this keeps
working unchanged if authentication (Clerk or any other provider) is added later; a stored
profile timezone could then simply be passed in the same way. Anything missing or invalid falls
back to UTC instead of failing the run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "UTC"
_MAX_NAME = 64


def normalize_timezone(name: str | None) -> str:
    """A valid IANA timezone name, or UTC when `name` is missing or unknown."""
    if not name or len(name) > _MAX_NAME:
        return DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_TIMEZONE
    return name


def describe_now(timezone: str, now: datetime | None = None) -> str:
    """The tool's answer: local date and time with weekday and UTC offset."""
    tz = ZoneInfo(normalize_timezone(timezone))
    local = (now or datetime.now(UTC)).astimezone(tz)
    offset = local.strftime("%z")
    return (
        f"Current date and time for the user: {local:%A, %d %B %Y, %H:%M} "
        f"({tz.key}, UTC{offset[:3]}:{offset[3:]}).\n"
        f"ISO 8601: {local.isoformat(timespec='seconds')}\n"
        "Write this date into reports as plain text; never use shell expressions like $(date)."
    )
