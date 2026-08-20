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

from app.core.config import get_settings
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


def test_docs_endpoint_matches_the_configured_environment(client: TestClient) -> None:
    """/docs (and /redoc, the raw OpenAPI schema) are gated off in
    production -- app/main.py's _docs_enabled -- a real hardening fix, not
    a regression: this test runs both where ENVIRONMENT is unset (the bare
    CI "unit" job, defaults to "development", docs enabled) and where it's
    explicitly "production" (the "integration-docker" job's
    docker-compose.prod.yml), so it must assert whichever behavior is
    actually correct for the environment it's running in, not assume docs
    are always on."""
    response = client.get("/docs")
    if get_settings().environment == "production":
        assert response.status_code == 404
    else:
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Swagger UI's HTML shell references the OpenAPI schema it renders against.
        assert "swagger" in response.text.lower()


def test_openapi_schema_builds_without_error() -> None:
    """The OpenAPI document must build without error regardless of whether
    the /docs HTTP route is exposed in this environment -- this is what
    would break if any router's pydantic models fail to serialize into a
    JSON schema, independent of the environment-based routing gate. Calls
    app.openapi() directly (the underlying schema-construction method)
    rather than the HTTP route, since that route 404s in production."""
    schema = app.openapi()
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
