#!/usr/bin/env bash
# Regression tests for common.sh's hg_detect_host_gateway_override --
# standalone, run-directly test script (mirrors linux/test/e2e-test.sh's
# own pass/fail reporting style), NOT part of the .deb package or the E2E
# rig -- this is unit-level, no Docker/root/real distro container needed.
#
# Stubs both real inputs the function reads, so this passes identically
# on any Linux box (or CI container) regardless of whether it's actually
# running inside WSL2:
#   - /proc/version / /proc/sys/kernel/osrelease -- via
#     HORIZON_GRID_PROC_VERSION_FILE / HORIZON_GRID_OSRELEASE_FILE,
#     common.sh's own test-override variables, pointed at temp files here.
#   - the `ip` command -- via a shell function named `ip` defined in this
#     same script (bash resolves a function before searching PATH, so
#     this is picked up by hg_detect_host_gateway_override's own `ip
#     route` call without needing a fake executable earlier on PATH).
#
# Usage: bash linux/scripts/test_host_gateway_detection.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$SCRIPT_DIR/common.sh"

TMPDIR_T="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_T"' EXIT

PASS_COUNT=0
FAIL_COUNT=0
pass() { echo "[PASS] $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "[FAIL] $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

# Default: no stub `ip` at all -- any case expected to short-circuit before
# ever calling `ip route` will fail loudly (via `ip` being undefined/real)
# rather than silently passing for the wrong reason.
unset -f ip 2>/dev/null || true

# --- Case 1: WSL2 detected (via /proc/version) + a valid "ip route"
# default line -> returns the real gateway IP. ---
printf 'Linux version 5.15.90.1-microsoft-standard-WSL2 (...) \n' >"$TMPDIR_T/proc_version_wsl2"
: >"$TMPDIR_T/osrelease_empty"
ip() { printf 'default via 172.30.192.1 dev eth0 proto kernel\n172.30.192.0/20 dev eth0 proto kernel scope link src 172.30.198.5\n'; }
export -f ip
HORIZON_GRID_PROC_VERSION_FILE="$TMPDIR_T/proc_version_wsl2" \
HORIZON_GRID_OSRELEASE_FILE="$TMPDIR_T/osrelease_empty" \
    result="$(hg_detect_host_gateway_override)"
if [ "$result" = "172.30.192.1" ]; then
    pass "WSL2 detected + valid default route -> returns the gateway IP (172.30.192.1)"
else
    fail "WSL2 detected + valid default route -> expected '172.30.192.1', got '$result'"
fi
unset -f ip

# --- Case 2: WSL2 NOT detected -> returns empty, and must not even call
# `ip route` (stub raises if invoked, so a silent false-pass can't hide a
# real bug). ---
printf 'Linux version 6.8.0-45-generic (Ubuntu 24.04) ...\n' >"$TMPDIR_T/proc_version_plain"
printf '6.8.0-45-generic\n' >"$TMPDIR_T/osrelease_plain"
ip() { echo "TEST BUG: ip route should not be called when WSL2 is not detected" >&2; return 1; }
export -f ip
HORIZON_GRID_PROC_VERSION_FILE="$TMPDIR_T/proc_version_plain" \
HORIZON_GRID_OSRELEASE_FILE="$TMPDIR_T/osrelease_plain" \
    result="$(hg_detect_host_gateway_override)"
if [ -z "$result" ]; then
    pass "WSL2 NOT detected -> returns empty (bare-metal Linux path preserved)"
else
    fail "WSL2 NOT detected -> expected empty, got '$result'"
fi
unset -f ip

# --- Case 2b: same as above but via the osrelease file only (some kernel
# builds put the WSL marker there instead of /proc/version) -- sanity
# check that detection isn't ONLY reading /proc/version. ---
printf 'Linux version 5.15.0-generic ...\n' >"$TMPDIR_T/proc_version_generic"
printf '5.15.90.1-microsoft-standard-WSL2\n' >"$TMPDIR_T/osrelease_wsl2"
ip() { printf 'default via 172.30.192.1 dev eth0\n'; }
export -f ip
HORIZON_GRID_PROC_VERSION_FILE="$TMPDIR_T/proc_version_generic" \
HORIZON_GRID_OSRELEASE_FILE="$TMPDIR_T/osrelease_wsl2" \
    result="$(hg_detect_host_gateway_override)"
if [ "$result" = "172.30.192.1" ]; then
    pass "WSL2 detected via osrelease-only -> returns the gateway IP"
else
    fail "WSL2 detected via osrelease-only -> expected '172.30.192.1', got '$result'"
fi
unset -f ip

# --- Case 3: WSL2 detected but "ip route" parsing fails/returns no
# default line -> returns empty, must not crash. ---
ip() { printf '172.30.192.0/20 dev eth0 proto kernel scope link src 172.30.198.5\n'; }
export -f ip
HORIZON_GRID_PROC_VERSION_FILE="$TMPDIR_T/proc_version_wsl2" \
HORIZON_GRID_OSRELEASE_FILE="$TMPDIR_T/osrelease_empty" \
    result="$(hg_detect_host_gateway_override)"
rc=$?
if [ $rc -eq 0 ] && [ -z "$result" ]; then
    pass "WSL2 detected + no default route line -> returns empty, no crash"
else
    fail "WSL2 detected + no default route line -> expected empty/rc=0, got '$result'/rc=$rc"
fi
unset -f ip

# --- Case 3b: WSL2 detected but the `ip` command itself fails outright
# (nonzero exit, no stdout) -> still returns empty, must not crash. ---
ip() { return 1; }
export -f ip
HORIZON_GRID_PROC_VERSION_FILE="$TMPDIR_T/proc_version_wsl2" \
HORIZON_GRID_OSRELEASE_FILE="$TMPDIR_T/osrelease_empty" \
    result="$(hg_detect_host_gateway_override)"
rc=$?
if [ $rc -eq 0 ] && [ -z "$result" ]; then
    pass "WSL2 detected + 'ip' command failing outright -> returns empty, no crash"
else
    fail "WSL2 detected + 'ip' command failing -> expected empty/rc=0, got '$result'/rc=$rc"
fi
unset -f ip

echo ""
echo "===================================================================="
echo " $PASS_COUNT passed, $FAIL_COUNT failed"
echo "===================================================================="
[ "$FAIL_COUNT" -eq 0 ]
