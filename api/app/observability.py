"""Langfuse tracing. Optional: the app runs (untraced) when no keys are configured.

The Langfuse SDK reads credentials from real environment variables, but our settings come from
.env via pydantic, so we construct the client explicitly. Secrets are never logged.
"""

from __future__ import annotations

import logging

from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

from app.config import Settings

logger = logging.getLogger(__name__)


def tracing_enabled(settings: Settings) -> bool:
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def init_langfuse(settings: Settings) -> Langfuse | None:
    if not tracing_enabled(settings):
        logger.warning("Langfuse keys not set: tracing disabled")
        return None
    return Langfuse(
        public_key=settings.secret("langfuse_public_key"),
        secret_key=settings.secret("langfuse_secret_key"),
        base_url=settings.langfuse_base_url,
    )


def make_handler(settings: Settings) -> CallbackHandler | None:
    if init_langfuse(settings) is None:
        return None
    return CallbackHandler(public_key=settings.secret("langfuse_public_key"))


def finalize_trace(
    handler: CallbackHandler | None, settings: Settings
) -> tuple[str | None, str | None]:
    """Flush the trace and return `(trace_id, trace_url)`; both None when tracing is off."""
    if handler is None or not tracing_enabled(settings):
        return None, None
    try:
        client = get_client(public_key=settings.secret("langfuse_public_key"))
        trace_id = handler.last_trace_id
        client.flush()
        url = client.get_trace_url(trace_id=trace_id) if trace_id else None
        return trace_id, url
    except Exception:  # tracing problems must never break a user's run
        logger.exception("could not finalize Langfuse trace")
        return None, None
