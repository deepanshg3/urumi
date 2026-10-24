"""Unit tests for gateway password hashing, API keys and credential encryption."""

from __future__ import annotations

import pytest

from services.common.errors import ConfigurationError
from services.gateway.security import (
    CredentialCipher,
    API_KEY_PREFIX,
    api_key_prefix,
    generate_api_key,
    generate_opaque_token,
    hash_api_key,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    encoded = hash_password("correct horse battery")
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery", encoded)
    assert not verify_password("wrong password", encoded)
    assert not verify_password("correct horse battery", None)


def test_password_hash_is_salted() -> None:
    assert hash_password("same-password-123") != hash_password("same-password-123")


def test_password_minimum_length() -> None:
    with pytest.raises(ValueError):
        hash_password("short")


def test_api_keys_are_prefixed_and_hashed() -> None:
    key = generate_api_key()
    assert key.startswith(API_KEY_PREFIX)
    assert len(key) > 40
    assert hash_api_key(key) != key
    assert api_key_prefix(key) == key[:12]


def test_opaque_tokens_are_unique() -> None:
    a, b = generate_opaque_token(), generate_opaque_token()
    assert a != b
    assert hash_token(a) != hash_token(b)


def test_credential_cipher_roundtrip() -> None:
    cipher = CredentialCipher(secret="a-very-secret-value-123")
    token = cipher.encrypt("super-secret-token")
    assert "super-secret-token" not in token
    assert cipher.decrypt(token) == "super-secret-token"


def test_credential_cipher_requires_secret() -> None:
    with pytest.raises(ConfigurationError):
        CredentialCipher(secret="")


def test_credential_cipher_rejects_wrong_key() -> None:
    token = CredentialCipher(secret="first-secret-value-123").encrypt("value")
    with pytest.raises(ConfigurationError):
        CredentialCipher(secret="different-secret-456").decrypt(token)
