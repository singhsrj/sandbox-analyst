"""Assemble the Deep Agent: model + custom tools + sandbox backend + checkpointer."""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.models import get_model
from app.agent.prompt import SYSTEM_PROMPT
from app.artifacts import ArtifactStore
from app.config import Settings
from app.sandbox.manager import SandboxManager
from app.tools.analyst_tools import ToolContext, build_tools


async def build_agent(
    settings: Settings,
    *,
    thread_id: str,
    sandboxes: SandboxManager,
    artifacts: ArtifactStore,
    sql_log: list[dict[str, Any]],
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """Return a compiled agent bound to this thread's sandbox.

    The sandbox is the agent's backend, so Deep Agents' built-in file tools and `execute` run
    INSIDE it (never on the host). Our custom tools are the only way to reach the database.
    """
    # M2 creates the sandbox up front (about 2s). M3 makes this lazy on first tool use.
    sandbox = await sandboxes.get(thread_id)
    ctx = ToolContext(
        settings=settings,
        get_sandbox=lambda: sandboxes.get(thread_id),
        artifacts=artifacts,
        sql_log=sql_log,
    )
    return create_deep_agent(
        model=model or get_model(settings),
        tools=build_tools(ctx),
        system_prompt=SYSTEM_PROMPT,
        backend=sandbox,
        checkpointer=checkpointer or InMemorySaver(),
        name="sandbox-analyst",
    )
