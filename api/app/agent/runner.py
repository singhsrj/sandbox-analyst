"""Run one question end to end and return a complete, serialisable record of what happened.

M2 uses this from the CLI. M3 replaces the printing with the SSE streaming adapter, but the run
record (question, steps, SQL, usage, trace id) is the same shape the replay mode and the eval
harness will consume.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agent.factory import build_agent
from app.agent.loop import AgentDriver
from app.agent.models import get_model
from app.agent.outputs import collect_outputs, missing_file_claims, unverified_file_claims
from app.agent.usage import BudgetExceeded, StepLimitExceeded, UsageTracker
from app.artifacts import ArtifactStore
from app.config import ModelProvider, Settings
from app.observability import finalize_trace, make_handler
from app.sandbox.manager import SandboxManager

EventSink = Callable[[dict[str, Any]], None]


@dataclass
class RunRecord:
    thread_id: str
    question: str
    provider: str
    model: str
    started_at: str
    status: str = "ok"  # ok | budget_exceeded | step_limit | error
    empty_reply_nudges: int = 0  # times the model ended its turn empty and was prompted again
    file_claim_nudges: int = 0  # times the answer named a file that did not exist and was redone
    error: str | None = None
    final_answer: str = ""
    final_message_meta: dict[str, Any] = field(
        default_factory=dict
    )  # diagnostics for empty answers
    steps: list[dict[str, Any]] = field(default_factory=list)
    sql: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    # chart/report files the answer mentions that were never delivered
    unverified_file_claims: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0
    trace_id: str | None = None
    trace_url: str | None = None

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, default=str)


def _clip(value: Any, n: int = 600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= n else text[: n - 1] + "…"


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)


def _events_from_update(update: Any) -> list[dict[str, Any]]:
    """Turn one LangGraph 'updates' chunk into plain step events."""
    events: list[dict[str, Any]] = []
    if not isinstance(update, dict):
        return events
    for node_update in update.values():
        messages = node_update.get("messages") if isinstance(node_update, dict) else None
        if not isinstance(messages, list):
            continue
        for message in messages:
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    events.append({"type": "tool_call", "name": call["name"], "args": call["args"]})
                if message.content and not message.tool_calls:
                    events.append({"type": "assistant", "text": _text(message)})
            elif isinstance(message, ToolMessage):
                events.append(
                    {"type": "tool_result", "name": message.name, "text": _clip(_text(message))}
                )
    return events


async def run_question(
    question: str,
    settings: Settings,
    *,
    provider: ModelProvider | None = None,
    model: str | None = None,
    thread_id: str | None = None,
    on_event: EventSink | None = None,
) -> RunRecord:
    thread_id = thread_id or f"run-{uuid.uuid4().hex[:10]}"
    provider = provider or settings.model_provider
    model_id = model or settings.model
    record = RunRecord(
        thread_id=thread_id,
        question=question,
        provider=provider,
        model=model_id,
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    artifacts = ArtifactStore(settings.artifacts_dir, thread_id)
    tracker = UsageTracker(
        max_tokens=settings.max_tokens_per_request,
        max_cost_usd=settings.max_cost_usd_per_request,
        max_llm_calls=settings.max_agent_steps,
    )
    handler = make_handler(settings)
    callbacks: list[Any] = [tracker] + ([handler] if handler else [])
    config: RunnableConfig = {
        "callbacks": callbacks,
        # LangGraph counts graph super-steps (several per model call). The real limit is the
        # model-call cap in UsageTracker; this is only a generous backstop.
        "recursion_limit": settings.max_agent_steps * 6 + 20,
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_tags": ["m2-cli", provider, model_id],
            "model": model_id,
            "provider": provider,
        },
        "run_name": "analyst-run",
    }

    started = time.monotonic()
    async with SandboxManager(settings) as sandboxes:
        try:
            agent = await build_agent(
                settings,
                thread_id=thread_id,
                sandboxes=sandboxes,
                artifacts=artifacts,
                sql_log=record.sql,
                model=get_model(settings, provider=provider, model=model_id),
            )
            driver = AgentDriver(
                agent,
                config,
                question,
                verify_files=lambda answer: missing_file_claims(
                    sandboxes, thread_id, artifacts, answer
                ),
            )
            async for mode, payload in driver.events():
                if mode != "updates":
                    continue
                for event in _events_from_update(payload):
                    record.steps.append(event)
                    if on_event:
                        on_event(event)
            record.final_answer = driver.final_answer
            record.empty_reply_nudges = driver.nudges
            record.file_claim_nudges = driver.file_nudges
            record.final_message_meta = driver.final_message_meta
        except StepLimitExceeded as exc:
            record.status, record.error = "step_limit", str(exc)
        except BudgetExceeded as exc:
            record.status, record.error = "budget_exceeded", str(exc)
        except Exception as exc:  # report every failure in the record instead of losing the run
            name = type(exc).__name__
            record.status = "step_limit" if name == "GraphRecursionError" else "error"
            record.error = f"{name}: {_clip(str(exc), 400)}"
        # Deliver whatever the agent saved under /home/user/outputs/ (even after a failure).
        await collect_outputs(sandboxes, thread_id, artifacts)

    record.seconds = round(time.monotonic() - started, 1)
    record.usage = tracker.summary.as_dict()
    record.artifacts = [
        {"name": a.name, "size": a.size, "mime": a.mime, "path": str(a.path)}
        for a in artifacts.list()
    ]
    record.unverified_file_claims = unverified_file_claims(
        record.final_answer, artifacts.all_names()
    )
    record.trace_id, record.trace_url = finalize_trace(handler, settings)
    return record
