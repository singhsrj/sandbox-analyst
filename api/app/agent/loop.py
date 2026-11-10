"""Drive an agent turn, including the "empty reply" recovery shared by the CLI and the API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.agent.approvals import PendingApproval, pending_from_interrupts
from app.streaming.adapter import message_text

logger = logging.getLogger(__name__)

MAX_EMPTY_NUDGES = 2
EMPTY_REPLY_NUDGE = (
    "Your last reply was empty. Continue the task: finish any remaining steps, save the report "
    "and charts under /home/user/outputs/, then give your final answer containing the full report."
)

# One repair attempt when the answer names files that were never saved. More than one would just
# repeat the same mistake; the UI still warns the user if the claim survives.
MAX_FILE_NUDGES = 1
FileVerifier = Callable[[str], Awaitable[list[str]]]


def missing_files_nudge(names: list[str]) -> str:
    return (
        f"Your answer mentions files that do not exist: {', '.join(names)}. Nothing with that name "
        "was saved under /home/user/outputs/. Either create the file there now (run the script and "
        "check that it succeeded), or leave it out. Then give your complete final answer again, "
        "mentioning only files that really exist."
    )


class AgentDriver:
    """Streams `(mode, payload)` events for one user turn (or for resuming a paused one).

    Open-weight models sometimes end a turn with an empty message. We nudge them (at most
    `MAX_EMPTY_NUDGES` times) and count it, because it is a real failure mode worth measuring.
    The same goes for an answer that names files which were never saved: when `verify_files` is
    given, it returns the missing names and the model is asked once (`MAX_FILE_NUDGES`) to create
    them or drop the claim. After `events()` is exhausted, `final_answer`, `nudges`,
    `file_nudges` and `pending` are set; a non-empty `pending` means the run is paused, waiting
    for a human to approve a query.
    """

    def __init__(
        self,
        agent: Any,
        config: RunnableConfig,
        question: str,
        *,
        resume: dict[str, Any] | None = None,
        verify_files: FileVerifier | None = None,
    ) -> None:
        self._agent = agent
        self._config = config
        self._question = question
        self._resume = resume
        self._verify_files = verify_files
        self.final_answer = ""
        self.nudges = 0
        self.file_nudges = 0
        self.final_message_meta: dict[str, Any] = {}
        self.pending: list[PendingApproval] = []

    async def events(self) -> AsyncIterator[tuple[str, Any]]:
        next_input: Any = (
            Command(resume=self._resume)
            if self._resume is not None
            else {"messages": [HumanMessage(self._question)]}
        )
        while True:
            async for event in self._agent.astream(
                next_input,
                self._config,
                stream_mode=["messages", "updates"],
            ):
                yield event
            state = await self._agent.aget_state(self._config)
            self.pending = pending_from_interrupts(getattr(state, "interrupts", ()))
            if self.pending:
                return  # paused for approval; not an empty reply
            messages = state.values.get("messages", [])
            last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            earlier_answer = self.final_answer  # set only when a file nudge asked for a redo
            self.final_answer = message_text(last_ai).strip() if last_ai else ""
            if last_ai is not None:
                self.final_message_meta = {
                    "finish_reason": last_ai.response_metadata.get("finish_reason"),
                    "n_tool_calls": len(last_ai.tool_calls),
                    "total_messages": len(messages),
                    "last_message_types": [type(m).__name__ for m in messages[-4:]],
                }
            if not self.final_answer and earlier_answer and self.file_nudges:
                self.final_answer = earlier_answer  # a redo that came back empty loses nothing
                return
            if self.final_answer:
                missing = await self._missing_files()
                if not missing:
                    return
                self.file_nudges += 1
                next_input = {"messages": [HumanMessage(missing_files_nudge(missing))]}
                continue
            if self.nudges >= MAX_EMPTY_NUDGES:
                return
            self.nudges += 1
            next_input = {"messages": [HumanMessage(EMPTY_REPLY_NUDGE)]}

    async def _missing_files(self) -> list[str]:
        """File names the current answer claims but the sandbox never produced (empty when the
        check is off, already used, or itself failed: it must never break a finished run)."""
        if self._verify_files is None or self.file_nudges >= MAX_FILE_NUDGES:
            return []
        try:
            return await self._verify_files(self.final_answer)
        except Exception:
            logger.exception("checking the answer's file claims failed")
            return []
