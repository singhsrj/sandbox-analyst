"""Command line interface: ask one question, watch the agent work, get the report.

uv run python -m app.cli "Why did revenue drop in March 2025, and which regions were affected?"
uv run python -m app.cli --model qwen.qwen3-235b-a22b-2507 "..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.agent.runner import RunRecord, run_question
from app.config import get_settings


def _print_event(event: dict[str, Any]) -> None:
    kind = event["type"]
    if kind == "tool_call":
        args = json.dumps(event["args"], default=str)
        print(f"\n> {event['name']}  {args[:300]}{'…' if len(args) > 300 else ''}", flush=True)
    elif kind == "tool_result":
        text = str(event["text"]).replace("\n", "\n    ")
        print(f"    {text[:500]}{'…' if len(text) > 500 else ''}", flush=True)
    elif kind == "assistant":
        print("\n[assistant] final answer ready", flush=True)


def _print_summary(record: RunRecord) -> None:
    u = record.usage
    cost = (
        "unknown (no verified price configured)"
        if u.get("cost_usd") is None
        else f"${u['cost_usd']:.4f}"
    )
    print("\n" + "=" * 78)
    print(f"status   : {record.status}" + (f"  ({record.error})" if record.error else ""))
    print(f"model    : {record.provider} / {', '.join(u.get('models') or [record.model])}")
    print(
        f"usage    : {u.get('llm_calls', 0)} model calls, {u.get('input_tokens', 0):,} in / "
        f"{u.get('output_tokens', 0):,} out tokens, cost {cost}"
    )
    print(
        f"time     : {record.seconds}s   steps: {len(record.steps)}   "
        f"sql queries: {len(record.sql)}"
    )
    for a in record.artifacts:
        print(f"artifact : {a['path']} ({a['size']:,} bytes)")
    if record.unverified_file_claims:
        print(
            "WARNING  : answer mentions files that were never delivered: "
            f"{record.unverified_file_claims}"
        )
    if record.empty_reply_nudges:
        print(f"note     : model ended its turn empty {record.empty_reply_nudges}x and was nudged")
    print(f"trace    : {record.trace_url or '(tracing disabled)'}")


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Ask the SandboxAnalyst agent a question.")
    parser.add_argument("question")
    parser.add_argument("--model", help="override MODEL (an id served by the provider)")
    parser.add_argument("--provider", choices=["bedrock-openai", "groq", "ollama"])
    parser.add_argument("--thread", help="thread id (default: random)")
    args = parser.parse_args()

    settings = get_settings()
    record = await run_question(
        args.question,
        settings,
        provider=args.provider,
        model=args.model,
        thread_id=args.thread,
        on_event=_print_event,
    )
    out_dir = settings.artifacts_dir / record.thread_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.json").write_text(record.to_json(), encoding="utf-8")

    print("\n" + "=" * 78 + "\nFINAL ANSWER\n" + "=" * 78)
    print(record.final_answer or "(no answer produced)")
    _print_summary(record)
    print(f"run record: {out_dir / 'run.json'}")
    return 0 if record.status == "ok" else 1


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
