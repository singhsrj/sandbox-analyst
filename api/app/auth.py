"""Accounts (ADR-028): Clerk session tokens, verified here; plus the demo access code.

Flow: the browser signs in with Clerk and sends its short-lived session token (a JWT) as
`Authorization: Bearer <token>` (ADR-006: no cross-site cookies). We verify it ourselves against
the public keys at `<CLERK_ISSUER>/.well-known/jwks.json`: RS256 signature, `iss`, `exp`/`nbf`,
and `azp` (the web origin that requested it; Clerk's recommended CSRF protection). The Clerk user
id (`sub`) is mapped to our own user id in `app.users` (app/db/app_store.py), and that id owns the
user's threads, so switching providers later does not orphan anyone's history.

Signing in says WHO someone is. Running live questions costs model tokens, so it additionally
needs the demo access code, entered once per account (`live_access`).
"""

from __future__ import annotations

import asyncio
import hmac
import re
from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from app.config import Settings

LEEWAY_SECONDS = 5  # clock skew between Clerk and this server
_CLERK_SUB = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class AuthError(Exception):
    """Missing, malformed, tampered, expired or foreign credentials."""


@dataclass(frozen=True)
class Identity:
    """A verified Clerk session: who signed in (not yet mapped to our user id)."""

    provider_sub: str
    expires_at: int


@dataclass(frozen=True)
class Session:
    owner_id: str  # our user id; owns threads, runs and the usage budget
    expires_at: int
    live_access: bool  # has entered the access code


class SigningKeys(Protocol):
    """Finds the public key for a token (PyJWKClient in production, a fixed key in tests)."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class ClerkVerifier:
    def __init__(self, settings: Settings, keys: SigningKeys | None = None) -> None:
        issuer = (settings.clerk_issuer or "").strip().rstrip("/")
        if not issuer.startswith("https://"):
            raise RuntimeError("CLERK_ISSUER must be the https:// Frontend API URL")
        self.issuer = issuer
        self.authorized_parties = frozenset(settings.authorized_parties)
        # PyJWKClient caches the key set and refetches on an unknown key id (key rotation).
        self._keys = keys or jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", lifespan=3600)

    async def verify(self, token: str) -> Identity:
        try:
            # The key lookup may fetch the JWKS over the network; keep it off the event loop.
            signing_key = await asyncio.to_thread(self._keys.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                key=getattr(signing_key, "key", signing_key),
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "nbf", "iat", "iss", "sub"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from exc
        # Required, not optional: every browser session token carries `azp`, and a token minted
        # for another origin must not work here.
        if claims.get("azp") not in self.authorized_parties:
            raise AuthError("token was issued to another origin")
        sub = str(claims["sub"])
        if not _CLERK_SUB.match(sub):
            raise AuthError("malformed subject")
        return Identity(provider_sub=sub, expires_at=int(claims["exp"]))


def code_is_valid(settings: Settings, supplied: str) -> bool:
    """Constant-time access-code check. Fails closed if no code is configured."""
    configured = settings.demo_access_code
    if configured is None or not configured.get_secret_value() or not supplied:
        return False
    return hmac.compare_digest(supplied.encode(), configured.get_secret_value().encode())
