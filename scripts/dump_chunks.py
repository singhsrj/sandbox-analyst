"""Write the UI-stream chunks our adapter produces to web/test-fixtures/chunks.json.

The web contract test validates every chunk against the installed `ai` package's own schema, so
a protocol drift between the Python backend and the AI SDK fails in CI instead of in the browser.

Run: uv run python scripts/dump_chunks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "api")]

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

from app.streaming.adapter import UIStreamAdapter, coalesce  # noqa: E402
from tests.fakes import recorded_events  # noqa: E402

# Must have exactly the keys ChatService._finish puts in `run_data` (checked by a backend test).
RUN_DATA = {
    "status": "ok",
    "model": "openai.gpt-oss-120b",
    "provider": "bedrock-openai",
    "usage": {
        "llm_calls": 6,
        "input_tokens": 41000,
        "output_tokens": 900,
        "total_tokens": 41900,
        "models": ["openai.gpt-oss-120b"],
        "cost_usd": None,
        "calls_without_usage": 0,
    },
    "seconds": 29.1,
    "trace_url": None,
    "empty_reply_nudges": 0,
    "unverified_file_claims": [],
    "sql_queries": 1,
}


def replay(events: list[tuple[str, object]], error: str | None = None) -> list[dict[str, object]]:
    adapter = UIStreamAdapter("msg-contract")
    chunks = adapter.start()
    for mode, payload in events:
        chunks.extend(adapter.feed(mode, payload))
    data_parts = [
        {
            "type": "data-artifacts",
            "id": "artifacts",
            "data": {
                "items": [
                    {
                        "name": "chart.png",
                        "mime": "image/png",
                        "size": 1234,
                        "url": "/api/threads/t/artifacts/chart.png",
                    }
                ]
            },
        },
        {"type": "data-run", "id": "run", "data": RUN_DATA},
    ]
    chunks.extend(adapter.finish(error=error, data_parts=data_parts))
    return chunks


def main() -> None:
    real = replay(recorded_events())
    call = AIMessage(
        content="", tool_calls=[{"name": "execute", "args": {"command": "x"}, "id": "c-err"}]
    )
    failed = ToolMessage("Traceback: boom", tool_call_id="c-err", name="execute", status="error")
    edge = replay(
        [
            ("updates", {"model": {"messages": [call]}}),
            ("updates", {"tools": {"messages": [failed]}}),
        ],
        error="The run failed (RuntimeError).",
    )
    out = {"real_run": real, "real_run_coalesced": coalesce(real), "tool_error_run": edge}
    target = ROOT / "web" / "test-fixtures" / "chunks.json"
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {target} ({sum(len(v) for v in out.values())} chunks)")


if __name__ == "__main__":
    main()
