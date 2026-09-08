"""Regression guard for a real, confirmed bug: k8s/base/backend-deployment.yaml's
readinessProbe and livenessProbe both hit the dependency-free GET /health
endpoint instead of GET /health/detailed, unlike every other deployment path in
this repo.

backend/app/main.py's GET /health docstring says it is "[d]eliberately
dependency-free" and "confirmed live to still return 200 with Postgres fully
stopped" -- i.e. it never checks Postgres/Redis at all. Its GET /health/detailed
docstring says explicitly: "Windows/Linux watchdog scripts and the Docker
Compose healthcheck: block should point here, not at the plain /health above."
docker-compose.yml's backend healthcheck: does exactly that (`curl -f
http://localhost:8000/health/detailed`, with its own comment noting it
deliberately avoids plain /health), and windows/scripts/Watchdog.ps1 /
linux/scripts/watchdog.sh both restart the backend based on a real
/health/detailed dependency check too.

k8s/base/backend-deployment.yaml's readinessProbe/livenessProbe used
`httpGet: path: /health` -- so if Postgres (or Redis) goes down, GET /health
still returns 200 unconditionally, both probes keep reporting the pod as
Ready/live, and the backend Service keeps routing real user traffic to a pod
that will 500 on every DB-backed endpoint, instead of k8s pulling it out of the
Service's endpoint list the way every other deployment path already would.
"""
from pathlib import Path

import pytest
import yaml

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_k8s_backend_deployment_msfrpcd.py / test_k8s_backend_db_pool_sizing.py):
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


def _backend_container_probes() -> dict:
    docs = list(yaml.safe_load_all(_BACKEND_DEPLOYMENT.read_text(encoding="utf-8")))
    deployment = next(doc for doc in docs if doc and doc.get("kind") == "Deployment")
    containers = deployment["spec"]["template"]["spec"]["containers"]
    backend_container = next(c for c in containers if c["name"] == "backend")
    probes = {
        "readinessProbe": backend_container.get("readinessProbe"),
        "livenessProbe": backend_container.get("livenessProbe"),
    }
    assert probes["readinessProbe"] and probes["livenessProbe"], (
        "backend container in k8s/base/backend-deployment.yaml is missing a "
        f"readinessProbe or livenessProbe entirely: {probes!r}"
    )
    return probes


@pytest.mark.skipif(not _BACKEND_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_backend_deployment_readiness_and_liveness_probes_use_detailed_health_check():
    probes = _backend_container_probes()
    for probe_name, probe in probes.items():
        path = probe["httpGet"]["path"]
        assert path == "/health/detailed", (
            f"k8s/base/backend-deployment.yaml's {probe_name} hits {path!r} instead of "
            "/health/detailed. Per backend/app/main.py's own docstrings, plain /health "
            "is deliberately dependency-free and still returns 200 with Postgres fully "
            "stopped -- so a probe pointed there can never detect a DB-broken backend "
            "pod, and k8s will keep routing real user traffic to it via the backend "
            "Service even while every DB-backed endpoint 500s."
        )


@pytest.mark.skipif(
    not (_BACKEND_DEPLOYMENT.exists() and _COMPOSE.exists()), reason=_SKIP_REASON
)
def test_backend_deployment_health_probes_match_docker_compose_healthcheck():
    # docker-compose.yml already solved this exact problem for the docker-compose
    # path -- guard against the k8s manifest drifting away from that same,
    # already-verified dependency-aware health check.
    compose_doc = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    compose_healthcheck = " ".join(compose_doc["services"]["backend"]["healthcheck"]["test"])
    assert "/health/detailed" in compose_healthcheck, (
        "test assumption stale: docker-compose.yml's backend healthcheck no longer "
        "targets /health/detailed -- if intentional, revisit this test"
    )

    probes = _backend_container_probes()
    for probe_name, probe in probes.items():
        assert probe["httpGet"]["path"] == "/health/detailed", (
            f"k8s/base/backend-deployment.yaml's {probe_name} does not match "
            "docker-compose.yml's dependency-aware /health/detailed healthcheck"
        )
