"""Drive an agent turn, including the "empty reply" recovery shared by the CLI and the API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.streaming.adapter import message_text

MAX_EMPTY_NUDGES = 2
EMPTY_REPLY_NUDGE = (
    "Your last reply was empty. Continue the task: finish any remaining steps, save the report "
    "and charts under /home/user/outputs/, then give your final answer containing the full report."
)


class AgentDriver:
    """Streams `(mode, payload)` events for one user turn.

    Open-weight models sometimes end a turn with an empty message. We nudge them (at most
    `MAX_EMPTY_NUDGES` times) and count it, because it is a real failure mode worth measuring.
    After `events()` is exhausted, `final_answer` and `nudges` are set.
    """

    def __init__(self, agent: Any, config: RunnableConfig, question: str) -> None:
        self._agent = agent
        self._config = config
        self._question = question
        self.final_answer = ""
        self.nudges = 0
        self.final_message_meta: dict[str, Any] = {}

    async def events(self) -> AsyncIterator[tuple[str, Any]]:
        next_input = self._question
        while True:
            async for event in self._agent.astream(
                {"messages": [HumanMessage(next_input)]},
                self._config,
                stream_mode=["messages", "updates"],
            ):
                yield event
            state = await self._agent.aget_state(self._config)
            messages = state.values.get("messages", [])
            last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            self.final_answer = message_text(last_ai).strip() if last_ai else ""
            if last_ai is not None:
                self.final_message_meta = {
                    "finish_reason": last_ai.response_metadata.get("finish_reason"),
                    "n_tool_calls": len(last_ai.tool_calls),
                    "total_messages": len(messages),
                    "last_message_types": [type(m).__name__ for m in messages[-4:]],
                }
            if self.final_answer or self.nudges >= MAX_EMPTY_NUDGES:
                return
            self.nudges += 1
            next_input = EMPTY_REPLY_NUDGE
