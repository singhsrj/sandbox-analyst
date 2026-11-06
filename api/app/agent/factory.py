"""Assemble the Deep Agent: model + custom tools + sandbox backend + checkpointer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.approvals import approval_middleware
from app.agent.models import get_model
from app.agent.prompt import SYSTEM_PROMPT
from app.artifacts import ArtifactStore
from app.config import ApprovalMode, Settings
from app.sandbox.manager import SandboxManager
from app.tools.analyst_tools import ToolContext, build_tools

if TYPE_CHECKING:  # deepagents is slow to import; see build_agent
    from deepagents.middleware.subagents import SubAgent


async def build_agent(
    settings: Settings,
    *,
    thread_id: str,
    sandboxes: SandboxManager,
    artifacts: ArtifactStore,
    sql_log: list[dict[str, Any]],
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    known_sandbox_id: str | None = None,
    approval_mode: ApprovalMode = "off",
) -> Any:
    """Return a compiled agent bound to this thread's sandbox.

    The sandbox is the agent's backend, so Deep Agents' built-in file tools and `execute` run
    INSIDE it (never on the host). Our custom tools are the only way to reach the database.
    """
    # Imported here, not at module level: deepagents pulls in the whole anthropic SDK, which makes
    # importing it cost 15-50 s on a slow disk. The API layer and unit tests should not pay for it.
    from deepagents import create_deep_agent

    sandbox = await sandboxes.get(thread_id, known_sandbox_id=known_sandbox_id)
    ctx = ToolContext(
        settings=settings,
        get_sandbox=lambda: sandboxes.get(thread_id),
        artifacts=artifacts,
        sql_log=sql_log,
    )
    approvals = approval_middleware(approval_mode)
    return create_deep_agent(
        model=model or get_model(settings),
        tools=build_tools(ctx),
        system_prompt=SYSTEM_PROMPT,
        middleware=[approvals] if approvals else [],
        subagents=[general_purpose_subagent()],
        backend=sandbox,
        checkpointer=checkpointer or InMemorySaver(),
        name="sandbox-analyst",
    )


def general_purpose_subagent() -> SubAgent:
    """Deep Agents' default helper sub-agent, minus our database tools.

    By default it inherits every custom tool, and our `middleware` (with the approval gate) is not
    passed down to sub-agents. A sub-agent with `run_sql` would therefore be a way around human
    approval. Giving it no custom tools closes that gap: it can still read/write files and run
    code in the same sandbox, but only the main agent can query the database.
    """
    from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT

    spec: SubAgent = {**GENERAL_PURPOSE_SUBAGENT, "tools": []}
    return spec
