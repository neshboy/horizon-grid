"""Regression guard for a real bug found via live docker-stats testing:
docker-compose.yml's celery_worker service ran `celery ... worker` with no
--concurrency flag. Celery's prefork pool defaults concurrency to
multiprocessing.cpu_count() when unset, so on a 32-core host it silently
forked 32 worker child processes regardless of the service's own
`mem_limit: 1g` -- confirmed live via `docker exec ... nproc` (32) and the
worker's own startup banner showing `concurrency: 32 (prefork)`, and via
`docker stats` showing the container permanently pinned at ~970-1015MiB
(~95-99%) of its 1g ceiling completely idle (0% CPU, no task ever run),
leaving almost no headroom for real task execution (httpx connections, DB
sessions, AI calls during scheduled OSINT crawls) and risking an OOM-kill
under any concurrent load rather than a genuine leak.

The fix pins --concurrency to a small fixed default (overridable via
CELERY_WORKER_CONCURRENCY) sized to fit comfortably under mem_limit -- this
worker only ever runs one task type (app.workers.tasks.run_osint_crawl,
scheduled hourly, itself already internally concurrent via asyncio/httpx --
see tasks.py), so it never needed to scale with host core count.

Confirmed live post-fix: recreating the container with the flag in place
dropped it to `concurrency: 4 (prefork)`, 5 PIDs (1 master + 4 children)
instead of 33, and ~208MiB/~20% of the same 1g limit at idle.
"""
import re
from pathlib import Path

import pytest
import yaml

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_k8s_ai_backend_secrets.py): the backend/celery_worker containers only
# ever bind-mount ./backend as /app -- docker-compose.yml is a sibling of
# backend/ in the real repo, but simply does not exist inside any
# container's filesystem at all. Skipping loudly (not silently) when it's
# not found, rather than assuming a container-relative path that would
# never resolve there, so this only ever runs (and only ever matters) from
# a host-side run against the full repo checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"

_SKIP_REASON = "docker-compose.yml not mounted in this environment (host-only check)"

_CONCURRENCY_RE = re.compile(r"--concurrency[= ](\S+)")


def _celery_worker_service() -> dict:
    doc = yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))
    return doc["services"]["celery_worker"]


@pytest.mark.skipif(not _COMPOSE_FILE.exists(), reason=_SKIP_REASON)
def test_celery_worker_command_pins_a_concurrency_flag():
    service = _celery_worker_service()
    command = service["command"]
    assert isinstance(command, str) and "celery" in command, (
        "test assumption stale: celery_worker's command is no longer a plain "
        f"string containing 'celery': {command!r}"
    )

    match = _CONCURRENCY_RE.search(command)
    assert match, (
        "celery_worker's command has no --concurrency flag -- without it, "
        "Celery's prefork pool defaults to multiprocessing.cpu_count(), "
        "which on a many-core host forks one child process per core "
        "regardless of this service's mem_limit, pinning the container "
        f"near its memory ceiling even completely idle. command={command!r}"
    )


@pytest.mark.skipif(not _COMPOSE_FILE.exists(), reason=_SKIP_REASON)
def test_celery_worker_concurrency_is_a_small_bounded_number_not_host_core_count():
    service = _celery_worker_service()
    command = service["command"]
    match = _CONCURRENCY_RE.search(command)
    assert match, "expected --concurrency to be present (see other test in this file)"

    raw_value = match.group(1)
    # The flag is expected to be overridable (CELERY_WORKER_CONCURRENCY, per
    # the fix's own comment in docker-compose.yml) via compose's
    # ${VAR:-default} syntax rather than a bare literal -- pull the default
    # out of that syntax if present, otherwise treat the whole value as a
    # literal.
    default_match = re.match(r"^\$\{[A-Z0-9_]+:-(\d+)\}$", raw_value)
    if default_match:
        concurrency = int(default_match.group(1))
    else:
        concurrency = int(raw_value)

    # Sanity bound, not a precisely-tuned ceiling: this worker runs a single
    # lightweight, already-internally-concurrent task type (see this file's
    # module docstring), so it should never need anywhere close to a
    # many-core host's full core count (32 on the box this bug was found
    # on) to fit under its 1g mem_limit. Guards against a future edit
    # silently reintroducing an unbounded/host-scaled value.
    assert 1 <= concurrency <= 16, (
        f"celery_worker --concurrency default of {concurrency} is outside the "
        "expected small, fixed range (1-16) -- if this is intentional, "
        "confirm live via `docker stats` that the container still has real "
        "headroom under mem_limit, not just at idle but under a burst of "
        "concurrent scheduled tasks."
    )


@pytest.mark.skipif(not _COMPOSE_FILE.exists(), reason=_SKIP_REASON)
def test_celery_worker_still_has_its_memory_limit():
    # Belt-and-suspenders: the fix is only meaningful paired with the
    # mem_limit it's sized against -- guard against that being dropped too.
    service = _celery_worker_service()
    assert service.get("mem_limit"), "celery_worker lost its mem_limit"
