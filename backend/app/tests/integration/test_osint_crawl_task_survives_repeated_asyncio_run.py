"""Regression test for a confirmed P3 finding, found via live/runtime testing
during a Redis failure-injection test: app.workers.tasks.run_osint_crawl (the
Celery Beat hourly task) crashed with an unhandled RuntimeError shortly after
a `docker compose stop redis` / `docker compose start redis` cycle --
`docker compose logs celery_worker` showed "RuntimeError: Event loop is
closed" while tearing down an asyncpg connection, immediately followed by
"RuntimeError: Task ... got Future ... attached to a different loop".

Root cause: run_osint_crawl() is a sync Celery task that calls
asyncio.run(_run_osint_crawl_async()) fresh on EVERY invocation (there is no
running loop in a Celery worker process to piggyback on -- see this task's
own module docstring). asyncio.run() tears down its event loop the moment the
coroutine returns. app.core.db's `_engine` (and its connection pool) is a
process-wide singleton, reused across every one of those invocations though
-- and asyncpg binds each pooled connection to the event loop that created
it. So a connection left sitting idle in the pool when one run's loop closes
is, from that point on, attached to a dead loop; the next run's pool_pre_ping
check (or any other use of that connection) then raises exactly the
"Event loop is closed" / "attached to a different loop" RuntimeErrors from
the live logs, instead of the task completing or failing cleanly.

Reproduced live (before the fix) by calling
app.workers.tasks._recent_crawlable_iocs() -- the coroutine that opens a real
DB session -- via two consecutive `asyncio.run()` calls in one process: the
FIRST call always succeeded, and the SECOND call crashed deterministically,
every time, with the identical traceback seen in the celery_worker logs. No
actual Redis outage is needed to reproduce this -- the Redis restart in the
original finding just happened to be what was running when this task's
second-or-later invocation in that worker process's lifetime landed.

Fix: _run_osint_crawl_async() now disposes app.core.db's `_engine` pool in a
`finally`, inside its OWN coroutine/event loop, before asyncio.run() returns
and tears that loop down -- draining any connections opened during this run
so the NEXT run's asyncio.run() call always opens fresh connections under
its own (new) loop instead of being handed one bound to an already-dead one.
This mirrors the exact pattern this repo's own DB-touching integration tests
already use for the identical problem across pytest-asyncio's per-test event
loops (see e.g. test_dashboard_service_db.py's `_dispose_pools_after_each_test`).

Follows this repo's own host-infra-override pattern (no shared conftest.py in
this repo -- see test_dashboard_service_db.py / test_lookup_stream_persistence.py
for the full rationale) so it works both inside a container (`docker compose
exec backend python -m pytest ...`) and from a bare host run.
"""
import asyncio
import os
import socket

import pytest


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _resolve_infra_host_port(in_network_host, in_network_port, published_host, published_port):
    """See test_lookup_stream_persistence.py's function of the same name for
    the full rationale: prefer the real in-docker-network hostname
    (`postgres`), reachable when this test runs INSIDE the backend container
    (the documented way to run it); fall back to the docker-compose
    HOST-published port for an out-of-container host run."""
    if _reachable(in_network_host, in_network_port):
        return in_network_host, in_network_port
    return published_host, published_port


POSTGRES_HOST, POSTGRES_PORT = _resolve_infra_host_port("postgres", 5432, "localhost", 5433)


pytestmark = pytest.mark.skipif(
    not _reachable(POSTGRES_HOST, POSTGRES_PORT),
    reason="Postgres not reachable via either the in-network `postgres` hostname or the "
    "docker-compose host-published localhost:5433 port -- run `docker compose up -d postgres` first.",
)


@pytest.fixture(autouse=True)
def _point_app_settings_at_host_infra():
    """See test_lookup_stream_persistence.py's fixture of the same name for
    the full rationale on why the engine must be rebuilt directly rather than
    just clearing the settings cache."""
    import app.core.db as db_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    previous_db_url = os.environ.get("DATABASE_URL")
    _pg_user = os.environ.get("POSTGRES_USER", "ioc")
    _pg_password = os.environ.get("POSTGRES_PASSWORD", "ioc")
    _pg_db = os.environ.get("POSTGRES_DB", "ioc_intel")
    os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{_pg_user}:{_pg_password}@{POSTGRES_HOST}:{POSTGRES_PORT}/{_pg_db}"
    get_settings.cache_clear()

    db_module._engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, echo=False)
    db_module._SessionLocal = async_sessionmaker(bind=db_module._engine, expire_on_commit=False, class_=AsyncSession)

    yield

    if previous_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_db_url
    get_settings.cache_clear()


def test_osint_crawl_survives_three_consecutive_asyncio_run_invocations(monkeypatch):
    """Deliberately NOT an `async def` test: run_osint_crawl() itself is a
    plain sync function that calls asyncio.run() -- you cannot call
    asyncio.run() from inside an already-running loop (which any
    @pytest.mark.asyncio test body is), so this reproduces the real bug's
    exact call shape: a sync caller invoking asyncio.run() repeatedly in the
    same process, exactly like Celery invoking this task's entry point once
    per schedule tick within one long-lived worker process.
    """
    import app.workers.tasks as tasks_module

    # Stub out the actual network crawl -- this test proves the shared DB
    # connection pool survives being reused across independent asyncio.run()
    # event loops, not the real OSINT provider integrations (no real network
    # calls, and no dependency on how many crawlable IOCs already exist in
    # this shared dev DB).
    calls = []

    async def _fake_crawl_one(ioc_value, ioc_type_str, client):
        calls.append((ioc_value, ioc_type_str))

    monkeypatch.setattr(tasks_module, "_crawl_one", _fake_crawl_one)

    # Run 1: opens a real DB session (app.core.db.new_session()) -- and,
    # before the fix, would leave a pooled asyncpg connection bound to THIS
    # call's event loop sitting idle in app.core.db._engine's pool.
    result_1 = asyncio.run(tasks_module._run_osint_crawl_async())

    # Run 2: a brand new event loop, sharing the SAME process-wide
    # app.core.db._engine/pool as run 1. Before the fix, this raised
    # RuntimeError("... attached to a different loop") / "Event loop is
    # closed" deterministically -- reproduced live, every single time,
    # before adding the engine.dispose() fix.
    result_2 = asyncio.run(tasks_module._run_osint_crawl_async())

    # Run 3, for extra confidence this isn't a one-off timing artifact.
    result_3 = asyncio.run(tasks_module._run_osint_crawl_async())

    # Real int returns (0 or the number of refreshed IOCs), not an exception,
    # from every single run.
    assert isinstance(result_1, int)
    assert isinstance(result_2, int)
    assert isinstance(result_3, int)
