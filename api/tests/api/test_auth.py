from __future__ import annotations

import base64
import json

import pytest

from app.auth import (
    AuthError,
    code_is_valid,
    issue_token,
    normalize_client_id,
    verify_token,
)
from app.config import Settings
from tests.helpers import make_settings

SECRET = "s" * 40


def settings(**extra: str) -> Settings:
    return make_settings(DEMO_ACCESS_CODE="open-sesame", SESSION_TOKEN_SECRET=SECRET, **extra)


def test_a_fresh_token_verifies_and_carries_the_owner() -> None:
    token, expires_at = issue_token(settings(), "client-abc-123", now=1_000)
    session = verify_token(settings(), token, now=1_001)
    assert session.owner_id == "client-abc-123" and session.expires_at == expires_at


def test_token_expires_exactly_at_the_ttl() -> None:
    s = settings(SESSION_TOKEN_TTL_MINUTES="10")
    token, expires_at = issue_token(s, "client-abc-123", now=0)
    assert expires_at == 600
    verify_token(s, token, now=599)
    with pytest.raises(AuthError, match="expired"):
        verify_token(s, token, now=600)


def test_tampered_payload_or_signature_is_rejected() -> None:
    token, _ = issue_token(settings(), "client-abc-123", now=0)
    body, signature = token.split(".")
    forged_payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "someone-else-1", "exp": 9_999_999_999}).encode()
    ).rstrip(b"=")
    for bad in (f"{forged_payload.decode()}.{signature}", f"{body}.AAAA", f"{body}.", body):
        with pytest.raises(AuthError):
            verify_token(settings(), bad, now=1)


def test_token_signed_with_another_secret_is_rejected() -> None:
    other = make_settings(SESSION_TOKEN_SECRET="x" * 40)
    token, _ = issue_token(other, "client-abc-123", now=0)
    with pytest.raises(AuthError):
        verify_token(settings(), token, now=1)


@pytest.mark.parametrize("token", [None, "", "garbage", "a.b.c", "....", "é.é"])
def test_garbage_tokens_never_raise_anything_but_autherror(token: str | None) -> None:
    with pytest.raises(AuthError):
        verify_token(settings(), token)


def test_access_code_check() -> None:
    s = settings()
    assert code_is_valid(s, "open-sesame")
    assert not code_is_valid(s, "open-sesame ") and not code_is_valid(s, "")
    assert not code_is_valid(s, "OPEN-SESAME")


def test_no_configured_code_means_nobody_gets_in() -> None:
    unconfigured = make_settings()
    assert not code_is_valid(unconfigured, "")
    assert not code_is_valid(unconfigured, "anything")


def test_client_ids_are_validated_or_replaced() -> None:
    assert normalize_client_id("abcdef123456") == "abcdef123456"
    for bad in (None, "", "short", "has spaces in it", "../../etc", "x" * 100):
        generated = normalize_client_id(bad)
        assert generated != bad and len(generated) == 32
