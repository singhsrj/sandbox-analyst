import pytest

from app.config import Settings

# Settings(_env_file=None): tests must not depend on a developer's local .env


def test_csv_env_values_become_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("FALLBACK_MODELS", "m1,m2")
    s = Settings(_env_file=None)
    assert s.cors_allow_origins == ["http://a.test", "http://b.test"]
    assert s.fallback_models == ["m1", "m2"]


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2B_API_KEY", "e2b_super_secret_value")
    s = Settings(_env_file=None)
    assert "e2b_super_secret_value" not in repr(s)
    assert "e2b_super_secret_value" not in str(s.model_dump())
    assert s.e2b_api_key is not None
    assert s.e2b_api_key.get_secret_value() == "e2b_super_secret_value"


def test_require_reports_missing_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    s = Settings(_env_file=None)
    with pytest.raises(RuntimeError, match="E2B_API_KEY"):
        s.require("e2b_api_key")


def test_invalid_provider_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    with pytest.raises(ValueError):
        Settings(_env_file=None)
