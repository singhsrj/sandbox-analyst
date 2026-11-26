"""Password encryption at rest: round trip, and every way a ciphertext must fail to open."""

from __future__ import annotations

import base64
import secrets

import pytest

from app.security.secret_box import SecretBox, SecretBoxError, connection_context
from tests.helpers import make_settings


def _key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def test_round_trip_and_the_password_is_not_in_the_ciphertext() -> None:
    box = SecretBox.from_settings(make_settings(CONNECTION_ENCRYPTION_KEY=_key()))
    assert box is not None
    ctx = connection_context("c1", "u1")
    blob = box.seal("hunter2-very-secret", ctx)
    assert b"hunter2" not in blob
    assert box.open(blob, ctx, box.key_id) == "hunter2-very-secret"
    assert box.seal("same", ctx) != box.seal("same", ctx)  # fresh nonce every time


def test_a_ciphertext_only_opens_for_its_own_connection_and_owner() -> None:
    box = SecretBox(secrets.token_bytes(32))
    blob = box.seal("pw", connection_context("c1", "u1"))
    for other in (connection_context("c2", "u1"), connection_context("c1", "u2")):
        with pytest.raises(SecretBoxError):
            box.open(blob, other, box.key_id)


def test_tampering_and_a_different_key_are_detected() -> None:
    box = SecretBox(secrets.token_bytes(32))
    ctx = connection_context("c1", "u1")
    blob = bytearray(box.seal("pw", ctx))
    blob[-1] ^= 1
    with pytest.raises(SecretBoxError):
        box.open(bytes(blob), ctx, box.key_id)
    other = SecretBox(secrets.token_bytes(32))
    with pytest.raises(SecretBoxError, match="different encryption key"):
        other.open(box.seal("pw", ctx), ctx, box.key_id)


def test_the_feature_is_off_without_a_key_and_bad_keys_are_refused() -> None:
    assert SecretBox.from_settings(make_settings()) is None
    with pytest.raises(ValueError, match="32 bytes"):
        SecretBox.from_settings(
            make_settings(CONNECTION_ENCRYPTION_KEY=base64.b64encode(b"short").decode())
        )
    with pytest.raises(ValueError, match="base64url"):
        SecretBox.from_settings(make_settings(CONNECTION_ENCRYPTION_KEY="!!!not base64!!!"))
