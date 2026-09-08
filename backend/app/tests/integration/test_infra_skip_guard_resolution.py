"""Regression test for a confirmed bug: 6 integration test files
(test_dashboard_api.py, test_dashboard_service_db.py,
test_deterministic_scoring.py, test_lookup_export_permissions.py,
test_lookup_flow.py, test_lookup_stream_persistence.py) used to hardcode
ONLY the docker-compose HOST-published ports (localhost:5433 for Postgres,
localhost:6379 for Redis) in the `pytestmark = pytest.mark.skipif(...)`
guard each of them wraps itself in.

Inside the backend container -- which is both this project's documented dev
test command (`docker compose exec backend python -m pytest ...`) and its
own CI's "integration-docker" job -- "localhost" is the container's OWN
loopback interface, where nothing listens on 5433/6379 (only the in-network
`postgres`/`redis` hostnames, on their normal 5432/6379 ports, route to the
real datastores from inside the container). That made every one of those
files' skipif conditions evaluate to True unconditionally in exactly the
two places this suite is meant to run, so all 42 of their tests silently
SKIPPED there -- never actually executing anywhere in the automated
pipeline, and providing zero real regression protection for e.g. the
lookup:export RBAC permission gate or the dashboard KPI exclusion rules.

Fix: each of those 6 modules now resolves its POSTGRES_HOST/PORT and
REDIS_HOST/PORT dynamically (`_resolve_infra_host_port` /
`_resolve_redis_host_port`), preferring the real in-network hostname when
reachable (the in-container case) and falling back to the docker-compose
host-published port otherwise (an out-of-container host-side pytest run).

This test proves the fix directly and deterministically -- without
depending on the full (occasionally slow/contended-under-concurrent-load)
end-to-end lookup flows those files otherwise exercise -- by re-importing
each fixed module fresh and asserting it resolved to the in-network
hostname (proving the resolution logic actually prefers it over the
never-reachable-from-in-container "localhost" default) and that its own
reachability check is satisfied (proving its skipif guard evaluates to "do
NOT skip" here, unlike before the fix).
"""
import importlib
import socket

import pytest

_POSTGRES_REDIS_MODULES = [
    "app.tests.integration.test_dashboard_api",
    "app.tests.integration.test_dashboard_service_db",
    "app.tests.integration.test_deterministic_scoring",
    "app.tests.integration.test_lookup_export_permissions",
    "app.tests.integration.test_lookup_stream_persistence",
]

_REDIS_ONLY_MODULES = [
    "app.tests.integration.test_lookup_flow",
]


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


# This test is only meaningful where at least the in-network hostnames (the
# case it primarily verifies) or the host-published ports (the fallback
# path it also touches) are reachable -- e.g. never on the bare GitHub
# runner that runs app/tests/unit with zero infra at all.
pytestmark = pytest.mark.skipif(
    not (
        (_reachable("postgres", 5432) or _reachable("localhost", 5433))
        and (_reachable("redis", 6379) or _reachable("localhost", 6379))
    ),
    reason="Neither in-network postgres/redis nor host-published "
    "localhost:5433/6379 reachable -- run `docker compose up -d postgres "
    "redis` first.",
)


@pytest.mark.parametrize("module_name", _POSTGRES_REDIS_MODULES)
def test_postgres_and_redis_module_resolves_reachable_infra(module_name):
    module = importlib.import_module(module_name)
    importlib.reload(module)  # re-run its module-level host/port resolution fresh

    # The exact assertion that fails against the pre-fix code: it used to
    # hardcode POSTGRES_HOST = "localhost" / REDIS_HOST = "localhost"
    # unconditionally, which is never the in-network hostname.
    assert module.POSTGRES_HOST == "postgres"
    assert module.POSTGRES_PORT == 5432
    assert module.REDIS_HOST == "redis"
    assert module.REDIS_PORT == 6379

    # And the direct behavioral consequence: the module's own skipif
    # condition -- built from the exact same POSTGRES_HOST/PORT and
    # REDIS_HOST/PORT this test just asserted on -- must resolve to
    # "reachable", i.e. do NOT skip, from inside this process.
    assert module._reachable(module.POSTGRES_HOST, module.POSTGRES_PORT)
    assert module._reachable(module.REDIS_HOST, module.REDIS_PORT)


@pytest.mark.parametrize("module_name", _REDIS_ONLY_MODULES)
def test_redis_only_module_resolves_reachable_infra(module_name):
    module = importlib.import_module(module_name)
    importlib.reload(module)

    # Pre-fix, this module hardcoded REDIS_HOST = "localhost" -- same port
    # number (6379) as the in-network hostname's, which is exactly what made
    # this particular bug easy to miss by inspection: the port looked right,
    # but "localhost" from inside the backend container is never where
    # Redis actually listens.
    assert module.REDIS_HOST == "redis"
    assert module.REDIS_PORT == 6379
    assert module._reachable(module.REDIS_HOST, module.REDIS_PORT)
