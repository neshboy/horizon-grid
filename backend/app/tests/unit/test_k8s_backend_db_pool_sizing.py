"""Regression guard for a real bug: k8s/base/configmap.yaml is envFrom'd
identically by the backend, celery-worker, AND celery-beat Deployments, and
never set DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW at all. That meant k8s backend
pods silently fell back to backend/app/core/config.py's small 5+5 default --
sized for celery-worker/celery-beat's minimal DB use, per that file's own
comment -- instead of the much larger pool docker-compose.yml explicitly
gives the backend service (DB_POOL_SIZE=30/DB_POOL_MAX_OVERFLOW=20) for real
concurrent user-facing HTTP traffic, where docker-compose.yml's own comment
explains every authenticated request already costs 2 connections (one from
the auth dependency, one from the service-layer session), not 1.

Confirmed live by reading the actual manifests before the fix:
k8s/base/backend-deployment.yaml's container had no `env:` block at all (only
`envFrom` pointing at the shared ConfigMap/Secret), and neither
DB_POOL_SIZE nor DB_POOL_MAX_OVERFLOW appeared anywhere in
k8s/base/configmap.yaml or k8s/base/secret.example.yaml.

The fix deliberately does NOT add these keys to the shared ConfigMap --
that's envFrom'd identically by celery-worker/celery-beat, so it would also
bump those two lightweight, DB-light processes to the backend's much larger
pool (wasting Postgres connections for no benefit, and risking exceeding
max_connections once replica counts are multiplied in). Instead it adds a
backend-only `env:` override on backend-deployment.yaml's container, mirroring
exactly how docker-compose.yml scopes this override to just the `backend`
service.
"""
from pathlib import Path

import pytest
import yaml

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_k8s_ai_backend_secrets.py / test_k8s_frontend_deployment_build.py): the
# backend container only ever bind-mounts ./backend as /app -- k8s/ and
# docker-compose.yml are siblings of backend/ in the real repo, but simply do
# not exist inside the container's filesystem at all. Skipping loudly (not
# silently) when they're not found, rather than assuming a container-relative
# path that would never resolve there, so this only ever runs (and only ever
# matters) from a host-side run against the full repo checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_DEPLOYMENT = _REPO_ROOT / "k8s" / "base" / "backend-deployment.yaml"
_CELERY_WORKER_DEPLOYMENT = _REPO_ROOT / "k8s" / "base" / "celery-worker-deployment.yaml"
_CELERY_BEAT_DEPLOYMENT = _REPO_ROOT / "k8s" / "base" / "celery-beat-deployment.yaml"
_CONFIGMAP = _REPO_ROOT / "k8s" / "base" / "configmap.yaml"
_COMPOSE = _REPO_ROOT / "docker-compose.yml"

_SKIP_REASON = "k8s/docker-compose files not mounted in this environment (host-only check)"


def _container_env(path: Path, container_name: str) -> dict:
    docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    deployment = next(doc for doc in docs if doc and doc.get("kind") == "Deployment")
    containers = deployment["spec"]["template"]["spec"]["containers"]
    container = next(c for c in containers if c["name"] == container_name)
    return {item["name"]: item.get("value") for item in (container.get("env") or [])}


def _configmap_data() -> dict:
    doc = yaml.safe_load(_CONFIGMAP.read_text(encoding="utf-8"))
    return doc.get("data") or {}


def _compose_backend_db_pool_env() -> dict:
    doc = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    backend_env = doc["services"]["backend"]["environment"]
    return {
        "DB_POOL_SIZE": str(backend_env["DB_POOL_SIZE"]),
        "DB_POOL_MAX_OVERFLOW": str(backend_env["DB_POOL_MAX_OVERFLOW"]),
    }


@pytest.mark.skipif(
    not (_BACKEND_DEPLOYMENT.exists() and _COMPOSE.exists()), reason=_SKIP_REASON
)
def test_backend_deployment_sets_db_pool_size_matching_docker_compose():
    expected = _compose_backend_db_pool_env()
    assert expected["DB_POOL_SIZE"] != "5" and expected["DB_POOL_MAX_OVERFLOW"] != "5", (
        "test assumption stale: docker-compose.yml's backend service no longer "
        "overrides DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW away from config.py's "
        "celery-sized default -- if intentional, revisit this test"
    )

    backend_env = _container_env(_BACKEND_DEPLOYMENT, "backend")
    missing = [k for k in expected if k not in backend_env]
    assert not missing, (
        "k8s/base/backend-deployment.yaml's backend container does not set "
        f"{missing!r} -- backend pods fall back to backend/app/core/config.py's "
        "small 5+5 default (sized for celery-worker/celery-beat's minimal DB "
        "use), not the pool size docker-compose.yml deliberately gives the "
        "user-facing backend for concurrent HTTP traffic (each authenticated "
        "request already costs 2 connections, not 1), causing k8s backend "
        "pods to exhaust their pool under traffic docker-compose.yml's sizing "
        "was calculated to support."
    )
    assert backend_env["DB_POOL_SIZE"] == expected["DB_POOL_SIZE"], (
        f"k8s backend DB_POOL_SIZE={backend_env['DB_POOL_SIZE']!r} does not match "
        f"docker-compose.yml's backend DB_POOL_SIZE={expected['DB_POOL_SIZE']!r}"
    )
    assert backend_env["DB_POOL_MAX_OVERFLOW"] == expected["DB_POOL_MAX_OVERFLOW"], (
        f"k8s backend DB_POOL_MAX_OVERFLOW={backend_env['DB_POOL_MAX_OVERFLOW']!r} does "
        f"not match docker-compose.yml's backend DB_POOL_MAX_OVERFLOW="
        f"{expected['DB_POOL_MAX_OVERFLOW']!r}"
    )


@pytest.mark.skipif(not _CONFIGMAP.exists(), reason=_SKIP_REASON)
def test_configmap_does_not_set_db_pool_size_for_all_three_workloads():
    # The shared ConfigMap is envFrom'd identically by backend, celery-worker,
    # AND celery-beat (see all three Deployments' envFrom.configMapRef) -- if
    # DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW were set here instead of on the
    # backend Deployment directly, celery-worker/celery-beat would also be
    # bumped to the backend's much larger pool, wasting Postgres connections
    # for two processes that barely touch the DB.
    configmap_keys = set(_configmap_data().keys())
    assert "DB_POOL_SIZE" not in configmap_keys and "DB_POOL_MAX_OVERFLOW" not in configmap_keys, (
        "k8s/base/configmap.yaml now sets DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW directly -- "
        "since this ConfigMap is envFrom'd identically by celery-worker/celery-beat too, "
        "that also bumps those lightweight processes to the backend's larger pool size. "
        "Keep this override on backend-deployment.yaml's own container `env:` instead, "
        "matching docker-compose.yml's backend-only scoping."
    )


@pytest.mark.skipif(
    not (_CELERY_WORKER_DEPLOYMENT.exists() and _CELERY_BEAT_DEPLOYMENT.exists()),
    reason=_SKIP_REASON,
)
def test_celery_deployments_do_not_override_db_pool_size():
    for path, name in (
        (_CELERY_WORKER_DEPLOYMENT, "celery-worker"),
        (_CELERY_BEAT_DEPLOYMENT, "celery-beat"),
    ):
        env = _container_env(path, name)
        assert "DB_POOL_SIZE" not in env and "DB_POOL_MAX_OVERFLOW" not in env, (
            f"k8s/base/{path.name}'s {name} container overrides DB_POOL_SIZE/"
            "DB_POOL_MAX_OVERFLOW -- docker-compose.yml deliberately leaves the "
            "matching celery_worker/celery_beat services on config.py's small "
            "default since they barely touch the DB; mirror that here rather than "
            "bumping them to the backend's larger pool."
        )
