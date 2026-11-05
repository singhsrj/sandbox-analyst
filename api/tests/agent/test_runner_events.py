from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from app.agent.runner import _events_from_update


def test_tool_calls_results_and_final_text_become_events() -> None:
    call = {"name": "run_sql", "args": {"query": "x"}, "id": "1"}
    update = {
        "model": {"messages": [AIMessage("", tool_calls=[call])]},
        "tools": {"messages": [ToolMessage("OK: 3 rows", name="run_sql", tool_call_id="1")]},
    }
    events = _events_from_update(update)
    assert [e["type"] for e in events] == ["tool_call", "tool_result"]
    assert events[0]["name"] == "run_sql" and events[1]["text"] == "OK: 3 rows"
    final = _events_from_update({"model": {"messages": [AIMessage("The answer is 42.")]}})
    assert final == [{"type": "assistant", "text": "The answer is 42."}]


def test_unexpected_update_shapes_are_ignored_not_fatal() -> None:
    assert _events_from_update(None) == []
    assert _events_from_update({"node": None}) == []
    assert _events_from_update({"node": {"messages": "not a list"}}) == []
