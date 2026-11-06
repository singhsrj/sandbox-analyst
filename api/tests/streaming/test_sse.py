from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.streaming.sse import SSE_HEADERS, sse_stream


async def gen(items: list[Any], delay: float = 0.0) -> AsyncIterator[dict[str, Any]]:
    for item in items:
        if delay:
            await asyncio.sleep(delay)
        if isinstance(item, BaseException):
            raise item
        yield item


async def collect(stream: AsyncIterator[str]) -> list[str]:
    return [frame async for frame in stream]


async def test_frames_then_done() -> None:
    frames = await collect(sse_stream(gen([{"type": "start"}, {"type": "finish"}])))
    assert frames == [
        'data: {"type":"start"}\n\n',
        'data: {"type":"finish"}\n\n',
        "data: [DONE]\n\n",
    ]


async def test_heartbeats_fill_quiet_periods_without_losing_chunks() -> None:
    frames = await collect(
        sse_stream(gen([{"type": "a"}, {"type": "b"}], delay=0.15), heartbeat_seconds=0.04)
    )
    pings = [f for f in frames if f.startswith(":")]
    chunks = [json.loads(f[6:])["type"] for f in frames if f.startswith("data: {")]
    assert len(pings) >= 3 and chunks == ["a", "b"] and frames[-1] == "data: [DONE]\n\n"


async def test_a_crashing_source_becomes_an_error_chunk_and_still_terminates() -> None:
    frames = await collect(sse_stream(gen([{"type": "start"}, RuntimeError("secret detail")])))
    assert frames[-1] == "data: [DONE]\n\n"
    error = json.loads(frames[-2][6:])
    assert error["type"] == "error" and "secret detail" not in error["errorText"]


async def test_closing_the_stream_closes_the_source() -> None:
    closed = asyncio.Event()

    async def source() -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"type": "start"}
            await asyncio.sleep(3600)
        finally:
            closed.set()

    stream = sse_stream(source(), heartbeat_seconds=0.05)
    task = asyncio.create_task(collect(stream))
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.wait_for(closed.wait(), timeout=2)


def test_required_header_for_custom_backends() -> None:
    assert SSE_HEADERS["x-vercel-ai-ui-message-stream"] == "v1"
    assert SSE_HEADERS["X-Accel-Buffering"] == "no"
