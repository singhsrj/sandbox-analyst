"""An answer that names a file the agent never saved gets one repair attempt (loop.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage

from app.agent.loop import MAX_FILE_NUDGES, AgentDriver
from tests.fakes import FakeAgent

CLAIM = "Summary. See repeat_by_channel.png for the chart."
FIXED = "Summary. No chart was produced."


class AnswersInOrder(FakeAgent):
    """Each model pass ends with the next scripted answer."""

    def __init__(self, *answers: str) -> None:
        super().__init__([], "")
        self._answers = list(answers)

    async def aget_state(self, config: Any) -> Any:
        text = self._answers[min(self.calls, len(self._answers)) - 1]
        return SimpleNamespace(values={"messages": [AIMessage(text)]}, interrupts=())


async def run(agent: FakeAgent, missing: dict[str, list[str]] | None = None) -> AgentDriver:
    asked: list[str] = []

    async def verify(answer: str) -> list[str]:
        asked.append(answer)
        return (missing or {}).get(answer, [])

    driver = AgentDriver(agent, {"configurable": {"thread_id": "t"}}, "q", verify_files=verify)
    async for _ in driver.events():
        pass
    return driver


async def test_a_missing_file_triggers_one_redo_and_the_new_answer_wins() -> None:
    agent = AnswersInOrder(CLAIM, FIXED)
    driver = await run(agent, {CLAIM: ["repeat_by_channel.png"]})

    assert driver.file_nudges == 1 and driver.nudges == 0
    assert driver.final_answer == FIXED
    assert agent.calls == 2
    assert "repeat_by_channel.png" in agent.inputs[1]  # the nudge names the file


async def test_a_claim_that_survives_the_redo_is_not_asked_about_again() -> None:
    agent = AnswersInOrder(CLAIM, CLAIM)
    driver = await run(agent, {CLAIM: ["repeat_by_channel.png"]})

    assert driver.file_nudges == MAX_FILE_NUDGES and agent.calls == 2
    assert driver.final_answer == CLAIM  # the UI warning still covers it


async def test_an_answer_with_no_missing_files_is_left_alone() -> None:
    agent = AnswersInOrder("All good.")
    driver = await run(agent)
    assert driver.file_nudges == 0 and agent.calls == 1 and driver.final_answer == "All good."


async def test_an_empty_redo_keeps_the_original_answer() -> None:
    agent = AnswersInOrder(CLAIM, "", "")
    driver = await run(agent, {CLAIM: ["repeat_by_channel.png"]})
    assert driver.final_answer == CLAIM


async def test_the_check_is_off_without_a_verifier() -> None:
    agent = AnswersInOrder(CLAIM)
    driver = AgentDriver(agent, {"configurable": {"thread_id": "t"}}, "q")
    async for _ in driver.events():
        pass
    assert driver.file_nudges == 0 and agent.calls == 1


async def test_a_failing_check_never_breaks_the_run() -> None:
    async def boom(answer: str) -> list[str]:
        raise RuntimeError("sandbox gone")

    agent = AnswersInOrder(CLAIM)
    driver = AgentDriver(agent, {"configurable": {"thread_id": "t"}}, "q", verify_files=boom)
    async for _ in driver.events():
        pass
    assert driver.final_answer == CLAIM and driver.file_nudges == 0
