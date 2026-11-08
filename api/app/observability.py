"""Langfuse tracing. Optional: the app runs (untraced) when no keys are configured.

The Langfuse SDK reads credentials from real environment variables, but our settings come from
.env via pydantic, so we construct the client explicitly. Secrets are never logged.
"""

from __future__ import annotations

import logging

from langfuse import Langfuse, LangfuseSpan, get_client
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
    public_key = settings.secret("langfuse_public_key")
    if not settings.langfuse_public_traces:
        return CallbackHandler(public_key=public_key)
    # Public traces: the run is nested under a root span so finalize_trace can attach the
    # "publish" marker to it (see publish_trace) and keep one root, named after the app.
    root = get_client(public_key=public_key).start_observation(name="sandbox-analyst")
    handler = CallbackHandler(
        public_key=public_key,
        trace_context={"trace_id": root.trace_id, "parent_span_id": root.id},
    )
    handler.public_root = root  # type: ignore[attr-defined]
    return handler


def publish_trace(root: LangfuseSpan) -> None:
    """Make the trace public: anyone with its link can open it without logging in.

    Langfuse takes the trace's public flag from its most recently started span, and every span of
    the run is created non-public, so the flag goes on a short marker span started last.
    """
    marker = root.start_observation(name="publish-trace", as_type="span")
    marker.set_trace_as_public()
    marker.end()


def finalize_trace(
    handler: CallbackHandler | None, settings: Settings
) -> tuple[str | None, str | None]:
    """Flush the trace and return `(trace_id, trace_url)`; both None when tracing is off."""
    if handler is None or not tracing_enabled(settings):
        return None, None
    try:
        client = get_client(public_key=settings.secret("langfuse_public_key"))
        trace_id = handler.last_trace_id
        root = getattr(handler, "public_root", None)
        if root is not None:
            publish_trace(root)
            root.end()
        client.flush()
        url = client.get_trace_url(trace_id=trace_id) if trace_id else None
        return trace_id, url
    except Exception:  # tracing problems must never break a user's run
        logger.exception("could not finalize Langfuse trace")
        return None, None
