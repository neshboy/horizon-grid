"""Regression guard for a real, live-reproduced bug: k8s/base/frontend-deployment.yaml's
Deployment ran `command: ["npm", "start"]` (i.e. `next start`), but nothing in the k8s
deployment path ever runs `next build` -- frontend/Dockerfile only does `npm install` +
`COPY . .`, and the manifest itself never built anything before starting the server.

Confirmed live: `docker run --rm horizon-grid-frontend:latest sh -c "ls .next; npm start"`
printed `ls: .next: No such file or directory` followed by Next's own
"Could not find a production build in the '.next' directory" error. Every frontend pod
deployed via `kubectl apply -k k8s/base` crash-looped immediately and indefinitely, so the
web UI was entirely unreachable.

Separately, even "just add `npm run build`" is not sufficient: frontend/next.config.js sets
`output: "standalone"`, which `next start` does NOT correctly serve (Next's own server prints
'"next start" does not work with "output: standalone" configuration' and falls back to the
non-standalone server). docker-compose.prod.yml's `frontend.command` already solves this for
the docker-compose production path (build, copy `public/` + `.next/static` into the standalone
output, then run `node .next/standalone/server.js` directly) -- the k8s manifest needs the same
sequence.
"""
from pathlib import Path

import pytest
import yaml

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern -- see
# test_app_version.py): the backend container only ever bind-mounts ./backend
# as /app -- k8s/ and frontend/ are siblings of backend/ in the real repo, but
# simply do not exist inside the container's filesystem at all. Skipping
# loudly (not silently) when they're not found, rather than assuming a
# container-relative path that would never resolve there, so this only ever
# runs (and only ever matters) from a host-side run against the full repo
# checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_FRONTEND_DEPLOYMENT = _REPO_ROOT / "k8s" / "base" / "frontend-deployment.yaml"
_NEXT_CONFIG = _REPO_ROOT / "frontend" / "next.config.js"
_COMPOSE_PROD = _REPO_ROOT / "docker-compose.prod.yml"

_SKIP_REASON = "k8s/frontend files not mounted in this environment (host-only check)"


def _frontend_container_command() -> str:
    docs = list(yaml.safe_load_all(_FRONTEND_DEPLOYMENT.read_text(encoding="utf-8")))
    deployment = next(doc for doc in docs if doc and doc.get("kind") == "Deployment")
    containers = deployment["spec"]["template"]["spec"]["containers"]
    frontend_container = next(c for c in containers if c["name"] == "frontend")
    command = frontend_container.get("command") or []
    assert command, "frontend container has no command at all in k8s/base/frontend-deployment.yaml"
    return " ".join(command)


@pytest.mark.skipif(not _FRONTEND_DEPLOYMENT.exists(), reason=_SKIP_REASON)
def test_frontend_deployment_command_runs_a_build_before_starting():
    command = _frontend_container_command()
    assert "build" in command, (
        "k8s/base/frontend-deployment.yaml's frontend container command does not run a "
        "build step before starting the server. frontend/Dockerfile never runs `next build` "
        "either, so there is no '.next' production build for `next start`/`npm start` to "
        "serve and every pod will crash-loop immediately on startup. "
        f"command was: {command!r}"
    )


@pytest.mark.skipif(
    not (_FRONTEND_DEPLOYMENT.exists() and _NEXT_CONFIG.exists()),
    reason=_SKIP_REASON,
)
def test_frontend_deployment_command_uses_standalone_server_not_next_start():
    next_config = _NEXT_CONFIG.read_text(encoding="utf-8")
    assert '"standalone"' in next_config, (
        "test assumption stale: frontend/next.config.js no longer sets output: standalone "
        "-- if this changed, plain `next start` may now be correct and this test should be "
        "revisited"
    )

    command = _frontend_container_command()
    # `next start` (and therefore plain `npm start`) does not correctly serve a
    # `output: "standalone"` build -- the traced standalone server must be run directly,
    # after copying in public/ and .next/static (both intentionally excluded from the
    # standalone trace by Next itself).
    assert ".next/standalone/server.js" in command, (
        "k8s/base/frontend-deployment.yaml's command does not run the standalone server "
        "entrypoint (node .next/standalone/server.js), but next.config.js sets "
        "output: \"standalone\" -- `next start`/`npm start` does not correctly serve a "
        f"standalone build. command was: {command!r}"
    )
    assert "npm start" not in command and "next start" not in command


@pytest.mark.skipif(
    not (_FRONTEND_DEPLOYMENT.exists() and _COMPOSE_PROD.exists()),
    reason=_SKIP_REASON,
)
def test_frontend_deployment_command_matches_compose_prod_standalone_pattern():
    # docker-compose.prod.yml already solved this exact problem for the docker-compose
    # production path -- guard against the k8s manifest drifting away from that same,
    # already-verified sequence (build -> copy public/+static into standalone -> run
    # standalone server.js directly).
    compose_prod_text = _COMPOSE_PROD.read_text(encoding="utf-8")
    assert "node .next/standalone/server.js" in compose_prod_text, (
        "test assumption stale: docker-compose.prod.yml no longer runs the standalone "
        "server directly -- if this changed intentionally, the k8s manifest's command "
        "should be revisited too"
    )

    command = _frontend_container_command()
    for required_fragment in ("npm run build", ".next/standalone/.next/static", "node .next/standalone/server.js"):
        assert required_fragment in command, (
            f"k8s/base/frontend-deployment.yaml's command is missing {required_fragment!r}, "
            "which docker-compose.prod.yml's already-verified frontend.command relies on -- "
            f"command was: {command!r}"
        )
