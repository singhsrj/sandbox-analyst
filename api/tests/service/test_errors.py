from __future__ import annotations

import pytest

from app.service.errors import describe_run_error


def make(name: str, module: str = "openai", message: str = "secret detail sk-12345") -> Exception:
    cls = type(name, (Exception,), {"__module__": module})
    exc: Exception = cls(message)
    return exc


@pytest.mark.parametrize(
    ("name", "module", "expected"),
    [
        ("OpenAIAuthenticationError", "langchain_openai", "credentials"),
        ("AuthenticationError", "openai", "credentials"),
        ("PermissionDeniedError", "openai", "credentials"),
        ("RateLimitError", "openai", "rate limiting"),
        ("APITimeoutError", "openai", "too long"),
        ("APIConnectionError", "openai", "Could not reach"),
        ("SandboxException", "e2b", "sandbox"),
        ("TimeoutException", "e2b", "sandbox"),
        ("OperationalError", "psycopg", "database"),
        ("PoolTimeout", "psycopg_pool", "database"),
    ],
)
def test_known_failures_get_an_actionable_message(name: str, module: str, expected: str) -> None:
    assert expected in describe_run_error(make(name, module))


def test_unknown_failures_name_only_the_class() -> None:
    assert describe_run_error(make("WeirdThing", "somepkg")) == "The run failed (WeirdThing)."


def test_exception_text_never_reaches_the_user() -> None:
    for name, module in [
        ("AuthenticationError", "openai"),
        ("WeirdThing", "x"),
        ("OperationalError", "psycopg"),
    ]:
        assert "sk-12345" not in describe_run_error(make(name, module))
