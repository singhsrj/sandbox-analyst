from typing import Any

import pytest

from app import observability
from tests.helpers import make_settings


class FakeSpan:
    def __init__(self, log: list[str], name: str) -> None:
        self.log, self.name = log, name
        self.trace_id, self.id = "a" * 32, "b" * 16

    def start_observation(self, *, name: str, as_type: str = "span") -> "FakeSpan":
        self.log.append(f"start {name}")
        return FakeSpan(self.log, name)

    def set_trace_as_public(self) -> None:
        self.log.append(f"public {self.name}")

    def end(self) -> None:
        self.log.append(f"end {self.name}")


class FakeClient(FakeSpan):
    def flush(self) -> None:
        self.log.append("flush")

    def get_trace_url(self, *, trace_id: str) -> str:
        return f"https://langfuse.test/traces/{trace_id}"


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    client = FakeClient(calls, "client")
    monkeypatch.setattr(observability, "init_langfuse", lambda settings: client)
    monkeypatch.setattr(observability, "get_client", lambda **kwargs: client)
    return calls


def keys(**values: Any) -> Any:
    return make_settings(
        langfuse_public_key="pk-lf-test", langfuse_secret_key="sk-lf-test", **values
    )


def test_traces_stay_private_by_default(log: list[str]) -> None:
    handler = observability.make_handler(keys())
    assert handler is not None and not hasattr(handler, "public_root")
    observability.finalize_trace(handler, keys())
    assert not any(entry.startswith("public") for entry in log)


def test_public_traces_publish_with_a_marker_started_last(log: list[str]) -> None:
    settings = keys(langfuse_public_traces=True)
    handler = observability.make_handler(settings)
    assert handler is not None
    handler.last_trace_id = "a" * 32
    _, url = observability.finalize_trace(handler, settings)
    assert log == [
        "start sandbox-analyst",
        "start publish-trace",
        "public publish-trace",
        "end publish-trace",
        "end sandbox-analyst",
        "flush",
    ]
    assert url == f"https://langfuse.test/traces/{'a' * 32}"
