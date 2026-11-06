"""Application settings, loaded from environment variables (and `.env` in local dev).

Every variable is documented in `.env.example`. Secrets are `SecretStr` so they are
masked in reprs/logs; call `.get_secret_value()` only at the point of use.

Most secrets are optional here so the app can boot (e.g. `/api/health`) without them;
each subsystem validates what it needs when it is first used (see `require()`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

ModelProvider = Literal["bedrock-openai", "groq", "ollama"]
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        populate_by_name=True,
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        protected_namespaces=(),  # allow fields named model / model_provider
    )

    # --- app ---
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    cors_allow_origins: CsvList = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- models ---
    model_provider: ModelProvider = "bedrock-openai"
    model: str = "openai.gpt-oss-120b"
    fallback_models: CsvList = Field(default_factory=list)
    allowed_models: CsvList = Field(default_factory=list)  # extra model ids users may select
    judge_provider: ModelProvider = "bedrock-openai"
    judge_model: str = "openai.gpt-oss-120b"

    # Bedrock's OpenAI-compatible endpoint (https://bedrock-mantle.<region>.api.aws/v1). The
    # standard OPENAI_* names are accepted because that is what the OpenAI SDK itself reads.
    aws_region: str = "ap-south-1"
    bedrock_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "BEDROCK_OPENAI_API_KEY")
    )
    bedrock_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_BASE_URL", "BEDROCK_OPENAI_BASE_URL")
    )
    groq_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- database (Neon) ---
    analyst_database_url: SecretStr | None = None  # pooled, role analyst_ro (agent SQL only)
    app_database_url: SecretStr | None = None  # direct, app role (threads, checkpoints)
    admin_database_url: SecretStr | None = None  # direct, app_admin (migrations/seed only)

    # --- sandbox (E2B) ---
    e2b_api_key: SecretStr | None = None
    sandbox_timeout_seconds: int = Field(default=600, ge=30, le=3600)
    sandbox_template: str = "code-interpreter-v1"  # has pandas/matplotlib; no pip needed
    sandbox_command_timeout_seconds: int = Field(default=120, ge=5, le=600)
    sandbox_idle_seconds: int = Field(default=300, ge=30)  # reaper kills sandboxes idle this long

    artifacts_dir: Path = REPO_ROOT / "runs"  # sandbox deliverables + saved run records

    # --- observability (Langfuse) ---
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"

    # --- auth / access code ---
    demo_access_code: SecretStr | None = None
    session_token_secret: SecretStr | None = None
    session_token_ttl_minutes: int = Field(default=120, ge=5)

    # --- limits & budgets ---
    max_agent_steps: int = Field(default=40, ge=1)  # max MODEL CALLS per request
    sql_max_rows: int = Field(default=10_000, ge=1)
    sql_statement_timeout_ms: int = Field(default=15_000, ge=100)
    tool_preview_rows: int = Field(default=5, ge=1, le=50)
    max_tool_output_chars: int = Field(default=4_000, ge=200)
    max_tokens_per_request: int = Field(default=300_000, ge=1_000)
    max_cost_usd_per_request: float = Field(default=0.10, gt=0)
    max_cost_usd_per_session: float = Field(default=0.50, gt=0)
    rate_limit_per_minute: int = Field(default=10, ge=1)
    login_attempts_per_minute: int = Field(default=5, ge=1)
    max_concurrent_runs: int = Field(default=3, ge=1)
    max_question_chars: int = Field(default=2_000, ge=10)

    @field_validator("cors_allow_origins", "fallback_models", "allowed_models", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def require(self, *names: str) -> None:
        """Raise a clear error if any of the named settings is missing or empty."""
        missing = [n for n in names if getattr(self, n) in (None, "")]
        if missing:
            env_names = ", ".join(n.upper() for n in missing)
            raise RuntimeError(f"Missing required configuration: {env_names} (see .env.example)")

    def secret(self, name: str) -> str:
        """Return the plain value of a required secret setting (raises if it is missing)."""
        self.require(name)
        value = getattr(self, name)
        return value.get_secret_value() if isinstance(value, SecretStr) else str(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
