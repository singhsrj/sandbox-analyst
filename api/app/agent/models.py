"""The ONE place that knows which provider serves the model.

Everything else calls `get_model()`; swapping provider or model is an env-var change.
All three providers speak the OpenAI chat-completions protocol:
  * bedrock-openai: Amazon Bedrock's OpenAI-compatible endpoint (production + evals)
  * groq:           Groq (dev/CI smoke only, free tier is heavily rate-limited)
  * ollama:         local models (optional dev fallback; slow/unreliable with Deep Agents)
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config import ModelProvider, Settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def get_model(
    settings: Settings,
    *,
    provider: ModelProvider | None = None,
    model: str | None = None,
) -> BaseChatModel:
    provider = provider or settings.model_provider
    model = model or settings.model

    if provider == "bedrock-openai":
        settings.require("bedrock_base_url")
        return ChatOpenAI(
            model=model,
            api_key=SecretStr(settings.secret("bedrock_api_key")),
            base_url=_clean_url(settings.bedrock_base_url),
            temperature=0,
            # Streamed responses carry no token usage unless asked. Without it the token budget
            # and cost accounting silently see zero (found in M3 live testing).
            stream_usage=True,
            timeout=120,
            max_retries=2,
        )
    if provider == "groq":
        return ChatOpenAI(
            model=model,
            api_key=SecretStr(settings.secret("groq_api_key")),
            base_url=GROQ_BASE_URL,
            temperature=0,
            # Streamed responses carry no token usage unless asked. Without it the token budget
            # and cost accounting silently see zero (found in M3 live testing).
            stream_usage=True,
            timeout=120,
            max_retries=2,
        )
    if provider == "ollama":
        return ChatOpenAI(
            model=model,
            api_key=SecretStr("ollama"),
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            temperature=0,
            # Streamed responses carry no token usage unless asked. Without it the token budget
            # and cost accounting silently see zero (found in M3 live testing).
            stream_usage=True,
            timeout=300,
            max_retries=0,
        )
    raise ValueError(f"Unknown model provider: {provider}")  # pragma: no cover


def _clean_url(url: str | None) -> str:
    return (url or "").strip().strip("'\"").rstrip("/")
