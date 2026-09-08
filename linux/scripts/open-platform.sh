#!/usr/bin/env bash
# Starts the platform if needed, waits until it's healthy, then opens it in
# the default browser (or, on a headless machine with no desktop session,
# just prints the URL -- xdg-open has nothing to hand off to there). Mirrors
# windows/scripts/Open-Platform.ps1 and the desktop launcher's real job:
# "click the icon" is the whole recovery story a user needs, whether that
# click came from a desktop menu entry or `horizon-grid open` in a terminal.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"

# Real gap found live during overnight QA: hg_read_env_var reads
# $HORIZON_GRID_ENV_FILE, which is chmod 600 root-only (see
# hg_init_data_directories) -- called from THIS script's non-root fast
# path (before hg_assert_root below), it silently fails (permission
# denied) and falls back to the hardcoded default port, exactly the class
# of bug hg_test_backend_health/hg_test_frontend_health's own comments
# already describe fixing for OTHER callers that run as root by the time
# they call it. A customized HOST_PORT_FRONTEND/HOST_PORT_BACKEND meant
# this fast path could never actually detect an already-running, healthy
# platform -- it always checked the default port instead, silently found
# nothing there, and dropped into the full root-requiring startup sequence
# even when the platform was already up and fine. Discovering the REAL
# published port straight from the Docker daemon (which already knows a
# running container's actual port mapping) needs no privileged file read
# at all.
hg_discover_running_port() {
    # $1 = internal container port, $2 = name filter substring.
    local internal_port="$1" name_filter="$2"
    docker ps --filter "name=${name_filter}" --format '{{.Ports}}' 2>/dev/null \
        | grep -o "[0-9.]*:[0-9]*->${internal_port}/tcp" | head -n1 | sed -E 's/.*:([0-9]+)->.*/\1/'
}

FRONTEND_PORT="$(hg_discover_running_port 3000 frontend)"; FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="$(hg_discover_running_port 8000 backend)"; BACKEND_PORT="${BACKEND_PORT:-8000}"
URL="http://localhost:${FRONTEND_PORT}"

open_browser() {
    if command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        xdg-open "$URL" >/dev/null 2>&1 &
    else
        echo "No desktop session detected -- open this URL yourself: $URL"
    fi
}

# Already up? Skip every startup step -- the common case, shouldn't pay for
# a sudo prompt or a wait it doesn't need. Pass the discovered URLs
# explicitly -- calling these with no argument would fall back to each
# function's OWN internal (root-locked-.env-dependent) port discovery.
# Guarded on HORIZON_GRID_SKIP_BROWSER too: this same branch is also the
# first thing the pkexec-elevated re-exec below hits on its own re-run of
# this script, and that instance (running as root) must never call
# open_browser itself.
if hg_test_backend_health "http://localhost:${BACKEND_PORT}" && hg_test_frontend_health "$URL"; then
    if [ "${HORIZON_GRID_SKIP_BROWSER:-}" != "1" ]; then
        open_browser
    fi
    exit 0
fi

# Real gap found live during overnight QA: hg_assert_root has no self-
# elevation mechanism at all -- unlike Windows's Assert-Elevated, which
# relaunches itself via UAC's -Verb RunAs, this just prints "re-run with
# sudo" to stderr and exits. A desktop-launched icon (this script's own
# stated primary use case -- "click the icon") has no visible terminal to
# show that message in: double-clicking it on the cold-start path (platform
# not already running) silently did nothing at all, with zero indication
# anything was wrong. pkexec is the standard Linux desktop equivalent of
# UAC (a graphical password prompt), used here only when a graphical
# session is actually present -- a pure-terminal invocation (e.g. over SSH,
# no DISPLAY) falls through to hg_assert_root's existing plain message,
# which a terminal user can actually see and act on. Only the root-
# requiring startup steps run elevated; control returns to THIS, still
# non-root, process to open the browser -- xdg-open should never run as
# root (no session bus to the real desktop session, and poor practice even
# where it happens to work).
if [ "$(id -u)" -ne 0 ]; then
    if command -v pkexec >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        pkexec env "DISPLAY=${DISPLAY:-}" "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}" HORIZON_GRID_SKIP_BROWSER=1 "$0" "$@"
        ELEVATED_EXIT=$?
        if [ "$ELEVATED_EXIT" -ne 0 ]; then
            echo "Failed to start the platform (elevated step exited with code $ELEVATED_EXIT)." >&2
            exit 1
        fi
        if hg_test_backend_health "http://localhost:${BACKEND_PORT}" && hg_test_frontend_health "$URL"; then
            open_browser
            exit 0
        fi
        echo "The platform did not report healthy after the elevated startup step. Run 'horizon-grid status' to check what's wrong." >&2
        exit 1
    fi
    hg_assert_root
fi

if [ ! -f "$HORIZON_GRID_ENV_FILE" ]; then
    echo "Not configured yet. Run 'sudo horizon-grid configure' first."
    exit 1
fi

echo "Checking the Docker service..."
if ! docker info >/dev/null 2>&1; then
    echo "Starting the docker service..."
    systemctl start docker 2>/dev/null || true
    for _ in $(seq 1 20); do
        docker info >/dev/null 2>&1 && break
        sleep 3
    done
    if ! docker info >/dev/null 2>&1; then
        echo "The Docker service did not become ready in time. Start it manually (sudo systemctl start docker) and try again."
        exit 1
    fi
fi

echo "Starting platform services..."
if ! hg_invoke_docker_compose up -d; then
    echo "Failed to start. See $HORIZON_GRID_LOG_DIR for details, or run 'horizon-grid status'."
    exit 1
fi

echo "Waiting for the platform to become healthy..."
healthy=false
for _ in $(seq 1 60); do
    if hg_test_backend_health && hg_test_frontend_health; then healthy=true; break; fi
    sleep 3
done

if [ "$healthy" != "true" ]; then
    echo "The platform started but did not report healthy within 3 minutes. Run 'horizon-grid status' to check what's wrong."
    exit 1
fi

# Set only on the pkexec-elevated re-exec above -- that instance is running
# as root and must not try to open a browser itself; the original,
# non-root parent process does that instead once this elevated step exits.
if [ "${HORIZON_GRID_SKIP_BROWSER:-}" != "1" ]; then
    open_browser
fi
