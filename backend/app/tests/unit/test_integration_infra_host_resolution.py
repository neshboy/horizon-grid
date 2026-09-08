"""Regression test for a confirmed bug: 6 integration test files under
app/tests/integration/ (test_dashboard_api.py, test_dashboard_service_db.py,
test_deterministic_scoring.py, test_lookup_export_permissions.py,
test_lookup_flow.py, test_lookup_stream_persistence.py) used to hardcode
ONLY the docker-compose HOST-published ports (POSTGRES_HOST="localhost",
POSTGRES_PORT=5433, REDIS_HOST="localhost", REDIS_PORT=6379) in the
`pytestmark = pytest.mark.skipif(...)` guard each of them wraps itself in.

Inside the backend container -- both this project's documented dev test
command (`docker compose exec backend python -m pytest ...`) and its own
CI's "integration-docker" job -- "localhost" is the container's OWN
loopback, where nothing listens on 5433/6379 (only the in-network
`postgres`/`redis` hostnames route to the real datastores from in there).
That made every one of those files' skipif conditions evaluate to True
unconditionally in exactly the two places this suite is meant to run, so
all 42 of their tests silently SKIPPED there -- never actually executing
anywhere in the automated pipeline.

Fix: each of those 6 modules now resolves its host/port pair dynamically at
import time via a `_resolve_infra_host_port` (Postgres+Redis files) /
`_resolve_redis_host_port` (the Redis-only test_lookup_flow.py) helper,
preferring the real in-network hostname when reachable and falling back to
the docker-compose host-published port only when it isn't.

This test is deliberately infra-independent (no real Postgres/Redis
connection needed, unlike app/tests/integration/test_infra_skip_guard_
resolution.py's live confirmation of the same fix) -- it monkeypatches
socket.create_connection to simulate both environments directly, so it runs
unconditionally in the CI "unit" job (bare runner, no docker network at
all) and is immune to the live stack's shared-database contention under
concurrent test runs. It also directly documents the "fails before, passes
after" property: `_resolve_infra_host_port` did not exist at all prior to
the fix (every one of these 6 files hardcoded the host-published pair
unconditionally), so importing it fails with AttributeError against the
pre-fix code.
"""
import socket

import pytest

# Any one of the 5 Postgres+Redis-guarded modules exposes the identical
# helper (duplicated across all 5 -- there is no shared conftest.py in this
# repo, per each file's own docstring) -- test_lookup_stream_persistence.py
# is the file named in the confirmed finding this regresses.
from app.tests.integration import test_lookup_stream_persistence as _pg_redis_module
from app.tests.integration import test_lookup_flow as _redis_only_module


def test_prefers_in_network_hostname_when_reachable(monkeypatch):
    """Simulates running INSIDE the backend container: the in-network
    `postgres:5432` hostname is reachable, the host-published
    `localhost:5433` is not (exactly the real, confirmed-live behavior)."""

    def fake_create_connection(address, timeout=1.0):
        host, port = address
        if (host, port) == ("postgres", 5432):
            return object()  # any truthy context-manager-ish stand-in
        raise OSError("simulated: unreachable from inside the container")

    monkeypatch.setattr(socket, "create_connection", _as_context_manager(fake_create_connection))

    host, port = _pg_redis_module._resolve_infra_host_port("postgres", 5432, "localhost", 5433)
    assert (host, port) == ("postgres", 5432)


def test_falls_back_to_host_published_port_when_in_network_unreachable(monkeypatch):
    """Simulates running OUTSIDE any container, directly on the dev host: the
    in-network `postgres` hostname doesn't resolve/isn't reachable at all,
    but the docker-compose host-published `localhost:5433` mapping is."""

    def fake_create_connection(address, timeout=1.0):
        host, port = address
        if (host, port) == ("localhost", 5433):
            return object()
        raise OSError("simulated: in-network hostname unreachable from the bare host")

    monkeypatch.setattr(socket, "create_connection", _as_context_manager(fake_create_connection))

    host, port = _pg_redis_module._resolve_infra_host_port("postgres", 5432, "localhost", 5433)
    assert (host, port) == ("localhost", 5433)


def test_neither_reachable_falls_back_to_published_pair_unchanged(monkeypatch):
    """Neither reachable (e.g. infra simply isn't up yet) -- must still
    return a well-formed pair (the host-published one) rather than raising,
    so the caller's own skipif guard is what reports the "not reachable"
    condition, not an unhandled exception here."""

    def fake_create_connection(address, timeout=1.0):
        raise OSError("simulated: nothing up yet")

    monkeypatch.setattr(socket, "create_connection", _as_context_manager(fake_create_connection))

    host, port = _pg_redis_module._resolve_infra_host_port("postgres", 5432, "localhost", 5433)
    assert (host, port) == ("localhost", 5433)


def test_redis_only_module_prefers_in_network_redis_hostname(monkeypatch):
    """test_lookup_flow.py is the one file of the 6 that is Redis-only (no
    Postgres) -- covers its distinct `_resolve_redis_host_port` helper,
    which had the extra wrinkle that the in-network and host-published ports
    are numerically IDENTICAL (6379 either way), so only the hostname
    differs; a naive port-only check would never have caught this bug."""

    def fake_create_connection(address, timeout=1.0):
        host, port = address
        if (host, port) == ("redis", 6379):
            return object()
        raise OSError("simulated: unreachable from inside the container")

    monkeypatch.setattr(socket, "create_connection", _as_context_manager(fake_create_connection))

    host, port = _redis_only_module._resolve_redis_host_port()
    assert (host, port) == ("redis", 6379)


def test_redis_only_module_falls_back_when_in_network_redis_unreachable(monkeypatch):
    def fake_create_connection(address, timeout=1.0):
        host, port = address
        if (host, port) == ("localhost", 6379):
            return object()
        raise OSError("simulated: in-network hostname unreachable from the bare host")

    monkeypatch.setattr(socket, "create_connection", _as_context_manager(fake_create_connection))

    host, port = _redis_only_module._resolve_redis_host_port()
    assert (host, port) == ("localhost", 6379)


def test_resolve_infra_host_port_helper_exists():
    """Directly documents the "fails before, passes after" property: this
    helper (and its Redis-only counterpart exercised above) did not exist at
    all prior to the fix -- every one of the 6 affected files hardcoded the
    host-published pair as bare module-level constants instead. Against the
    pre-fix code this raises AttributeError.
    """
    assert hasattr(_pg_redis_module, "_resolve_infra_host_port")
    assert hasattr(_redis_only_module, "_resolve_redis_host_port")


class _as_context_manager:
    """socket.create_connection is normally used as a context manager
    (`with socket.create_connection(...) as s:`); wraps a plain
    address-in/connection-out fake so it satisfies that protocol too."""

    def __init__(self, fn):
        self._fn = fn

    def __call__(self, address, timeout=1.0):
        return _CMWrapper(self._fn(address, timeout))


class _CMWrapper:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self._value

    def __exit__(self, exc_type, exc, tb):
        return False
