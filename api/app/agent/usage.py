"""Token/cost accounting and per-request budget enforcement.

`UsageTracker` is a LangChain callback: it sums token usage across every model call in a run,
records which exact model ids answered, and raises `BudgetExceeded` as soon as the token budget
is crossed (`raise_error = True` makes LangChain propagate the exception instead of swallowing it).
Cost is only reported when a verified price exists in model_prices.json; otherwise it is None.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

PRICES_FILE = Path(__file__).parent / "model_prices.json"


class BudgetExceeded(RuntimeError):
    """The run used more tokens (or dollars) than its budget allows."""


class StepLimitExceeded(BudgetExceeded):
    """The run made more model calls than allowed (runaway-loop protection)."""


@lru_cache
def load_prices() -> dict[str, tuple[float, float]]:
    data = json.loads(PRICES_FILE.read_text(encoding="utf-8"))
    raw = data.get("prices_per_million_usd", {})
    return {model: (float(p["input"]), float(p["output"])) for model, p in raw.items()}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost in USD, or None when we have no verified price for this model."""
    price = load_prices().get(model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


@dataclass
class UsageSummary:
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    models: list[str] = field(default_factory=list)
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "models": self.models,
            "cost_usd": self.cost_usd,
        }


class UsageTracker(AsyncCallbackHandler):
    raise_error = True  # let BudgetExceeded stop the run

    def __init__(
        self,
        *,
        max_tokens: int,
        max_cost_usd: float | None = None,
        max_llm_calls: int | None = None,
    ) -> None:
        self.max_llm_calls = max_llm_calls
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.summary = UsageSummary()
        self._costs: list[float | None] = []

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        for generation_list in response.generations:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) or {}
                meta = getattr(message, "response_metadata", None) or {}
                model = str(meta.get("model_name") or meta.get("model") or "unknown")
                self._record(
                    model, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
                )

    def _record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        s = self.summary
        s.llm_calls += 1
        s.input_tokens += input_tokens
        s.output_tokens += output_tokens
        if model not in s.models:
            s.models.append(model)
        self._costs.append(cost_usd(model, input_tokens, output_tokens))
        known = [c for c in self._costs if c is not None]
        s.cost_usd = sum(known) if len(known) == len(self._costs) else None

        if self.max_llm_calls is not None and s.llm_calls > self.max_llm_calls:
            raise StepLimitExceeded(
                f"Step limit exceeded: more than {self.max_llm_calls} model calls."
            )
        if s.total_tokens > self.max_tokens:
            raise BudgetExceeded(
                f"Token budget exceeded: {s.total_tokens:,} > {self.max_tokens:,} tokens."
            )
        if self.max_cost_usd is not None and s.cost_usd is not None:
            if s.cost_usd > self.max_cost_usd:
                raise BudgetExceeded(
                    f"Cost budget exceeded: ${s.cost_usd:.4f} > ${self.max_cost_usd:.2f}."
                )
