"""ChatService end to end with a fake agent that replays the REAL recorded stream."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.agent.usage import BudgetExceeded, StepLimitExceeded
from app.config import Settings
from app.service import chat as chat_module
from app.service.chat import ChatService, ServerBusy, ThreadBusy
from app.streaming.sse import sse_stream
from tests.fakes import FakeAgent, FakeSandboxes, FakeStore, recorded_events
from tests.helpers import make_settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(ARTIFACTS_DIR=str(tmp_path), MAX_CONCURRENT_RUNS="2")


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the parts that need network: model, agent construction, output collection."""
    state: dict[str, Any] = {
        "agent": FakeAgent(recorded_events(), "In 2025 there were 1,086 cancelled orders.")
    }

    async def fake_build_agent(*args: Any, **kwargs: Any) -> Any:
        return state["agent"]

    async def fake_collect(*args: Any, **kwargs: Any) -> list[str]:
        return []

    monkeypatch.setattr(chat_module, "build_agent", fake_build_agent)
    monkeypatch.setattr(chat_module, "get_model", lambda *a, **k: object())
    monkeypatch.setattr(chat_module, "collect_outputs", fake_collect)
    monkeypatch.setattr(chat_module, "make_handler", lambda settings: None)
    return state


def make_service(settings: Settings, store: FakeStore) -> ChatService:
    return ChatService(settings, store, FakeSandboxes(), checkpointer=None)  # type: ignore[arg-type]


async def collect(
    service: ChatService, thread_id: str = "thread-12345", owner: str = "owner-12345"
) -> list[dict[str, Any]]:
    turn = await service.prepare(
        thread_id=thread_id, owner_id=owner, question="How many were cancelled?"
    )
    return [chunk async for chunk in service.stream(turn)]


async def test_successful_turn_streams_a_complete_message_and_persists_the_run(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    service = make_service(settings, store)
    chunks = await collect(service)

    assert chunks[0]["type"] == "start" and chunks[-1] == {"type": "finish"}
    kinds = Counter(c["type"] for c in chunks)
    assert kinds["tool-input-available"] == kinds["tool-output-available"] >= 3
    run_part = next(c for c in chunks if c["type"] == "data-run")
    assert run_part["data"]["status"] == "ok" and run_part["data"]["model"] == settings.model

    (saved,) = store.runs
    assert saved["status"] == "ok" and saved["question"] == "How many were cancelled?"
    assert "1,086" in saved["final_answer"]
    assert any(c["type"] == "data-todos" for c in saved["chunks"])
    assert service.active_runs == 0


async def test_stored_chunks_are_coalesced_but_replay_to_the_same_text(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    chunks = await collect(make_service(settings, store))
    stored = store.runs[0]["chunks"]
    live_text = "".join(c["delta"] for c in chunks if c["type"] == "text-delta")
    stored_text = "".join(c["delta"] for c in stored if c["type"] == "text-delta")
    assert live_text == stored_text != ""
    assert len(stored) <= len(chunks)


async def test_a_failing_agent_ends_the_stream_cleanly_with_an_error_and_a_saved_run(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    patched["agent"] = FakeAgent(
        recorded_events(), raise_after=5, error=RuntimeError("db password is hunter2")
    )
    chunks = await collect(make_service(settings, store))
    error = next(c for c in chunks if c["type"] == "error")
    assert "hunter2" not in error["errorText"] and "RuntimeError" in error["errorText"]  # no leak
    assert chunks[-1] == {"type": "finish"}
    assert store.runs[0]["status"] == "error"


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (BudgetExceeded("Token budget exceeded: 5 > 3 tokens."), "budget_exceeded"),
        (StepLimitExceeded("Step limit exceeded."), "step_limit"),
    ],
)
async def test_budget_and_step_limits_stop_the_run_with_a_readable_reason(
    settings: Settings, store: FakeStore, patched: dict[str, Any], exc: Exception, status: str
) -> None:
    patched["agent"] = FakeAgent(recorded_events(), raise_after=3, error=exc)
    chunks = await collect(make_service(settings, store))
    assert next(c for c in chunks if c["type"] == "error")["errorText"] == str(exc)
    assert store.runs[0]["status"] == status


async def test_an_empty_reply_is_nudged_once_and_recorded(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    patched["agent"] = FakeAgent(recorded_events(), "Recovered answer.", empty_first=True)
    chunks = await collect(make_service(settings, store))
    assert patched["agent"].calls == 2 and "empty" in patched["agent"].inputs[1].lower()
    assert next(c for c in chunks if c["type"] == "data-run")["data"]["empty_reply_nudges"] == 1
    assert store.runs[0]["final_answer"] == "Recovered answer."


async def test_client_disconnect_persists_the_run_and_frees_the_slot(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    service = make_service(settings, store)
    turn = await service.prepare(thread_id="thread-12345", owner_id="owner-12345", question="q?")
    stream = service.stream(turn)
    for _ in range(4):
        await stream.__anext__()
    await stream.aclose()  # what Starlette does when the browser goes away

    assert store.runs[0]["status"] == "aborted"
    assert service.active_runs == 0
    # the thread is usable again immediately
    again = await service.prepare(
        thread_id="thread-12345", owner_id="owner-12345", question="again?"
    )
    assert again.thread.thread_id == "thread-12345"


async def test_cancellation_while_waiting_on_the_agent_is_also_persisted(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    class Hanging(FakeAgent):
        async def astream(self, payload: Any, config: Any, stream_mode: Any) -> AsyncIterator[Any]:
            yield ("updates", {})
            await asyncio.sleep(3600)

    patched["agent"] = Hanging([])
    service = make_service(settings, store)
    turn = await service.prepare(thread_id="thread-12345", owner_id="owner-12345", question="q?")

    async def consume() -> None:
        async for _ in sse_stream(service.stream(turn), heartbeat_seconds=0.05):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.runs and store.runs[0]["status"] == "aborted"
    assert service.active_runs == 0


async def test_a_second_turn_on_a_busy_thread_is_refused_before_streaming(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    service = make_service(settings, store)
    first = await service.prepare(thread_id="thread-12345", owner_id="owner-12345", question="q?")
    stream = service.stream(first)
    await stream.__anext__()  # run is now in progress and holds the lock
    with pytest.raises(ThreadBusy):
        await service.prepare(thread_id="thread-12345", owner_id="owner-12345", question="q2?")
    await stream.aclose()


async def test_global_concurrency_cap(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    service = make_service(settings, store)  # MAX_CONCURRENT_RUNS=2
    streams = []
    for i in range(2):
        turn = await service.prepare(
            thread_id=f"thread-1234{i}", owner_id="owner-12345", question="q?"
        )
        s = service.stream(turn)
        await s.__anext__()
        streams.append(s)
    with pytest.raises(ServerBusy):
        await service.prepare(thread_id="thread-99999", owner_id="owner-12345", question="q?")
    for s in streams:
        await s.aclose()
    assert service.active_runs == 0


async def test_someone_elses_thread_looks_like_it_does_not_exist(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    from app.db.app_store import ThreadNotFound

    service = make_service(settings, store)
    await collect(service, "thread-12345", "owner-aaaaaaa")
    with pytest.raises(ThreadNotFound):
        await service.prepare(
            thread_id="thread-12345", owner_id="owner-bbbbbbb", question="mine now?"
        )


async def test_sandbox_id_is_remembered_for_reconnects(
    settings: Settings, store: FakeStore, patched: dict[str, Any]
) -> None:
    await collect(make_service(settings, store))
    assert store.sandbox_ids["thread-12345"] == "sbx-fake"
