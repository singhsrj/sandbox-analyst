"""The streaming adapter: unit cases plus a replay of a REAL recorded agent stream."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    ToolMessage,
    messages_from_dict,
)

from app.streaming.adapter import (
    SSE_DONE,
    UIStreamAdapter,
    coalesce,
    to_sse,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "stream_simple.jsonl"


def load_recorded_events() -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["mode"] == "messages":
            message = messages_from_dict([record["message"]])[0]
            events.append(("messages", (message, {"langgraph_node": record["node"]})))
        else:
            payload: dict[str, Any] = {}
            for node, update in record["payload"].items():
                payload[node] = (
                    None if update is None else {"messages": messages_from_dict(update["messages"])}
                )
            events.append(("updates", payload))
    return events


def run_adapter(events: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    adapter = UIStreamAdapter("msg-1")
    chunks = adapter.start()
    for mode, payload in events:
        chunks.extend(adapter.feed(mode, payload))
    chunks.extend(adapter.finish())
    return chunks


def assert_well_formed(chunks: list[dict[str, Any]]) -> None:
    """Structural rules of the protocol that the AI SDK client relies on."""
    assert chunks[0] == {"type": "start", "messageId": "msg-1"}
    assert chunks[-1] == {"type": "finish"} and chunks[-2] == {"type": "finish-step"}
    open_text: set[str] = set()
    input_started: set[str] = set()
    input_ready: set[str] = set()
    for c in chunks:
        t = c["type"]
        if t == "text-start":
            assert c["id"] not in open_text
            open_text.add(c["id"])
        elif t == "text-delta":
            assert c["id"] in open_text, "delta outside an open text part"
        elif t == "text-end":
            assert c["id"] in open_text
            open_text.discard(c["id"])
        elif t == "tool-input-start":
            assert c["toolCallId"] not in input_started, "duplicate tool call"
            input_started.add(c["toolCallId"])
        elif t == "tool-input-available":
            assert c["toolCallId"] in input_started
            input_ready.add(c["toolCallId"])
        elif t in ("tool-output-available", "tool-output-error"):
            assert c["toolCallId"] in input_ready, "output before its input"
    assert not open_text, "text part left open"


def test_replay_of_a_real_stream_is_well_formed() -> None:
    chunks = run_adapter(load_recorded_events())
    assert_well_formed(chunks)
    kinds = Counter(c["type"] for c in chunks)
    assert kinds["tool-input-available"] >= 3
    assert kinds["tool-input-available"] == kinds["tool-output-available"]
    assert kinds["text-delta"] >= 1
    assert kinds["data-todos"] >= 1


def test_the_final_answer_is_the_text_after_the_last_tool_call() -> None:
    adapter = UIStreamAdapter("msg-1")
    adapter.start()
    for mode, payload in load_recorded_events():
        adapter.feed(mode, payload)
    assert "cancelled" in adapter.final_text.lower()
    assert "1,086" in adapter.final_text


def test_tool_calls_carry_their_complete_input() -> None:
    chunks = run_adapter(load_recorded_events())
    sql_calls = [
        c for c in chunks if c["type"] == "tool-input-available" and c["toolName"] == "run_sql"
    ]
    assert sql_calls and "query" in sql_calls[0]["input"]
    todos = [c for c in chunks if c["type"] == "data-todos"]
    assert todos[0]["id"] == "todos" and isinstance(todos[0]["data"]["todos"], list)


def test_every_chunk_is_valid_json_in_an_sse_frame() -> None:
    for chunk in run_adapter(load_recorded_events()):
        frame = to_sse(chunk)
        assert frame.startswith("data: ") and frame.endswith("\n\n") and "\n" not in frame[:-2]
        assert json.loads(frame[6:]) == chunk
    assert SSE_DONE == "data: [DONE]\n\n"


def test_coalescing_keeps_the_same_message_but_fewer_chunks() -> None:
    chunks = [
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "Hel"},
        {"type": "text-delta", "id": "t1", "delta": "lo"},
        {"type": "text-end", "id": "t1"},
        {"type": "text-start", "id": "t2"},
        {"type": "text-delta", "id": "t2", "delta": "!"},
    ]
    merged = coalesce(chunks)
    assert len(merged) == 5
    assert merged[1] == {"type": "text-delta", "id": "t1", "delta": "Hello"}
    assert merged[4] == {"type": "text-delta", "id": "t2", "delta": "!"}


# ---------------------------------------------------------------- synthetic edge cases
def _chunk(text: str, msg_id: str = "m1", node: str = "model") -> tuple[str, Any]:
    return "messages", (AIMessageChunk(content=text, id=msg_id), {"langgraph_node": node})


def test_streamed_text_is_one_part_with_ordered_deltas() -> None:
    chunks = run_adapter([_chunk("Hel"), _chunk("lo "), _chunk("world")])
    assert_well_formed(chunks)
    deltas = [c["delta"] for c in chunks if c["type"] == "text-delta"]
    assert "".join(deltas) == "Hello world"
    assert Counter(c["type"] for c in chunks)["text-start"] == 1


def test_empty_keep_alive_chunks_and_foreign_nodes_are_ignored() -> None:
    chunks = run_adapter([_chunk(""), _chunk("secret", node="tools"), _chunk("shown")])
    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == ["shown"]


def test_answer_that_only_arrives_in_updates_is_not_lost() -> None:
    final = AIMessage(content="The answer is 42.", id="m9")
    chunks = run_adapter([("updates", {"model": {"messages": [final]}})])
    assert_well_formed(chunks)
    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == ["The answer is 42."]


def test_streamed_answer_is_not_duplicated_by_the_update() -> None:
    final = AIMessage(content="Hello world", id="m1")
    chunks = run_adapter(
        [_chunk("Hello "), _chunk("world"), ("updates", {"model": {"messages": [final]}})]
    )
    assert "".join(c["delta"] for c in chunks if c["type"] == "text-delta") == "Hello world"


def test_text_before_a_tool_call_closes_and_resets_the_final_answer() -> None:
    call = AIMessage(
        content="", tool_calls=[{"name": "list_tables", "args": {}, "id": "c1"}], id="m2"
    )
    result = ToolMessage("tables...", tool_call_id="c1", name="list_tables")
    adapter = UIStreamAdapter("msg-1")
    adapter.start()
    adapter.feed(*_chunk("Let me look."))
    out = adapter.feed("updates", {"model": {"messages": [call]}})
    assert out[0] == {"type": "text-end", "id": "text-1"}
    assert adapter.final_text == ""
    adapter.feed("updates", {"tools": {"messages": [result]}})
    adapter.feed(*_chunk("Done.", "m3"))
    assert adapter.final_text == "Done."


def test_duplicate_updates_do_not_duplicate_tool_parts() -> None:
    call = AIMessage(
        content="", tool_calls=[{"name": "run_sql", "args": {"query": "x"}, "id": "c1"}]
    )
    result = ToolMessage("OK", tool_call_id="c1", name="run_sql")
    chunks = run_adapter(
        [("updates", {"model": {"messages": [call]}})] * 2
        + [("updates", {"tools": {"messages": [result]}})] * 2
    )
    kinds = Counter(c["type"] for c in chunks)
    assert kinds["tool-input-available"] == 1 and kinds["tool-output-available"] == 1


def test_tool_errors_become_error_outputs_and_long_outputs_are_clipped() -> None:
    call = AIMessage(
        content="", tool_calls=[{"name": "execute", "args": {"command": "x"}, "id": "c1"}]
    )
    failed = ToolMessage("boom", tool_call_id="c1", name="execute", status="error")
    huge = ToolMessage("x" * 50_000, tool_call_id="c2", name="read_file")
    call2 = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "c2"}])
    chunks = run_adapter(
        [
            ("updates", {"model": {"messages": [call, call2]}}),
            ("updates", {"tools": {"messages": [failed, huge]}}),
        ]
    )
    error = next(c for c in chunks if c["type"] == "tool-output-error")
    assert error["errorText"] == "boom"
    long_output = next(c for c in chunks if c["type"] == "tool-output-available")
    assert len(long_output["output"]) < 7_000 and "truncated" in long_output["output"]


def test_finish_closes_open_text_adds_error_and_data_parts_once() -> None:
    adapter = UIStreamAdapter("msg-1")
    adapter.start()
    adapter.feed(*_chunk("partial"))
    data = [{"type": "data-run", "id": "run", "data": {"status": "error"}}]
    out = adapter.finish(error="boom", data_parts=data)
    assert [c["type"] for c in out] == ["text-end", "error", "data-run", "finish-step", "finish"]
    assert adapter.finish() == []  # idempotent
    assert adapter.feed(*_chunk("late")) == []  # nothing after finish


@pytest.mark.parametrize("payload", [None, 5, "x", {"n": None}, {"n": {"messages": "no"}}, (1,)])
def test_garbage_input_never_raises(payload: Any) -> None:
    adapter = UIStreamAdapter("m")
    adapter.start()
    assert adapter.feed("updates", payload) == []
    assert adapter.feed("messages", payload) == []
    assert adapter.feed("other", payload) == []
