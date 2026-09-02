"""Unit tests for app.main's startup hooks -- specifically the JWT-secret
placeholder guard. Confirmed live during overnight QA that a token forged
offline with the literal .env.example placeholder was accepted by the real
running backend (GET /auth/me and admin-only POST /admin/users both
succeeded with zero real credentials) -- this guard is the fix.
"""
import pytest

from app.main import _warn_if_jwt_secret_is_a_placeholder, settings


@pytest.mark.asyncio
async def test_production_with_placeholder_secret_refuses_to_start(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "replace-with-a-long-random-string")
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        await _warn_if_jwt_secret_is_a_placeholder()


@pytest.mark.asyncio
async def test_production_with_other_known_placeholder_also_refuses_to_start(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "change-me-in-production")
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        await _warn_if_jwt_secret_is_a_placeholder()


@pytest.mark.asyncio
async def test_development_with_placeholder_secret_only_warns(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "replace-with-a-long-random-string")
    monkeypatch.setattr(settings, "environment", "development")
    await _warn_if_jwt_secret_is_a_placeholder()  # must not raise


@pytest.mark.asyncio
async def test_production_with_a_real_secret_starts_cleanly(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "a-genuinely-random-64-char-secret-value-not-a-placeholder-x9z")
    monkeypatch.setattr(settings, "environment", "production")
    await _warn_if_jwt_secret_is_a_placeholder()  # must not raise
