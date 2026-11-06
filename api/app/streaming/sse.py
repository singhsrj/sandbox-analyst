"""Wrap a chunk generator as an SSE text stream with heartbeats and a guaranteed terminator."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.streaming.adapter import SSE_DONE, SSE_HEARTBEAT, Chunk, to_sse

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",  # required by the AI SDK client for custom backends
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # stop nginx/Caddy-style proxies from buffering the stream
}


async def sse_stream(
    chunks: AsyncIterator[Chunk], heartbeat_seconds: float = 15.0
) -> AsyncIterator[str]:
    """Yield `data: ...` frames, a `: ping` comment whenever the source is quiet, then `[DONE]`.

    Model calls can take tens of seconds without producing an event; load balancers commonly
    close connections that are idle for 30-60 s, so we keep the line warm. The pending read is
    kept alive across heartbeats (never cancelled), so no chunk can be lost.
    """
    iterator = chunks.__aiter__()
    pending: asyncio.Task[Chunk] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if not done:
                yield SSE_HEARTBEAT
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                break
            finally:
                pending = None
            yield to_sse(chunk)
    except Exception:  # the service reports run errors itself; this is a last line of defence
        logger.exception("unexpected error while streaming")
        yield to_sse({"type": "error", "errorText": "The stream failed unexpectedly."})
    finally:
        if pending is not None and not pending.done():
            pending.cancel()  # client went away: stop the run
            await asyncio.gather(pending, return_exceptions=True)
        await _aclose(iterator)
    yield SSE_DONE


async def _aclose(iterator: AsyncIterator[Chunk]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception:
            logger.exception("error closing chunk generator")
