"""Regression guard for a real, confirmed bug: k8s/base/backend-deployment.yaml's
Deployment command never starts msfrpcd, so the Pentest Suite's Metasploit-backed
exploit-validation feature is completely non-functional under k8s even though the
backend image has the full Metasploit Framework installed and the Secret/README
both document MSF_RPC_PASSWORD as required.

backend/app/pentest/msf_client.py's MsfRpcClient / backend/app/core/config.py's
Settings default msf_rpc_host to "127.0.0.1" -- i.e. the client always expects
msfrpcd to be running inside the SAME container as the backend process, not
reachable via any separate Service. docker-compose.yml's backend service
satisfies this explicitly via its command, which starts
`msfrpcd -f -P "$$MSF_RPC_PASSWORD" -S -a 127.0.0.1 -p 55553 -U msf &` before
`alembic upgrade head && uvicorn ...`. k8s/base/backend-deployment.yaml's command
was only `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port
8000` -- msfrpcd was never invoked anywhere in that pod, despite using the
identical backend image, so MsfRpcClient's `_raw_call` connected to
http://127.0.0.1:55553/api/ inside the backend pod, got connection-refused, and
raised `MsfRpcError('msfrpcd unreachable: ...')` on every single exploit-
validation call.
"""
from pathlib import Path

import pytest
import yaml

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_k8s_frontend_deployment_build.py / test_k8s_ai_backend_secrets.py): the
# backend container only ever bind-mounts ./backend as /app -- k8s/ is a
# sibling of backend/ in the real repo, but simply does not exist inside the
# container's filesystem at all. Skipping loudly (not silently) when it's not
# found, rather than assuming a container-relative path that would never
# resolve there, so this only ever runs (and only ever matters) from a
# host-side run against the full repo checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_DEPLOYMENT = _REPO_ROOT / "k8s" / "base" / "backend-deployment.yaml"
_COMPOSE = _REPO_ROOT / "docker-compose.yml"

_SKIP_REASON = "k8s/backend-deployment.yaml not mounted in this environment (host-only check)"


def _backend_container_command() -> str:
    docs = list(yaml.safe_load_all(_BACKEND_DEPLOYMENT.read_text(encoding="utf-8")))
    deployment = next(doc for doc in docs if doc and doc.get("kind") == "Deployment")
    containers = deployment["spec"]["template"]["spec"]["containers"]
    backend_container = next(c for c in containers if c["name"] == "backend")
    command = backend_container.get("command") or []
    assert command, "backend container has no command at all in k8s/base/backend-deployment.yaml"
    return " ".join(command)


@pytest.mark.skipif(not _BACKEND_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_backend_deployment_command_starts_msfrpcd():
    command = _backend_container_command()
    assert "msfrpcd" in command, (
        "k8s/base/backend-deployment.yaml's backend container command never starts "
        "msfrpcd, but backend/app/pentest/msf_client.py's MsfRpcClient (via "
        "backend/app/core/config.py's msf_rpc_host default of 127.0.0.1) always "
        "connects to msfrpcd on 127.0.0.1:55553 inside its own container -- every "
        "Pentest Suite exploit-validation call will fail with 'msfrpcd unreachable' "
        f"under this manifest. command was: {command!r}"
    )


@pytest.mark.skipif(not _BACKEND_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_backend_deployment_starts_msfrpcd_before_uvicorn_and_bound_to_loopback():
    command = _backend_container_command()
    assert "msfrpcd" in command, "msfrpcd startup missing -- see test_backend_deployment_command_starts_msfrpcd"

    msf_index = command.index("msfrpcd")
    uvicorn_index = command.index("uvicorn")
    assert msf_index < uvicorn_index, (
        "msfrpcd must be started before uvicorn (backgrounded with '&', mirroring "
        f"docker-compose.yml) so it is listening by the time the app serves requests. command: {command!r}"
    )
    # Bound to loopback only (matches docker-compose.yml and secret.example.yaml's
    # own documentation of this) -- never exposed outside the pod.
    assert "-a 127.0.0.1" in command and "-p 55553" in command, (
        f"msfrpcd must bind to 127.0.0.1:55553 to match msf_rpc_host/msf_rpc_port defaults "
        f"in backend/app/core/config.py. command: {command!r}"
    )


@pytest.mark.skipif(
    not (_BACKEND_DEPLOYMENT.exists() and _COMPOSE.exists()), reason=_SKIP_REASON
)
def test_backend_deployment_msfrpcd_matches_compose_pattern():
    # docker-compose.yml already solved this exact problem for the docker-compose
    # path -- guard against the k8s manifest drifting away from that same,
    # already-verified startup sequence (msfrpcd backgrounded, then alembic, then
    # uvicorn).
    compose_text = _COMPOSE.read_text(encoding="utf-8")
    assert "msfrpcd -f -P" in compose_text, (
        "test assumption stale: docker-compose.yml no longer starts msfrpcd this way "
        "-- if this changed intentionally, k8s/base/backend-deployment.yaml's command "
        "should be revisited too"
    )

    command = _backend_container_command()
    for required_fragment in ("msfrpcd -f -P", "-S -a 127.0.0.1 -p 55553 -U msf", "alembic upgrade head", "uvicorn app.main:app"):
        assert required_fragment in command, (
            f"k8s/base/backend-deployment.yaml's command is missing {required_fragment!r}, "
            f"which docker-compose.yml's already-verified backend command relies on -- command was: {command!r}"
        )
