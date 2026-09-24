"""Unit tests for app.core.crypto -- the encryption layer protecting
runtime-configured provider/AI credentials at rest (see
app/core/runtime_config.py). All values here are synthetic test strings,
never real credentials.
"""
import pytest

import app.core.crypto as crypto_module
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    # _fernet() is @lru_cache'd on purpose (real key material shouldn't be
    # re-derived per call) but that means a test that monkeypatches
    # get_settings() must clear it before AND after, or the cached Fernet
    # instance from a previous test leaks into this one (or vice versa).
    crypto_module._fernet.cache_clear()
    yield
    crypto_module._fernet.cache_clear()


def test_encrypt_then_decrypt_roundtrips():
    plaintext = "sk-test-abcdef123456"
    ciphertext = encrypt_secret(plaintext)
    assert ciphertext != plaintext
    assert decrypt_secret(ciphertext) == plaintext


def test_encrypting_empty_string_returns_empty_string():
    assert encrypt_secret("") == ""


def test_decrypting_empty_string_returns_empty_string():
    assert decrypt_secret("") == ""


def test_decrypting_garbage_returns_empty_string_not_raise():
    # A corrupted row or a master-key rotation should degrade to "no
    # credential" (safe: providers already treat that as not-configured),
    # never raise and 500 the caller.
    assert decrypt_secret("not-a-real-fernet-token") == ""


def test_decrypting_a_token_from_a_different_key_returns_empty_string():
    # The real-world case that motivates the above: a structurally valid
    # Fernet token that was encrypted under a *different* key (e.g. after a
    # master-key rotation) must still degrade to "" rather than raise --
    # this is distinct from plain garbage, since it exercises the HMAC
    # verification failure path rather than a token-parsing failure.
    from cryptography.fernet import Fernet

    foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(
        b"sk-test-abcdef123456"
    ).decode("ascii")
    assert decrypt_secret(foreign_ciphertext) == ""


def test_ciphertext_never_contains_the_plaintext():
    plaintext = "super-secret-value-1234567890"
    ciphertext = encrypt_secret(plaintext)
    assert plaintext not in ciphertext


def test_two_encryptions_of_the_same_value_differ():
    # Fernet includes a random IV/timestamp -- ciphertext should not be
    # deterministic (guards against a naive/broken implementation that
    # would make ciphertext-equality leak plaintext-equality).
    plaintext = "same-value"
    assert encrypt_secret(plaintext) != encrypt_secret(plaintext)


def test_mask_secret_shows_only_a_short_suffix():
    masked = mask_secret("abcdefghij1234")
    assert masked.endswith("1234")
    assert "abcdefghij" not in masked
    assert set(masked[:-4]) == {"*"}


def test_mask_secret_of_empty_string_is_empty():
    assert mask_secret("") == ""


def test_mask_secret_shorter_than_suffix_is_fully_masked():
    masked = mask_secret("ab")
    assert masked == "**"
    assert "ab" not in masked


def test_mask_secret_exact_suffix_length_is_fully_masked():
    # Boundary: length == visible_suffix must take the "fully masked"
    # branch (len(plaintext) <= visible_suffix), not the suffix-revealing
    # branch -- otherwise a short credential would be shown in full.
    masked = mask_secret("abcd")
    assert masked == "****"
    assert "abcd" not in masked


def test_invalid_encryption_master_key_falls_back_instead_of_crashing(monkeypatch):
    # Real bug found live: .env.example used to ship ENCRYPTION_MASTER_KEY
    # with a non-empty placeholder ("replace-with-a-different-long-random-
    # string") that isn't valid Fernet key material (not 32 url-safe
    # base64-encoded bytes). A fresh install that only follows the README's
    # Quick Start (which calls out replacing JWT_SECRET_KEY, never this one)
    # left that placeholder in place, and every single encrypt_secret()/
    # decrypt_secret() call raised ValueError -- which silently failed every
    # IOC investigation with no explanation surfaced to the user. This must
    # degrade to the JWT-derived key instead, exactly like an unset value
    # does, not raise.
    class _FakeSettings:
        encryption_master_key = "replace-with-a-different-long-random-string"
        jwt_secret_key = "a-real-jwt-secret-for-this-test-only"

    monkeypatch.setattr(crypto_module, "get_settings", lambda: _FakeSettings())

    plaintext = "sk-test-should-not-crash"
    ciphertext = encrypt_secret(plaintext)
    assert ciphertext != plaintext
    assert decrypt_secret(ciphertext) == plaintext


def test_invalid_encryption_master_key_falls_back_to_the_same_key_an_unset_one_would(
    monkeypatch,
):
    # The fallback path above must be the *same* derived key an empty/unset
    # ENCRYPTION_MASTER_KEY would already use -- otherwise "invalid value"
    # and "unset value" would silently encrypt under two different keys,
    # which would be its own confusing bug.
    class _FakeSettingsInvalid:
        encryption_master_key = "still-not-valid-fernet-key-material"
        jwt_secret_key = "shared-jwt-secret-for-this-test"

    class _FakeSettingsEmpty:
        encryption_master_key = ""
        jwt_secret_key = "shared-jwt-secret-for-this-test"

    monkeypatch.setattr(crypto_module, "get_settings", lambda: _FakeSettingsInvalid())
    crypto_module._fernet.cache_clear()
    token = encrypt_secret("cross-check-value")

    monkeypatch.setattr(crypto_module, "get_settings", lambda: _FakeSettingsEmpty())
    crypto_module._fernet.cache_clear()
    assert decrypt_secret(token) == "cross-check-value"
