"""Human approval of SQL: mapping decisions, and the real LangGraph pause/resume with a fake model.

The graph tests use LangChain's real `create_agent` + `HumanInTheLoopMiddleware` + an in-memory
checkpointer, driven by a scripted chat model, so the interrupt and resume semantics we rely on
are exercised for real (no network).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.approvals import (
    STRICT_REASON,
    ApprovalAnswer,
    ApprovalMismatch,
    PendingApproval,
    approval_middleware,
    approval_reason,
    resume_payload,
)
from app.agent.loop import AgentDriver
from app.streaming.adapter import UIStreamAdapter

FLAGGED = "SELECT * FROM analytics.orders"
SAFE = "SELECT count(*) FROM analytics.orders"


def pending(query: str = FLAGGED) -> PendingApproval:
    return PendingApproval(
        id="i-1",
        tool_call_id="c-1",
        name="run_sql",
        args={"query": query, "output_file": "o.csv"},
        reason="r",
    )


# --------------------------------------------------------------------------- decision mapping
def test_approve_reject_and_edit_map_to_langchain_decisions() -> None:
    approve, audit = resume_payload([ApprovalAnswer("i-1", True)], [pending()])
    assert approve == {"i-1": {"type": "approve"}} and audit[0]["decision"] == "approve"

    reject, _ = resume_payload([ApprovalAnswer("i-1", False, "too big")], [pending()])
    assert reject == {"i-1": {"type": "reject", "message": "too big"}}

    bare_reject, _ = resume_payload([ApprovalAnswer("i-1", False)], [pending()])
    assert bare_reject == {"i-1": {"type": "reject"}}

    edit, audit = resume_payload(
        [ApprovalAnswer("i-1", True, edited_query=FLAGGED + " LIMIT 100")], [pending()]
    )
    action = edit["i-1"]["edited_action"]
    assert edit["i-1"]["type"] == "edit" and action["name"] == "run_sql"
    assert action["args"] == {"query": FLAGGED + " LIMIT 100", "output_file": "o.csv"}
    assert audit[0]["edited_query"].endswith("LIMIT 100")


def test_an_unchanged_edit_is_a_plain_approval() -> None:
    resume, _ = resume_payload(
        [ApprovalAnswer("i-1", True, edited_query=f"  {FLAGGED} ")], [pending()]
    )
    assert resume == {"i-1": {"type": "approve"}}


def test_an_edit_on_a_rejection_is_ignored() -> None:
    resume, _ = resume_payload([ApprovalAnswer("i-1", False, edited_query="SELECT 1")], [pending()])
    assert resume["i-1"]["type"] == "reject"


def test_reasons_are_trimmed_to_a_safe_length() -> None:
    resume, _ = resume_payload([ApprovalAnswer("i-1", False, "x" * 5000)], [pending()])
    assert len(resume["i-1"]["message"]) == 500


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [ApprovalAnswer("someone-else", True)],
        [ApprovalAnswer("i-1", True), ApprovalAnswer("i-1", False)],
        [ApprovalAnswer("i-1", True), ApprovalAnswer("extra", True)],
    ],
)
def test_answers_must_match_the_pending_approvals_exactly(answers: list[ApprovalAnswer]) -> None:
    with pytest.raises(ApprovalMismatch):
        resume_payload(answers, [pending()])


def test_reasons_shown_on_the_card() -> None:
    assert approval_reason("strict", SAFE) == STRICT_REASON
    assert "raw rows of analytics.orders" in approval_reason("normal", FLAGGED)


def test_off_mode_adds_no_middleware() -> None:
    assert approval_middleware("off") is None


def test_the_helper_subagent_cannot_query_the_database() -> None:
    """Our approval middleware is not passed to sub-agents, so they must not have run_sql."""
    from app.agent.factory import general_purpose_subagent

    spec = general_purpose_subagent()
    assert spec["name"] == "general-purpose" and spec["tools"] == []


# --------------------------------------------------------------------------- real graph
class ScriptedModel(GenericFakeChatModel):
    """A fake chat model that supports tool binding (create_agent needs it). Streaming is off
    because the fake streams by splitting text and yields nothing for a tool-call-only reply."""

    disable_streaming: bool = True

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


def scripted(*queries: str) -> Iterator[AIMessage]:
    for i, query in enumerate(queries):
        call = {"name": "run_sql", "args": {"query": query, "output_file": "o.csv"}, "id": f"c-{i}"}
        yield AIMessage("", tool_calls=[call], id=f"m-{i}")
    yield AIMessage("Final answer.", id="m-final")


def build(mode: Any, *queries: str) -> tuple[Any, list[str]]:
    executed: list[str] = []

    @tool
    async def run_sql(query: str, output_file: str) -> str:
        """Run a query."""
        executed.append(query)
        return f"OK: ran {query}"

    middleware = approval_middleware(mode)
    agent = create_agent(
        ScriptedModel(messages=scripted(*queries)),
        tools=[run_sql],
        middleware=[middleware] if middleware else [],
        checkpointer=InMemorySaver(),
    )
    return agent, executed


async def drive(
    agent: Any, thread: str, *, resume: dict[str, Any] | None = None
) -> tuple[AgentDriver, list[dict[str, Any]]]:
    config: Any = {"configurable": {"thread_id": thread}}
    driver = AgentDriver(agent, config, "How many orders?", resume=resume)
    adapter = UIStreamAdapter("msg")
    chunks = adapter.start(continuing=resume is not None)
    async for mode, payload in driver.events():
        chunks.extend(adapter.feed(mode, payload))
    return driver, chunks


async def test_normal_mode_pauses_only_on_flagged_queries_and_resumes_after_approval() -> None:
    agent, executed = build("normal", SAFE, FLAGGED)
    driver, chunks = await drive(agent, "t-normal")

    assert executed == [SAFE]  # the safe query ran without asking
    (item,) = driver.pending
    assert item.tool_call_id == "c-1" and item.args["query"] == FLAGGED
    request = next(c for c in chunks if c["type"] == "tool-approval-request")
    assert request["toolCallId"] == "c-1" and request["approvalId"] == item.id
    assert "raw rows" in request["reason"]
    assert driver.nudges == 0 and driver.final_answer == ""  # a pause is not an empty reply

    resume, _ = resume_payload([ApprovalAnswer(item.id, True)], driver.pending)
    driver, chunks = await drive(agent, "t-normal", resume=resume)
    assert executed == [SAFE, FLAGGED]
    assert not driver.pending and driver.final_answer == "Final answer."
    assert any(c["type"] == "tool-output-available" and c["toolCallId"] == "c-1" for c in chunks)
    assert chunks[0] == {"type": "start"}  # continues the same browser message


async def test_strict_mode_pauses_on_every_query() -> None:
    agent, executed = build("strict", SAFE)
    driver, _ = await drive(agent, "t-strict")
    assert executed == [] and len(driver.pending) == 1


async def test_off_mode_never_pauses() -> None:
    agent, executed = build("off", FLAGGED)
    driver, _ = await drive(agent, "t-off")
    assert executed == [FLAGGED] and not driver.pending


async def test_a_rejected_query_never_runs_and_shows_as_denied() -> None:
    agent, executed = build("strict", FLAGGED)
    driver, _ = await drive(agent, "t-reject")
    resume, audit = resume_payload([ApprovalAnswer(driver.pending[0].id, False)], driver.pending)

    config: Any = {"configurable": {"thread_id": "t-reject"}}
    resumed = AgentDriver(agent, config, "q", resume=resume)
    adapter = UIStreamAdapter("msg")
    chunks = adapter.start(continuing=True) + adapter.approval_responses(audit)
    async for mode, payload in resumed.events():
        chunks.extend(adapter.feed(mode, payload))

    assert executed == []
    assert {
        "type": "tool-approval-response",
        "approvalId": driver.pending[0].id,
        "approved": False,
    } in chunks
    assert {"type": "tool-output-denied", "toolCallId": "c-0"} in chunks
    assert resumed.final_answer == "Final answer."


async def test_an_edited_query_is_what_actually_runs() -> None:
    agent, executed = build("strict", FLAGGED)
    driver, _ = await drive(agent, "t-edit")
    edited = FLAGGED + " WHERE order_date >= '2025-03-01'"
    resume, _ = resume_payload(
        [ApprovalAnswer(driver.pending[0].id, True, edited_query=edited)], driver.pending
    )
    await drive(agent, "t-edit", resume=resume)
    assert executed == [edited]
