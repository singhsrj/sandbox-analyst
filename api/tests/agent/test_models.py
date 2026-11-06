from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI

from app.agent.models import GROQ_BASE_URL, get_model
from app.config import Settings
from tests.helpers import make_settings


def make(**env: str) -> Settings:
    return make_settings(**env)


def test_bedrock_uses_openai_compatible_endpoint_and_cleans_the_url() -> None:
    s = make(OPENAI_API_KEY="k", OPENAI_BASE_URL='"https://bedrock-mantle.ap-south-1.api.aws/v1/"')
    model = get_model(s)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "openai.gpt-oss-120b"
    assert str(model.openai_api_base) == "https://bedrock-mantle.ap-south-1.api.aws/v1"
    assert model.temperature == 0


def test_provider_and_model_come_from_settings_and_can_be_overridden() -> None:
    s = make(MODEL_PROVIDER="groq", MODEL="openai/gpt-oss-120b", GROQ_API_KEY="g")
    groq = get_model(s)
    assert isinstance(groq, ChatOpenAI) and str(groq.openai_api_base) == GROQ_BASE_URL
    other = get_model(s, provider="ollama", model="qwen3:4b")
    assert isinstance(other, ChatOpenAI) and other.model_name == "qwen3:4b"


def test_missing_credentials_fail_with_a_clear_message() -> None:
    with pytest.raises(RuntimeError, match="BASE_URL"):
        get_model(make(OPENAI_API_KEY="k"))
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        get_model(make(MODEL_PROVIDER="groq"))


def test_streamed_responses_request_token_usage_for_every_provider() -> None:
    """Regression (M3): without stream_usage the budget and usage stats silently read zero."""
    s = make(OPENAI_API_KEY="k", OPENAI_BASE_URL="https://x.example/v1", GROQ_API_KEY="g")
    for provider in ("bedrock-openai", "groq", "ollama"):
        model = get_model(s, provider=provider)
        assert isinstance(model, ChatOpenAI) and model.stream_usage is True
