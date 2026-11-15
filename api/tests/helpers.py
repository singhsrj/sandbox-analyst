"""Small helpers shared by tests."""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from app.config import Settings


def make_settings(**values: Any) -> Settings:
    """Settings built only from the given values (never from a developer's .env)."""
    return Settings(_env_file=None, **values)


# --------------------------------------------------------------------------- Clerk tokens
ISSUER = "https://test-app.clerk.accounts.dev"
WEB_ORIGIN = "http://localhost:3000"


class StaticKeys:
    """Stands in for PyJWKClient: always the test key pair's public half."""

    def __init__(self, public_key: Any) -> None:
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return self.public_key


@lru_cache
def _key_pair() -> Any:
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def clerk_keys() -> StaticKeys:
    return StaticKeys(_key_pair().public_key())


def clerk_token(
    sub: str = "user_test1", *, now: float | None = None, key: Any = None, **claims: Any
) -> str:
    """A Clerk-shaped session token signed with the test key (or `key`)."""
    import jwt

    issued = int(now if now is not None else time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": sub,
        "azp": WEB_ORIGIN,
        "iat": issued,
        "nbf": issued - 1,
        "exp": issued + 60,
        **claims,
    }
    payload = {k: v for k, v in payload.items() if v is not None}  # claims=None removes one
    return jwt.encode(payload, key or _key_pair(), algorithm="RS256")
