"""Translate LangGraph stream events into AI SDK "UI message stream" chunks.

Pure and synchronous: no I/O, no model, no network, so it is fully unit-testable. The chunk
shapes follow https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol and are additionally validated
against the real `ai` package's own schema by web/ (contract test, M4).

Input  : `(mode, payload)` pairs from `agent.astream(..., stream_mode=["messages", "updates"])`.
           * "messages": (message_chunk, metadata)  -> live text
           * "updates" : {node_name: {"messages": [...]}} -> tool calls and tool results
Output : lists of plain-dict chunks (one SSE `data:` line each).

Design choices
  * Tool cards come from "updates" (complete inputs, reliable outputs); text streams live from
    "messages". Models that send their answer in one burst work just as well as token streamers.
  * If a final answer only shows up in "updates" (some providers do not stream), it is emitted
    from there, so the user never sees an empty reply.
  * The agent's todo list is surfaced as a `data-todos` part (same id -> updated in place).
  * Custom data parts: data-todos, data-artifacts, data-run.
  * Human approval uses the SDK's own tool-approval-request / tool-approval-response /
    tool-output-denied chunks; a resumed run continues the same assistant message.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

Chunk = dict[str, Any]

MAX_TOOL_OUTPUT_CHARS = 6_000
TODO_TOOL = "write_todos"
INTERRUPT_KEY = "__interrupt__"  # LangGraph puts pending interrupts under this key in "updates"


def clip(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... [truncated, {len(text) - limit:,} more characters]"


def message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in (None, "text"):
            parts.append(str(block.get("text", "")))
    return "".join(parts)


class UIStreamAdapter:
    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        self.final_text = ""  # text produced after the last tool call (the user-facing answer)
        self._text_seq = 0
        self._open_text: str | None = None
        self._streamed_ids: set[str] = set()
        self._tool_inputs: set[str] = set()
        self._tool_outputs: set[str] = set()
        self._denied: set[str] = set()  # tool calls a reviewer rejected
        self._approvals: set[str] = set()
        # Approval interrupts already sent to the browser. LangGraph checkpoints a pause before it
        # emits it, so these are pending even if the client disconnects right afterwards.
        self.interrupts_sent: list[Any] = []
        self._finished = False
        self._continuing = False

    # ------------------------------------------------------------------ lifecycle
    def start(self, *, continuing: bool = False) -> list[Chunk]:
        """Open the message. When `continuing` (resuming after an approval), no messageId is
        sent, so the browser keeps appending to the assistant message it already shows."""
        self._continuing = continuing
        first: Chunk = (
            {"type": "start"}
            if continuing
            else {
                "type": "start",
                "messageId": self.message_id,
            }
        )
        return [first, {"type": "start-step"}]

    def approval_responses(self, audit: list[dict[str, Any]]) -> list[Chunk]:
        """Record the reviewer's decisions in the stream (so a replay shows them too)."""
        out: list[Chunk] = []
        for item in audit:
            approved = item["decision"] != "reject"
            if not approved:
                self._denied.add(item["tool_call_id"])
            chunk: Chunk = {
                "type": "tool-approval-response",
                "approvalId": item["id"],
                "approved": approved,
            }
            note = item.get("reason") or (
                "Edited by the reviewer before it ran." if item["decision"] == "edit" else None
            )
            if note:
                chunk["reason"] = note
            out.append(chunk)
        return out

    def finish(
        self,
        *,
        error: str | None = None,
        data_parts: list[Chunk] | None = None,
    ) -> list[Chunk]:
        """Close anything open, append data parts, and end the message."""
        if self._finished:
            return []
        self._finished = True
        out = self._close_text()
        if error:
            out.append({"type": "error", "errorText": error})
        out.extend(data_parts or [])
        out.extend([{"type": "finish-step"}, {"type": "finish"}])
        return out

    # ------------------------------------------------------------------ main entry
    def feed(self, mode: str, payload: Any) -> list[Chunk]:
        if self._finished:
            return []
        if mode == "messages":
            return self._on_message_chunk(payload)
        if mode == "updates":
            return self._on_update(payload)
        return []

    # ------------------------------------------------------------------ messages (live text)
    def _on_message_chunk(self, payload: Any) -> list[Chunk]:
        try:
            message, metadata = payload
        except (TypeError, ValueError):
            return []
        if not isinstance(message, AIMessageChunk) or message.tool_call_chunks:
            return []
        if isinstance(metadata, dict) and metadata.get("langgraph_node") not in (None, "model"):
            return []
        text = message_text(message)
        if not text:
            return []
        if message.id:
            self._streamed_ids.add(message.id)
        return self._append_text(text)

    # ------------------------------------------------------------------ updates (tools, fallback)
    def _on_update(self, payload: Any) -> list[Chunk]:
        out: list[Chunk] = []
        if not isinstance(payload, dict):
            return out
        for node, node_update in payload.items():
            if node == INTERRUPT_KEY:
                out.extend(self._on_interrupts(node_update))
                continue
            messages = node_update.get("messages") if isinstance(node_update, dict) else None
            if not isinstance(messages, list):
                continue
            for message in messages:
                if isinstance(message, AIMessage):
                    out.extend(self._on_ai_message(message))
                elif isinstance(message, ToolMessage):
                    out.extend(self._on_tool_message(message))
        return out

    def _on_ai_message(self, message: AIMessage) -> list[Chunk]:
        out: list[Chunk] = []
        text = message_text(message).strip()
        if text and not message.tool_calls and (message.id not in self._streamed_ids):
            out.extend(self._append_text(text))  # provider did not stream it live
        # A call whose arguments the model garbled or cut off (long file contents hit the output
        # limit) is an `invalid_tool_call`, not a `tool_call`. It still gets an error result
        # later, so it must be announced too or the browser rejects that result as an orphan.
        for call in (*message.tool_calls, *message.invalid_tool_calls):
            call_id = call.get("id") or ""
            if not call_id or call_id in self._tool_inputs:
                continue
            args = call.get("args")
            args = args if isinstance(args, dict) else {}  # invalid calls carry raw text instead
            name = call.get("name") or "tool"
            out.extend(self._announce_call(call_id, name, args))
            if name == TODO_TOOL and isinstance(args.get("todos"), list):
                out.append({"type": "data-todos", "id": "todos", "data": {"todos": args["todos"]}})
        return out

    def _announce_call(self, call_id: str, name: str, args: dict[str, Any]) -> list[Chunk]:
        self._tool_inputs.add(call_id)
        out = self._close_text()
        self.final_text = ""  # text before a tool call is narration, not the answer
        out.append({"type": "tool-input-start", "toolCallId": call_id, "toolName": name})
        out.append(
            {
                "type": "tool-input-available",
                "toolCallId": call_id,
                "toolName": name,
                "input": args,
            }
        )
        return out

    def _on_tool_message(self, message: ToolMessage) -> list[Chunk]:
        call_id = message.tool_call_id
        if not call_id or call_id in self._tool_outputs:
            return []
        out: list[Chunk] = []
        # Safety net: a result is only valid after its call. LangGraph middleware can add results
        # for calls this adapter never saw (for example patched-in "cancelled" messages), and the
        # browser throws on such a result. A resumed run is exempt: its calls were announced in
        # the request before the pause, and re-announcing them would reset the approval card.
        if call_id not in self._tool_inputs and not self._continuing:
            out.extend(self._announce_call(call_id, message.name or "tool", {}))
        self._tool_outputs.add(call_id)
        if call_id in self._denied:
            return [*out, {"type": "tool-output-denied", "toolCallId": call_id}]
        text = clip(message_text(message))
        if getattr(message, "status", "success") == "error":
            return [*out, {"type": "tool-output-error", "toolCallId": call_id, "errorText": text}]
        return [*out, {"type": "tool-output-available", "toolCallId": call_id, "output": text}]

    def _on_interrupts(self, interrupts: Any) -> list[Chunk]:
        """A paused run: one approval request per gated tool call (see app/agent/approvals.py)."""
        out: list[Chunk] = []
        for item in interrupts if isinstance(interrupts, (list, tuple)) else ():
            value = getattr(item, "value", None)
            approval_id = str(getattr(item, "id", "") or "")
            if not isinstance(value, dict) or value.get("type") != "tool_approval":
                continue
            call_id = str(value.get("tool_call_id") or "")
            if not approval_id or not call_id or approval_id in self._approvals:
                continue
            self._approvals.add(approval_id)
            self.interrupts_sent.append(item)
            out.extend(self._close_text())
            if call_id not in self._tool_inputs:  # never shown (should not happen): show it now
                self._tool_inputs.add(call_id)
                name = str(value.get("name", "tool"))
                out.append({"type": "tool-input-start", "toolCallId": call_id, "toolName": name})
                out.append(
                    {
                        "type": "tool-input-available",
                        "toolCallId": call_id,
                        "toolName": name,
                        "input": value.get("args") or {},
                    }
                )
            chunk: Chunk = {
                "type": "tool-approval-request",
                "approvalId": approval_id,
                "toolCallId": call_id,
            }
            if value.get("description"):
                chunk["reason"] = str(value["description"])
            out.append(chunk)
        return out

    # ------------------------------------------------------------------ text helpers
    def _append_text(self, text: str) -> list[Chunk]:
        out: list[Chunk] = []
        if self._open_text is None:
            self._text_seq += 1
            self._open_text = f"text-{self._text_seq}"
            out.append({"type": "text-start", "id": self._open_text})
        out.append({"type": "text-delta", "id": self._open_text, "delta": text})
        self.final_text += text
        return out

    def _close_text(self) -> list[Chunk]:
        if self._open_text is None:
            return []
        chunk = {"type": "text-end", "id": self._open_text}
        self._open_text = None
        return [chunk]


def coalesce(chunks: list[Chunk]) -> list[Chunk]:
    """Merge consecutive text/reasoning deltas of the same part so stored runs stay small.

    Replaying the coalesced list builds exactly the same message as the original stream.
    """
    merged: list[Chunk] = []
    for chunk in chunks:
        if (
            chunk.get("type") in ("text-delta", "reasoning-delta")
            and merged
            and merged[-1].get("type") == chunk["type"]
            and merged[-1].get("id") == chunk.get("id")
        ):
            merged[-1] = {**merged[-1], "delta": merged[-1]["delta"] + chunk["delta"]}
        else:
            merged.append(chunk)
    return merged


def to_sse(chunk: Chunk) -> str:
    """One Server-Sent Event line for a chunk."""
    return f"data: {json.dumps(chunk, separators=(',', ':'), ensure_ascii=False, default=str)}\n\n"


SSE_DONE = "data: [DONE]\n\n"
SSE_HEARTBEAT = (
    ": ping\n\n"  # comment line: keeps proxies/load balancers from closing an idle stream
)
