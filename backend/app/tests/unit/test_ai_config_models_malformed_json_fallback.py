"""Regression test for POST /api/v1/ai/{backend}/models returning an
unhandled 500 (instead of falling back to the static FALLBACK_MODELS list)
when a backend's own /models endpoint replies with HTTP 200 but a body that
isn't valid JSON -- e.g. a gateway/outage page served with a 200 status.

Real bug: groq_client.list_models() (and the identical
openai_client/kimi_client/deepseek_client/xai_client/mistral_client/
openrouter_client implementations) call `response.raise_for_status()` then
unconditionally `response.json()`. raise_for_status() only raises on
4xx/5xx, so a 200 with a malformed body raises json.JSONDecodeError (a
ValueError), not an httpx.HTTPStatusError/HTTPError. ai_list_models() in
app/api/routes/ai_config.py used to wrap each of these 7 live-discovery
calls in only `except httpx.HTTPError`, which does not catch
JSONDecodeError, so it propagated uncaught out of the route handler as a
bare 500 -- rather than falling back to the static model list the
surrounding try/except is explicitly written to provide (same as the
missing-API-key and real-network-failure cases).

The neighboring "ollama" branch was coincidentally unaffected because it
already has a (differently-motivated) `except ValueError` clause that
happens to also catch JSONDecodeError.
"""
import uuid

import httpx
import pytest
import respx

from app.ai import deepseek_client, groq_client, kimi_client, mistral_client, openai_client, openrouter_client, xai_client
from app.api.routes.ai_config import ModelListRequest, ai_list_models
from app.auth.rbac import CurrentUser
from app.models.user import Role

_FAKE_USER = CurrentUser(id=uuid.uuid4(), email="admin@example.com", role=Role.ADMIN, full_name="Admin")

# (backend, models-endpoint URL, client module) for the 7 backends with real
# dynamic discovery -- mirrors the branch order in ai_config.ai_list_models.
_LIVE_DISCOVERY_BACKENDS = [
    ("groq", "https://api.groq.com/openai/v1/models", groq_client),
    ("openai", "https://api.openai.com/v1/models", openai_client),
    ("kimi", "https://api.moonshot.ai/v1/models", kimi_client),
    ("deepseek", "https://api.deepseek.com/models", deepseek_client),
    ("xai", "https://api.x.ai/v1/models", xai_client),
    ("mistral", "https://api.mistral.ai/v1/models", mistral_client),
    ("openrouter", "https://openrouter.ai/api/v1/models", openrouter_client),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend,models_url,client_module", _LIVE_DISCOVERY_BACKENDS)
@respx.mock
async def test_malformed_200_body_falls_back_to_static_list_not_500(backend, models_url, client_module):
    # Simulates a vendor outage/gateway page served with a 200 status --
    # raise_for_status() won't raise, but response.json() will.
    respx.get(models_url).mock(
        return_value=httpx.Response(200, content=b"<html>502 Bad Gateway</html>", headers={"content-type": "text/html"})
    )

    result = await ai_list_models(
        backend,
        ModelListRequest(credentials={"api_key": "mock-key"}),
        user=_FAKE_USER,
    )

    assert result["source"] == "fallback"
    assert result["models"] == client_module.FALLBACK_MODELS
    assert result["default"] == client_module.DEFAULT_MODEL
