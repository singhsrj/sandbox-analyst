"""Clerk session-token verification and the access-code check (ADR-028)."""

from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import AuthError, ClerkVerifier, code_is_valid
from app.config import Settings
from tests.helpers import ISSUER, WEB_ORIGIN, clerk_keys, clerk_token, make_settings


def settings(**extra: str) -> Settings:
    values = {"CLERK_ISSUER": ISSUER, "CORS_ALLOW_ORIGINS": WEB_ORIGIN, **extra}
    return make_settings(DEMO_ACCESS_CODE="open-sesame", **values)


def verifier(**extra: str) -> ClerkVerifier:
    return ClerkVerifier(settings(**extra), keys=clerk_keys())


async def test_a_valid_token_names_the_clerk_user() -> None:
    identity = await verifier().verify(clerk_token("user_abc123"))
    assert identity.provider_sub == "user_abc123"
    assert identity.expires_at > time.time()


@pytest.mark.parametrize(
    ("why", "token"),
    [
        ("expired", lambda: clerk_token(now=time.time() - 3600)),
        ("not yet valid", lambda: clerk_token(nbf=int(time.time()) + 600)),
        ("another issuer", lambda: clerk_token(iss="https://evil.clerk.accounts.dev")),
        ("another origin", lambda: clerk_token(azp="https://evil.example")),
        ("no origin", lambda: clerk_token(azp=None)),
        ("no subject", lambda: clerk_token(sub=None)),  # type: ignore[arg-type]
        ("bad subject", lambda: clerk_token("user/../../etc")),
        (
            "signed by another key",
            lambda: clerk_token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        ),
        ("junk", lambda: "not.a.jwt"),
    ],
)
async def test_bad_tokens_are_rejected(why: str, token: object) -> None:
    with pytest.raises(AuthError):
        await verifier().verify(token())  # type: ignore[operator]


async def test_hs256_token_is_rejected() -> None:
    """Algorithm confusion: a token 'signed' with HMAC must never pass the RS256 check."""
    import jwt

    now = int(time.time())
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "user_x",
            "azp": WEB_ORIGIN,
            "iat": now,
            "nbf": now,
            "exp": now + 60,
        },
        "s" * 64,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        await verifier().verify(forged)


async def test_authorized_parties_default_to_cors_origins_and_can_be_set() -> None:
    other = "https://sandbox-analyst.vercel.app"
    with pytest.raises(AuthError):
        await verifier().verify(clerk_token(azp=other))
    custom = verifier(CLERK_AUTHORIZED_PARTIES=f"{WEB_ORIGIN},{other}")
    assert (await custom.verify(clerk_token(azp=other))).provider_sub == "user_test1"


def test_issuer_must_be_https() -> None:
    with pytest.raises(RuntimeError):
        ClerkVerifier(settings(CLERK_ISSUER="http://test.clerk.accounts.dev"), keys=clerk_keys())


def test_access_code_check() -> None:
    s = settings()
    assert code_is_valid(s, "open-sesame")
    assert not code_is_valid(s, "open-sesame ") and not code_is_valid(s, "")
    assert not code_is_valid(s, "OPEN-SESAME")


def test_no_configured_code_means_nobody_gets_in() -> None:
    unconfigured = make_settings()
    assert not code_is_valid(unconfigured, "")
    assert not code_is_valid(unconfigured, "anything")
