"""Regression guard for a real, live-found gap: docker-compose.prod.yml's
backend service override replaced the base docker-compose.yml's ENTIRE
command, silently dropping the `msfrpcd -f -P ... &` prefix that starts the
real Metasploit RPC daemon. docker-compose.prod.yml is exactly what every
real Windows/Linux installer's compose invocation actually uses (see that
file's own header comment) -- so the Exploit Validation feature was broken
on every real installed deployment despite working fine in the dev-only
`docker-compose.yml`-alone setup, and nothing caught it.

Static text check only (no YAML parsing needed, no Docker required) --
matches this project's own established "host-only, skip loudly if the file
isn't mounted in this environment" pattern (see test_app_version.py).
"""
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_COMPOSE_PROD = _REPO_ROOT / "docker-compose.prod.yml"


@pytest.mark.skipif(not _COMPOSE_PROD.exists(), reason="docker-compose.prod.yml not mounted in this environment (host-only check)")
def test_prod_compose_backend_command_still_starts_msfrpcd():
    text = _COMPOSE_PROD.read_text(encoding="utf-8")
    # Crude but effective: find the backend service's `command:` block and
    # confirm msfrpcd is started within it, not just present anywhere in
    # the file (e.g. in a comment).
    backend_start = text.index("backend:")
    next_service_markers = [text.index(m, backend_start + 1) for m in ("\n  celery_worker:", "\n  celery_beat:", "\n  frontend:") if m in text[backend_start + 1:]]
    backend_end = min(next_service_markers) if next_service_markers else len(text)
    backend_block = text[backend_start:backend_end]
    assert "msfrpcd" in backend_block, (
        "docker-compose.prod.yml's backend service command no longer starts msfrpcd -- "
        "this breaks Exploit Validation on every real installed deployment."
    )
