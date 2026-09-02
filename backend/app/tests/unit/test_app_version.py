"""Regression guard for a real, live-found gap: backend/app/main.py's
_APP_VERSION constant was never bumped alongside windows/installer.iss and
linux/debian/control for six releases (0.3.1-0.3.8 all shipped still
reporting "0.3.0" via /health and the OpenAPI schema), because there is no
single canonical version source shared across Python/Inno/Debian. This
can't prevent the next manual-bump miss, but it turns it into an immediate,
loud test failure instead of a silent drift discovered live in production.
"""
import re
from pathlib import Path

import pytest

from app.main import _APP_VERSION

# Real environment constraint (matches this project's own already-documented
# "host-only test files silently skip in-container" pattern): the backend
# container only ever bind-mounts ./backend as /app -- windows/ and linux/
# are siblings of backend/ in the real repo, but simply do not exist inside
# the container's filesystem at all. Skipping loudly (not silently) when
# they're not found, rather than assuming a container-relative path that
# would never resolve there, so this only ever runs (and only ever matters)
# from a host-side run against the full repo checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_INSTALLER_ISS = _REPO_ROOT / "windows" / "installer.iss"
_DEBIAN_CONTROL = _REPO_ROOT / "linux" / "debian" / "control"


def _read_installer_version() -> str:
    text = _INSTALLER_ISS.read_text(encoding="utf-8")
    match = re.search(r'#define MyAppVersion "([^"]+)"', text)
    assert match, "could not find #define MyAppVersion in windows/installer.iss"
    return match.group(1)


def _read_debian_control_version() -> str:
    text = _DEBIAN_CONTROL.read_text(encoding="utf-8")
    match = re.search(r"^Version:\s*(\S+)", text, re.MULTILINE)
    assert match, "could not find Version: in linux/debian/control"
    return match.group(1)


@pytest.mark.skipif(not _INSTALLER_ISS.exists(), reason="windows/installer.iss not mounted in this environment (host-only check)")
def test_app_version_matches_windows_installer_version():
    assert _APP_VERSION == _read_installer_version(), (
        f"_APP_VERSION ({_APP_VERSION}) does not match windows/installer.iss's MyAppVersion "
        f"({_read_installer_version()}) -- bump whichever one is stale."
    )


@pytest.mark.skipif(not _DEBIAN_CONTROL.exists(), reason="linux/debian/control not mounted in this environment (host-only check)")
def test_app_version_matches_linux_debian_control_version():
    assert _APP_VERSION == _read_debian_control_version(), (
        f"_APP_VERSION ({_APP_VERSION}) does not match linux/debian/control's Version "
        f"({_read_debian_control_version()}) -- bump whichever one is stale."
    )
