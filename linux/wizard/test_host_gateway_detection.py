#!/usr/bin/env python3
"""Regression tests for setup_wizard.py's _detect_host_gateway_override().

No existing test file/convention exists yet for the standalone wizard
script (linux/test/ holds shell-driven E2E fixtures, not unit tests for
setup_wizard.py itself), so this is a minimal, dependency-free
unittest module living next to the script it tests -- run directly
(no pytest requirement) via:

    python3 linux/wizard/test_host_gateway_detection.py

Covers the three cases called out in the fix's own requirements:
  1. WSL2 detected (via /proc/version) + a valid "ip route" default line
     -> returns the real gateway IP.
  2. WSL2 NOT detected (neither /proc/version nor osrelease mention it)
     -> returns "" (empty), regardless of what "ip route" would say --
     "ip route" must not even be consulted in this case on a real
     bare-metal Linux box (it might not exist there for a NAT gateway),
     so this also asserts subprocess.run is never called.
  3. WSL2 detected but "ip route" parsing fails/returns no default line
     (or the command itself fails) -> returns "" and must not raise.

Real /proc/version and /proc/sys/kernel/osrelease reads, and the real
`ip route` subprocess call, are mocked out here -- these tests must pass
identically on Windows, macOS, or any Linux box, not just inside WSL2.
"""
import io
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import setup_wizard  # noqa: E402


def _fake_open_factory(proc_version=None, osrelease=None):
    """Returns a function suitable for patching builtins.open that serves
    canned content for /proc/version and /proc/sys/kernel/osrelease, and
    raises OSError (like the real thing does off-WSL2/off-Linux, or under
    this test's own sandboxed environment) for anything else.
    """
    real_open = open

    def _fake_open(path, *args, **kwargs):
        if path == "/proc/version":
            if proc_version is None:
                raise OSError("no such file: /proc/version")
            return io.StringIO(proc_version)
        if path == "/proc/sys/kernel/osrelease":
            if osrelease is None:
                raise OSError("no such file: /proc/sys/kernel/osrelease")
            return io.StringIO(osrelease)
        return real_open(path, *args, **kwargs)

    return _fake_open


class DetectHostGatewayOverrideTests(unittest.TestCase):
    def test_wsl2_detected_via_proc_version_returns_gateway_ip(self):
        fake_open = _fake_open_factory(
            proc_version="Linux version 5.15.90.1-microsoft-standard-WSL2 ...",
            osrelease=None,
        )
        fake_ip_route = mock.Mock(
            return_value=subprocess.CompletedProcess(
                args=["ip", "route"], returncode=0,
                stdout="default via 172.30.192.1 dev eth0 proto kernel\n"
                       "172.30.192.0/20 dev eth0 proto kernel scope link src 172.30.198.5\n",
            )
        )
        with mock.patch("builtins.open", fake_open), \
             mock.patch.object(setup_wizard.subprocess, "run", fake_ip_route):
            result = setup_wizard._detect_host_gateway_override()
        self.assertEqual(result, "172.30.192.1")
        fake_ip_route.assert_called_once()

    def test_wsl2_detected_via_osrelease_only_returns_gateway_ip(self):
        # /proc/version present but silent about Microsoft/WSL; osrelease
        # is what actually carries it on some kernel builds.
        fake_open = _fake_open_factory(
            proc_version="Linux version 5.15.0-generic ...",
            osrelease="5.15.90.1-microsoft-standard-WSL2",
        )
        fake_ip_route = mock.Mock(
            return_value=subprocess.CompletedProcess(
                args=["ip", "route"], returncode=0,
                stdout="default via 172.30.192.1 dev eth0\n",
            )
        )
        with mock.patch("builtins.open", fake_open), \
             mock.patch.object(setup_wizard.subprocess, "run", fake_ip_route):
            result = setup_wizard._detect_host_gateway_override()
        self.assertEqual(result, "172.30.192.1")

    def test_not_wsl2_returns_empty_and_never_calls_ip_route(self):
        fake_open = _fake_open_factory(
            proc_version="Linux version 6.8.0-generic (Ubuntu) ...",
            osrelease="6.8.0-generic",
        )
        fake_ip_route = mock.Mock(
            side_effect=AssertionError("ip route must not be called when WSL2 isn't detected")
        )
        with mock.patch("builtins.open", fake_open), \
             mock.patch.object(setup_wizard.subprocess, "run", fake_ip_route):
            result = setup_wizard._detect_host_gateway_override()
        self.assertEqual(result, "")
        fake_ip_route.assert_not_called()

    def test_no_proc_files_at_all_returns_empty(self):
        # e.g. running the wizard's own unit tests on a non-Linux dev
        # machine, or any environment where these procfs paths simply
        # don't exist -- must not raise, must resolve to "not WSL2".
        fake_open = _fake_open_factory(proc_version=None, osrelease=None)
        fake_ip_route = mock.Mock(side_effect=AssertionError("must not be called"))
        with mock.patch("builtins.open", fake_open), \
             mock.patch.object(setup_wizard.subprocess, "run", fake_ip_route):
            result = setup_wizard._detect_host_gateway_override()
        self.assertEqual(result, "")

    def test_wsl2_detected_but_ip_route_has_no_default_line_returns_empty(self):
        fake_open = _fake_open_factory(
            proc_version="Linux version 5.15.90.1-microsoft-standard-WSL2 ...",
            osrelease=None,
        )
        fake_ip_route = mock.Mock(
            return_value=subprocess.CompletedProcess(
                args=["ip", "route"], returncode=0,
                stdout="172.30.192.0/20 dev eth0 proto kernel scope link src 172.30.198.5\n",
            )
        )
        with mock.patch("builtins.open", fake_open), \
             mock.patch.object(setup_wizard.subprocess, "run", fake_ip_route):
            result = setup_wizard._detect_host_gateway_override()
        self.assertEqual(result, "")

    def test_wsl2_detected_but_ip_route_command_fails_returns_empty(self):
        fake_open = _fake_open_factory(
            proc_version="Linux version 5.15.90.1-microsoft-standard-WSL2 ...",
            osrelease=None,
        )
        fake_ip_route = mock.Mock(
            return_value=subprocess.CompletedProcess(
                args=["ip", "route"], returncode=1, stdout="",
            )
        )
        with mock.patch("builtins.open", fake_open), \
             mock.patch.object(setup_wizard.subprocess, "run", fake_ip_route):
            result = setup_wizard._detect_host_gateway_override()
        self.assertEqual(result, "")

    def test_wsl2_detected_but_ip_missing_raises_oserror_returns_empty(self):
        fake_open = _fake_open_factory(
            proc_version="Linux version 5.15.90.1-microsoft-standard-WSL2 ...",
            osrelease=None,
        )
        fake_ip_route = mock.Mock(side_effect=FileNotFoundError("ip: command not found"))
        with mock.patch("builtins.open", fake_open), \
             mock.patch.object(setup_wizard.subprocess, "run", fake_ip_route):
            result = setup_wizard._detect_host_gateway_override()
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
