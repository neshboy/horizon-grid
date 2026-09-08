"""Regression guard for a real bug: k8s/base/celery-worker-deployment.yaml's
Deployment ran `celery -A app.workers.celery_app worker --loglevel=info` with
no --concurrency flag at all, silently re-introducing the exact OOM/memory-bomb
bug that docker-compose.yml's celery_worker.command comment documents fixing
(see test_celery_worker_concurrency_is_bounded.py's own docstring for the full
live repro: with no --concurrency, Celery's prefork pool defaults to
multiprocessing.cpu_count(), forking one child process per host core
regardless of the container's own memory limit).

The k8s Deployment is at least as exposed to this as the docker-compose
service was pre-fix -- real k8s worker nodes routinely have more logical
CPUs than a modest single-machine docker-compose/dev host, and the pod's
own resources.limits.memory here is capped at 1Gi, the same ceiling the
docker-compose comment says this exact scenario blows through. A pod
deployed via `kubectl apply -k k8s/base` onto such a node would be OOM-killed
by the kubelet before ever picking up a task, then restart and repeat
(CrashLoopBackOff).
"""
import re
from pathlib import Path

import pytest
import yaml

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_k8s_ai_backend_secrets.py / test_k8s_frontend_deployment_build.py): the
# backend container only ever bind-mounts ./backend as /app -- k8s/ is a
# sibling of backend/ in the real repo, but simply does not exist inside the
# container's filesystem at all. Skipping loudly (not silently) when it's not
# found, rather than assuming a container-relative path that would never
# resolve there, so this only ever runs (and only ever matters) from a
# host-side run against the full repo checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CELERY_WORKER_DEPLOYMENT = _REPO_ROOT / "k8s" / "base" / "celery-worker-deployment.yaml"

_SKIP_REASON = "k8s/base/celery-worker-deployment.yaml not mounted in this environment (host-only check)"

_CONCURRENCY_RE = re.compile(r"--concurrency[= ]\$?\{?([A-Z0-9_]+:-)?(\d+)\}?")


def _celery_worker_container() -> dict:
    doc = yaml.safe_load(_CELERY_WORKER_DEPLOYMENT.read_text(encoding="utf-8"))
    containers = doc["spec"]["template"]["spec"]["containers"]
    return next(c for c in containers if c["name"] == "celery-worker")


def _rendered_command(container: dict) -> str:
    command = container.get("command") or []
    assert command, "celery-worker container has no command at all in k8s/base/celery-worker-deployment.yaml"
    return " ".join(command)


@pytest.mark.skipif(not _CELERY_WORKER_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_celery_worker_deployment_command_pins_a_concurrency_flag():
    container = _celery_worker_container()
    command = _rendered_command(container)
    assert "celery" in command, (
        f"test assumption stale: celery-worker's command no longer runs celery: {command!r}"
    )

    match = _CONCURRENCY_RE.search(command)
    assert match, (
        "k8s/base/celery-worker-deployment.yaml's celery-worker command has no "
        "--concurrency flag -- without it, Celery's prefork pool defaults to "
        "multiprocessing.cpu_count(), which on a many-core k8s node forks one "
        "child process per core regardless of this container's "
        f"resources.limits.memory, risking an OOM-kill/CrashLoopBackOff. command={command!r}"
    )


@pytest.mark.skipif(not _CELERY_WORKER_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_celery_worker_deployment_concurrency_is_a_small_bounded_number_not_host_core_count():
    container = _celery_worker_container()
    command = _rendered_command(container)
    match = _CONCURRENCY_RE.search(command)
    assert match, "expected --concurrency to be present (see other test in this file)"

    concurrency = int(match.group(2))

    # Sanity bound, not a precisely-tuned ceiling -- mirrors
    # test_celery_worker_concurrency_is_bounded.py's own bound for the
    # docker-compose service this Deployment is a translation of: this
    # worker runs a single lightweight, already-internally-concurrent task
    # type, so it should never need anywhere close to a many-core node's
    # full core count to fit under its memory limit.
    assert 1 <= concurrency <= 16, (
        f"celery-worker Deployment's --concurrency default of {concurrency} is outside "
        "the expected small, fixed range (1-16) -- if this is intentional, confirm the "
        "pod still has real headroom under resources.limits.memory under a burst of "
        "concurrent scheduled tasks, not just at idle."
    )


@pytest.mark.skipif(not _CELERY_WORKER_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_celery_worker_deployment_still_has_its_memory_limit():
    # Belt-and-suspenders: the fix is only meaningful paired with the memory
    # limit it's sized against -- guard against that being dropped too.
    container = _celery_worker_container()
    assert (container.get("resources") or {}).get("limits", {}).get("memory"), (
        "celery-worker Deployment lost its resources.limits.memory"
    )


@pytest.mark.skipif(not _CELERY_WORKER_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_celery_worker_deployment_concurrency_matches_docker_compose_default():
    # Cross-check against the docker-compose fix this Deployment is meant to
    # mirror, so the two paths don't silently drift apart (e.g. someone
    # raising docker-compose.yml's default without ever touching k8s again).
    compose_file = _REPO_ROOT / "docker-compose.yml"
    if not compose_file.exists():
        pytest.skip(_SKIP_REASON)

    compose_doc = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    compose_command = compose_doc["services"]["celery_worker"]["command"]
    compose_match = re.search(r"--concurrency=\$\{[A-Z0-9_]+:-(\d+)\}", compose_command)
    assert compose_match, (
        "test assumption stale: docker-compose.yml's celery_worker command no longer "
        f"has the expected --concurrency=${{VAR:-N}} form: {compose_command!r}"
    )
    compose_default = int(compose_match.group(1))

    container = _celery_worker_container()
    k8s_command = _rendered_command(container)
    k8s_match = _CONCURRENCY_RE.search(k8s_command)
    assert k8s_match, "expected --concurrency to be present (see other test in this file)"
    k8s_default = int(k8s_match.group(2))

    assert k8s_default == compose_default, (
        f"k8s celery-worker Deployment's --concurrency default ({k8s_default}) no longer "
        f"matches docker-compose.yml's celery_worker default ({compose_default}) -- the two "
        "deployment paths have drifted apart."
    )
