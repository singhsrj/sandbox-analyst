"""Encryption at rest for users' database passwords (AES-256-GCM).

* the key comes from CONNECTION_ENCRYPTION_KEY (32 bytes, base64url); it is never stored with
  the data, so a copy of the database alone does not reveal any password
* every ciphertext is bound to its row with associated data (connection id + owner): a
  ciphertext copied into another row, or another person's row, fails to decrypt
* `key_id` (a short hash of the key) is stored next to each ciphertext, so a rotated key is
  detected with a clear error instead of a decryption failure
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings

_NONCE_BYTES = 12


class SecretBoxError(RuntimeError):
    """A secret could not be opened (wrong key, tampered data, or the wrong row)."""


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("the connection encryption key must be 32 bytes")
        self._aead = AESGCM(key)
        self.key_id = hashlib.sha256(b"sandbox-analyst/connections/" + key).hexdigest()[:16]

    @classmethod
    def from_settings(cls, settings: Settings) -> SecretBox | None:
        """The box for CONNECTION_ENCRYPTION_KEY, or None when it is not configured."""
        if settings.connection_encryption_key is None:
            return None
        raw = settings.connection_encryption_key.get_secret_value().strip()
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (binascii.Error, ValueError) as exc:
            raise ValueError("CONNECTION_ENCRYPTION_KEY is not valid base64url") from exc
        return cls(key)

    def seal(self, plaintext: str, context: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext.encode(), context.encode())

    def open(self, blob: bytes, context: str, key_id: str) -> str:
        if key_id != self.key_id:
            raise SecretBoxError("saved with a different encryption key")
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        try:
            return self._aead.decrypt(nonce, ciphertext, context.encode()).decode()
        except InvalidTag as exc:
            raise SecretBoxError("the secret does not belong to this record") from exc


def connection_context(connection_id: str, owner_id: str) -> str:
    """Associated data that ties a password ciphertext to its connection and its owner."""
    return f"connection:{connection_id}:owner:{owner_id}"
