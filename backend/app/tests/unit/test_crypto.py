"""Unit tests for app.core.crypto -- the encryption layer protecting
runtime-configured provider/AI credentials at rest (see
app/core/runtime_config.py). All values here are synthetic test strings,
never real credentials.
"""
import pytest

from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret


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
