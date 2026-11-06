"""Access-code login and short-lived signed bearer tokens (ADR-006: no cross-site cookies).

Flow: the visitor enters the demo access code -> POST /api/session -> we return a token that the
browser sends as `Authorization: Bearer <token>`. The token is `base64url(payload).base64url(hmac)`
with payload `{"sub": <client id>, "exp": <unix seconds>}`, signed with SESSION_TOKEN_SECRET.
`sub` is a random id the browser keeps (it owns that visitor's threads); it is an identifier,
not a credential: access always requires a valid, unexpired token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from dataclasses import dataclass

from app.config import Settings

_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class AuthError(Exception):
    """Missing, malformed, tampered or expired credentials."""


@dataclass(frozen=True)
class Session:
    owner_id: str
    expires_at: int


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def code_is_valid(settings: Settings, supplied: str) -> bool:
    """Constant-time access-code check. Fails closed if no code is configured."""
    configured = settings.demo_access_code
    if configured is None or not configured.get_secret_value() or not supplied:
        return False
    return hmac.compare_digest(supplied.encode(), configured.get_secret_value().encode())


def normalize_client_id(client_id: str | None) -> str:
    if client_id and _CLIENT_ID.match(client_id):
        return client_id
    return uuid.uuid4().hex


def issue_token(settings: Settings, owner_id: str, *, now: float | None = None) -> tuple[str, int]:
    expires_at = int(
        (now if now is not None else time.time()) + settings.session_token_ttl_minutes * 60
    )
    body = _b64(json.dumps({"sub": owner_id, "exp": expires_at}, separators=(",", ":")).encode())
    return f"{body}.{_sign(settings.secret('session_token_secret'), body)}", expires_at


def verify_token(settings: Settings, token: str | None, *, now: float | None = None) -> Session:
    if not token:
        raise AuthError("missing token")
    try:
        body, signature = token.split(".", 1)
        expected = _sign(settings.secret("session_token_secret"), body)
        if not hmac.compare_digest(signature, expected):
            raise AuthError("bad signature")
        payload = json.loads(_unb64(body))
        owner, expires_at = str(payload["sub"]), int(payload["exp"])
    except AuthError:
        raise
    except Exception as exc:  # malformed base64/json/fields: treat all as an invalid token
        raise AuthError("malformed token") from exc
    if (now if now is not None else time.time()) >= expires_at:
        raise AuthError("expired token")
    if not _CLIENT_ID.match(owner):
        raise AuthError("malformed token")
    return Session(owner_id=owner, expires_at=expires_at)
