"""Human-in-the-loop approval of SQL queries (ADR-022).

How it works:
  * LangChain's `HumanInTheLoopMiddleware` in `per_call` mode pauses the graph (a LangGraph
    `interrupt`) right before a gated `run_sql` call runs. The paused state lives in the
    checkpointer, so the HTTP request can end and a later request can resume it.
  * Each interrupt carries the tool call id, so the UI attaches the approval card to the exact
    tool step it is about. The interrupt id is the approval id the browser sends back.
  * The reviewer can approve, reject (optionally with a reason the model reads) or edit the SQL.
    An edited query still goes through the validator and the read-only role: approval never
    widens what SQL can do, it only adds a human check on top.

Why our own middleware instead of `create_deep_agent(interrupt_on=...)`: that path builds the
middleware in `batched` mode, whose interrupts do not say which tool call they are about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.config import ApprovalMode
from app.security.sql_risk import assess_query

if TYPE_CHECKING:
    from langchain.agents.middleware import HumanInTheLoopMiddleware

GATED_TOOL = "run_sql"
MAX_REASON_CHARS = 500

STRICT_REASON = "Strict mode: every query is shown to you before it runs."


def _query_of(args: Any) -> str:
    return str(args.get("query", "")) if isinstance(args, dict) else ""


def approval_reason(mode: ApprovalMode, query: str) -> str:
    """The text shown on the approval card (and kept in the trace)."""
    if mode == "strict":
        return STRICT_REASON
    reasons = assess_query(query).reasons
    return "Flagged for review: " + "; ".join(reasons) if reasons else "Flagged for review."


def approval_middleware(mode: ApprovalMode) -> HumanInTheLoopMiddleware[Any, Any, Any] | None:
    """The middleware that gates run_sql for this mode, or None when approvals are off."""
    if mode == "off":
        return None
    from langchain.agents.middleware import HumanInTheLoopMiddleware, InterruptOnConfig

    def describe(tool_call: Any, state: Any, runtime: Any) -> str:
        return approval_reason(mode, _query_of(tool_call.get("args")))

    config = InterruptOnConfig(
        allowed_decisions=["approve", "edit", "reject"], description=describe
    )
    if mode == "normal":
        # Deterministic (pure function of the SQL text): LangChain re-runs it on resume.
        config["when"] = lambda request: assess_query(_query_of(request.tool_call["args"])).flagged
    return HumanInTheLoopMiddleware(interrupt_on={GATED_TOOL: config}, interrupt_mode="per_call")


# --------------------------------------------------------------------------- pause and resume
@dataclass(frozen=True)
class PendingApproval:
    id: str  # LangGraph interrupt id == AI SDK approval id
    tool_call_id: str
    name: str
    args: dict[str, Any]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "args": self.args,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingApproval:
        return cls(
            id=str(data["id"]),
            tool_call_id=str(data["tool_call_id"]),
            name=str(data["name"]),
            args=dict(data.get("args") or {}),
            reason=str(data.get("reason", "")),
        )


def pending_from_interrupts(interrupts: Any) -> list[PendingApproval]:
    """Approval requests among LangGraph interrupts (anything else is ignored)."""
    pending: list[PendingApproval] = []
    for item in interrupts or ():
        value = getattr(item, "value", None)
        if not isinstance(value, dict) or value.get("type") != "tool_approval":
            continue
        pending.append(
            PendingApproval(
                id=str(item.id),
                tool_call_id=str(value.get("tool_call_id", "")),
                name=str(value.get("name", "")),
                args=dict(value.get("args") or {}),
                reason=str(value.get("description", "")),
            )
        )
    return pending


@dataclass(frozen=True)
class ApprovalAnswer:
    id: str
    approved: bool
    reason: str | None = None
    edited_query: str | None = None


class ApprovalMismatch(ValueError):
    """The answers do not match the approvals that are actually pending."""


def resume_payload(
    answers: list[ApprovalAnswer], pending: list[PendingApproval]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Map the browser's answers to LangGraph resume values, keyed by interrupt id.

    Returns (resume, audit). Every pending approval needs exactly one answer: a partial answer
    would leave the graph paused in a state the UI cannot show.
    """
    by_id = {p.id: p for p in pending}
    answered = [a.id for a in answers]
    if len(set(answered)) != len(answered) or set(answered) != set(by_id):
        raise ApprovalMismatch(
            "These approvals do not match the queries waiting for review. Reload the "
            "conversation and try again."
        )
    resume: dict[str, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    for answer in answers:
        item = by_id[answer.id]
        reason = (answer.reason or "").strip()[:MAX_REASON_CHARS] or None
        original = _query_of(item.args)
        edited = (answer.edited_query or "").strip()
        if answer.approved and edited and edited != original.strip():
            decision: dict[str, Any] = {
                "type": "edit",
                "edited_action": {"name": item.name, "args": {**item.args, "query": edited}},
            }
        elif answer.approved:
            decision = {"type": "approve"}
        else:
            decision = {"type": "reject", **({"message": reason} if reason else {})}
        resume[answer.id] = decision
        audit.append(
            {
                "id": answer.id,
                "tool_call_id": item.tool_call_id,
                "decision": decision["type"],
                "reason": reason,
                **({"edited_query": edited} if decision["type"] == "edit" else {}),
            }
        )
    return resume, audit
