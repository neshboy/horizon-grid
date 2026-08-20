#!/usr/bin/env bash
# Verifies the host machine can actually run HORIZON GRID before the .deb's
# postinst / the setup wizard proceeds. Mirrors windows/scripts/Check-Prerequisites.ps1
# check-for-check: OS/distro support, root privileges, RAM, disk space, Docker
# Engine installed AND running (checked via `docker info`, not package/service
# presence -- a package can be installed with a daemon that isn't actually
# up), Docker Compose v2, and the required TCP ports free.
#
# Exit code 0 = all hard checks passed. Exit code 1 = one or more hard
# failures. Emits one JSON object to stdout (and nothing else) so a calling
# script/wizard can parse results programmatically; human-readable detail
# goes to stderr.

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
. "$SCRIPT_DIR/common.sh"

REQUIRED_PORTS="${1:-3000 8000 5433 6379 7475 7688 9200}"
MIN_FREE_DISK_GB=8

CHECKS_JSON="[]"
OK=true

add_check() {
    # $1=name $2=passed(true/false) $3=detail $4=hard(true/false, default true)
    #
    # Real bug fixed: this used to interpolate $passed/$hard directly into
    # Python SOURCE as bare identifiers (`'passed': $passed`) -- bash's
    # lowercase true/false are not valid Python literals (Python's are
    # True/False), so EVERY call raised a silent NameError, caught only by
    # this function's own `2>/dev/null || echo "$CHECKS_JSON"` fallback.
    # The human-readable [PASS]/[FAIL] stderr lines below and the script's
    # overall exit code (bash's own $OK, tracked independently) both still
    # worked, which is exactly why this went unnoticed -- CHECKS_JSON's
    # "checks" array was silently empty in every real run, discovered only
    # once something actually parsed it programmatically (this mission's
    # new setup_wizard.py prerequisite gate). Fixed by passing every field
    # through the environment instead of interpolating into Python source
    # at all -- also removes the need for $detail's own sed-escaping, since
    # env vars need no shell-quoting-for-Python-string-literal handling.
    local name="$1" passed="$2" detail="$3" hard="${4:-true}"
    CHECKS_JSON=$(NAME="$name" PASSED="$passed" DETAIL="$detail" HARD="$hard" CHECKS_JSON="$CHECKS_JSON" python3 -c "
import json, os
checks = json.loads(os.environ['CHECKS_JSON'])
checks.append({
    'name': os.environ['NAME'],
    'passed': os.environ['PASSED'] == 'true',
    'detail': os.environ['DETAIL'],
    'hard': os.environ['HARD'] == 'true',
})
print(json.dumps(checks))
" 2>/dev/null || echo "$CHECKS_JSON")
    if [ "$hard" = "true" ] && [ "$passed" = "false" ]; then
        OK=false
    fi
    printf '  [%s] %s -- %s\n' "$([ "$passed" = "true" ] && echo PASS || echo FAIL)" "$name" "$detail" >&2
}

# --- Supported distribution ---
DISTRO_ID="unknown"
DISTRO_VERSION="unknown"
if [ -r /etc/os-release ]; then
    . /etc/os-release
    DISTRO_ID="${ID:-unknown}"
    DISTRO_VERSION="${VERSION_ID:-unknown}"
fi
SUPPORTED="false"
case "${DISTRO_ID}:${DISTRO_VERSION}" in
    ubuntu:24.04|ubuntu:22.04|debian:12) SUPPORTED="true" ;;
esac
add_check "Supported distribution" "$SUPPORTED" \
    "Detected ${DISTRO_ID} ${DISTRO_VERSION} -- tested targets are Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, and Debian 12. Other distributions may work (this is a standard Docker Compose + systemd application) but have not been verified." \
    "false"

# --- Architecture ---
ARCH="$(uname -m)"
ARCH_OK="false"
[ "$ARCH" = "x86_64" ] && ARCH_OK="true"
add_check "x86_64 architecture" "$ARCH_OK" "Detected $ARCH -- every base image this platform builds on (postgres:16-alpine, redis:7-alpine, neo4j:5-community, opensearch, python:3.12-slim, node:20-alpine) ships an amd64 build; arm64 has not been tested." "false"

# --- Root / sudo ---
IS_ROOT="false"
[ "$(id -u)" -eq 0 ] && IS_ROOT="true"
add_check "Running as root" "$IS_ROOT" "$([ "$IS_ROOT" = "true" ] && echo "Running as root/sudo" || echo "Not running as root -- re-run with sudo.")"

# --- RAM (same practical floor as the Windows check -- soft, not a hard
# platform requirement, but the 8-container stack is heavy below it) ---
TOTAL_RAM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
TOTAL_RAM_GB=$(awk -v kb="$TOTAL_RAM_KB" 'BEGIN { printf "%.1f", kb/1024/1024 }')
RAM_OK="false"
awk -v gb="$TOTAL_RAM_GB" 'BEGIN { exit !(gb >= 7.5) }' && RAM_OK="true"
add_check "At least 8 GB RAM" "$RAM_OK" "${TOTAL_RAM_GB} GB detected -- the full Docker Compose stack (8 containers) is heavy on less." "false"

# --- Disk space on the filesystem that will hold /opt (installer target) ---
FREE_KB=$(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $4}')
FREE_KB="${FREE_KB:-0}"
FREE_GB=$(awk -v kb="$FREE_KB" 'BEGIN { printf "%.1f", kb/1024/1024 }')
DISK_OK="false"
awk -v gb="$FREE_GB" -v min="$MIN_FREE_DISK_GB" 'BEGIN { exit !(gb >= min) }' && DISK_OK="true"
add_check "Sufficient free disk space" "$DISK_OK" "${FREE_GB} GB free on the filesystem holding /opt (need at least ${MIN_FREE_DISK_GB} GB for Docker images + data)."

# --- Docker Engine installed ---
DOCKER_PRESENT="false"
DOCKER_PATH=""
if command -v docker >/dev/null 2>&1; then
    DOCKER_PRESENT="true"
    DOCKER_PATH="$(command -v docker)"
fi
add_check "Docker Engine installed" "$DOCKER_PRESENT" "$([ "$DOCKER_PRESENT" = "true" ] && echo "$DOCKER_PATH" || echo "docker not found on PATH -- install Docker Engine, e.g. https://docs.docker.com/engine/install/${DISTRO_ID}/ (do not use Docker Desktop on a Linux server -- Docker Engine + the compose plugin is the correct install there).")"

# --- Docker daemon actually reachable ---
DOCKER_RUNNING="false"
DOCKER_DETAIL="Docker Engine is installed but the daemon isn't reachable (not running, or this user/root can't reach the socket)."
if [ "$DOCKER_PRESENT" = "true" ]; then
    if VER_JSON=$(docker info --format '{{json .ServerVersion}}' 2>/dev/null) && [ -n "$VER_JSON" ]; then
        DOCKER_RUNNING="true"
        DOCKER_DETAIL="Docker engine ${VER_JSON//\"/} is running."
    fi
fi
add_check "Docker daemon is running" "$DOCKER_RUNNING" "$DOCKER_DETAIL"

# --- Docker Compose v2 available (docker-compose.yml uses the `docker
# compose` plugin syntax, not the standalone docker-compose v1 binary) ---
COMPOSE_OK="false"
COMPOSE_DETAIL="docker compose (v2 plugin) not available."
if [ "$DOCKER_RUNNING" = "true" ]; then
    if COMPOSE_VER=$(docker compose version --short 2>/dev/null) && [ -n "$COMPOSE_VER" ]; then
        COMPOSE_OK="true"
        COMPOSE_DETAIL="docker compose v${COMPOSE_VER}"
    fi
fi
add_check "Docker Compose v2 available" "$COMPOSE_OK" "$COMPOSE_DETAIL"

# --- Required ports free (soft -- the setup wizard's port-review step lets
# the administrator remap a conflicting one, same as the Windows wizard) ---
for port in $REQUIRED_PORTS; do
    if hg_test_port_free "$port"; then
        add_check "Port $port available" "true" "Free" "false"
    else
        OWNER=""
        if command -v ss >/dev/null 2>&1; then
            OWNER=$(ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $NF}' | head -n1)
        fi
        add_check "Port $port available" "false" "In use${OWNER:+ (by $OWNER)} -- the setup wizard will offer an alternate port." "false"
    fi
done

# --- Existing installation detection (informational, not pass/fail) ---
EXISTING="false"
[ -f "$HORIZON_GRID_ENV_FILE" ] && EXISTING="true"
add_check "Existing installation detected" "true" "$([ "$EXISTING" = "true" ] && echo "Found existing configuration at $HORIZON_GRID_ENV_FILE -- this will be an upgrade/reconfigure." || echo "No existing installation found -- this will be a fresh install.")" "false"

python3 -c "
import json
print(json.dumps({'ok': $OK, 'checks': json.loads('''$CHECKS_JSON''')}))
" 2>/dev/null || echo "{\"ok\": $OK, \"checks\": $CHECKS_JSON}"

[ "$OK" = "true" ] && exit 0 || exit 1
