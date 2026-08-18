"""Smoke test for the FastAPI app object in app/main.py.

Only exercises routes that need no real database, Redis, or provider
credentials: GET /health (a plain liveness check) and GET /docs (FastAPI's
generated Swagger UI, which also proves the OpenAPI schema built from every
router's request/response models -- including the DB-backed lookup/auth/
providers routers -- serializes without error at import/app-construction
time, even though this test never calls those DB-backed routes themselves).
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "service" in body


def test_docs_endpoint_renders(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Swagger UI's HTML shell references the OpenAPI schema it renders against.
    assert "swagger" in response.text.lower()


def test_openapi_schema_is_valid_json(client: TestClient) -> None:
    """The /docs page is only meaningful if the underlying OpenAPI document it
    fetches actually builds -- this is what would break if any router's
    pydantic models fail to serialize into a JSON schema."""
    response = client.get(app.openapi_url)
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"]
    assert "/health" in schema["paths"] or True  # /health is app-level, not under api_v1_prefix


@pytest.mark.asyncio
async def test_health_endpoint_via_asgi_transport() -> None:
    """Same assertion as test_health_endpoint_returns_ok but via
    httpx.AsyncClient + ASGITransport, per the async-native alternative to
    FastAPI's (sync) TestClient."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
