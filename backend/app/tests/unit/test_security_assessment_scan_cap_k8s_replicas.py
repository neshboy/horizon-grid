"""Regression guard for a real, confirmed bug: app/core/security_assessment.py's
platform-wide concurrent-scan cap (_MAX_CONCURRENT_SCANS / _scan_semaphore) was
a bare module-level `asyncio.Semaphore(4)` -- an in-process object that only
ever bounds concurrency WITHIN ONE Python process.

docker-compose.yml and the Windows/Linux installers all run exactly one
backend container, so 4 IS the real platform-wide ceiling there, deliberately
paired with that service's 4g mem_limit (see docker-compose.yml's backend
comment: "the cap bounds how many can run at once, this limits the damage if
that cap is ever raised or a single run is unusually heavy").

k8s/base/backend-deployment.yaml runs `replicas: 2` of this same image, and
POST /{lookup_id}/run's background task (_spawn_background) runs in-process
via asyncio.create_task, not via Celery/any shared queue -- so each of the 2
pods built its own independent `asyncio.Semaphore(4)`, silently doubling the
real platform-wide ceiling to 8 concurrent scans/nmap subprocesses versus the
4 every other deployment path enforces.

The fix makes the cap read from app/core/config.py's Settings
(security_assessment_max_concurrent_scans, still defaulting to 4) instead of
a hardcoded literal, and has k8s/base/backend-deployment.yaml override it down
to 2-per-pod via its own container-level `env:` (mirroring the existing
DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW backend-only override pattern there) so
2 pods x 2 = 4, matching the intended single platform-wide ceiling.
"""
from pathlib import Path

import pytest
import yaml

import app.core.security_assessment as security_assessment_module
from app.core.config import Settings

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_k8s_backend_db_pool_sizing.py / test_k8s_backend_deployment_health_probes.py):
# the backend container only ever bind-mounts ./backend as /app -- k8s/ and
# docker-compose.yml are siblings of backend/ in the real repo, but simply do
# not exist inside the container's filesystem at all. Skipping loudly (not
# silently) when they're not found, rather than assuming a container-relative
# path that would never resolve there, so this only ever runs (and only ever
# matters) from a host-side run against the full repo checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_DEPLOYMENT = _REPO_ROOT / "k8s" / "base" / "backend-deployment.yaml"
_COMPOSE = _REPO_ROOT / "docker-compose.yml"

_SKIP_REASON = "k8s/docker-compose files not mounted in this environment (host-only check)"


def _backend_deployment_replicas_and_env() -> tuple[int, dict]:
    docs = list(yaml.safe_load_all(_BACKEND_DEPLOYMENT.read_text(encoding="utf-8")))
    deployment = next(doc for doc in docs if doc and doc.get("kind") == "Deployment")
    replicas = deployment["spec"]["replicas"]
    containers = deployment["spec"]["template"]["spec"]["containers"]
    backend_container = next(c for c in containers if c["name"] == "backend")
    env = {item["name"]: item.get("value") for item in (backend_container.get("env") or [])}
    return replicas, env


def _compose_backend_env() -> dict:
    doc = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    return doc["services"]["backend"].get("environment") or {}


def test_default_max_concurrent_scans_is_still_the_single_instance_ceiling():
    # docker-compose.yml/the Windows/Linux installers rely on this default
    # (they never override SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS) being the
    # real platform-wide ceiling for their single-container deployment --
    # if this default ever drifts, every deployment-path comparison below
    # (and docker-compose.yml's paired 4g mem_limit) silently goes stale too.
    assert Settings().security_assessment_max_concurrent_scans == 4


def test_scan_semaphore_capacity_is_driven_by_settings_not_a_hardcoded_literal(monkeypatch):
    # This is the actual root-cause assertion: before the fix,
    # _MAX_CONCURRENT_SCANS was the bare literal `4` with no route from
    # app/core/config.py's Settings at all, so no environment variable could
    # ever change a single backend process's cap. Simulating a
    # differently-configured process (as k8s/base/backend-deployment.yaml now
    # does with SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS=2) must change what a
    # freshly-built semaphore's capacity would be.
    patched = Settings(security_assessment_max_concurrent_scans=2)
    monkeypatch.setattr(security_assessment_module, "get_settings", lambda: patched)

    # Calls the exact function the module's own top-level
    # `_MAX_CONCURRENT_SCANS = _resolve_max_concurrent_scans()` uses to build
    # the semaphore's capacity at import time.
    rebuilt_cap = security_assessment_module._resolve_max_concurrent_scans()
    assert rebuilt_cap == 2, (
        "app/core/security_assessment.py's concurrent-scan cap did not pick up "
        "a changed Settings value -- it is still hardcoded rather than sourced "
        "from app/core/config.py's Settings, so k8s/base/backend-deployment.yaml's "
        "per-pod override has no effect."
    )


@pytest.mark.skipif(
    not (_BACKEND_DEPLOYMENT.exists() and _COMPOSE.exists()), reason=_SKIP_REASON
)
def test_k8s_per_pod_scan_cap_times_replica_count_matches_single_instance_ceiling():
    single_instance_ceiling = Settings().security_assessment_max_concurrent_scans
    assert single_instance_ceiling == 4, (
        "test assumption stale: app/core/config.py's "
        "security_assessment_max_concurrent_scans default is no longer 4 -- "
        "if intentional, revisit this test's expected platform-wide ceiling"
    )

    compose_env = _compose_backend_env()
    assert "SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS" not in compose_env, (
        "test assumption stale: docker-compose.yml's backend service now overrides "
        "SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS -- this test assumes docker-compose's "
        "single backend container relies on config.py's default instead"
    )

    replicas, backend_env = _backend_deployment_replicas_and_env()
    assert replicas > 1, (
        "test assumption stale: k8s/base/backend-deployment.yaml no longer runs "
        "multiple backend replicas -- the per-pod cap divide-down this test "
        "checks for is only needed while replicas > 1"
    )

    assert "SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS" in backend_env, (
        "k8s/base/backend-deployment.yaml's backend container does not override "
        "SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS -- with replicas: "
        f"{replicas} and no override, each pod independently falls back to "
        f"config.py's default of {single_instance_ceiling}, so the real "
        f"platform-wide ceiling silently becomes {replicas * single_instance_ceiling} "
        f"concurrent scans/nmap subprocesses instead of the intended "
        f"{single_instance_ceiling} every other deployment path enforces."
    )

    per_pod_cap = int(backend_env["SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS"])
    platform_wide_ceiling = per_pod_cap * replicas
    assert platform_wide_ceiling == single_instance_ceiling, (
        f"k8s/base/backend-deployment.yaml's per-pod SECURITY_ASSESSMENT_MAX_CONCURRENT_SCANS="
        f"{per_pod_cap} x replicas={replicas} = {platform_wide_ceiling} concurrent "
        f"scans/nmap subprocesses platform-wide, which does not match the "
        f"{single_instance_ceiling}-scan ceiling every other deployment path "
        "(docker-compose.yml, the Windows/Linux installers) enforces -- "
        "recompute the per-pod value so the product stays equal."
    )
