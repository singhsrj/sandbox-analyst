"""Langfuse tracing. Optional: the app runs (untraced) when no keys are configured.

The Langfuse SDK reads credentials from real environment variables, but our settings come from
.env via pydantic, so we construct the client explicitly. Secrets are never logged.
"""

from __future__ import annotations

import logging

from langfuse import Langfuse
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
