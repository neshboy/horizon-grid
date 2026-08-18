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

FRONTEND_PORT="$(hg_read_env_var HOST_PORT_FRONTEND)"; FRONTEND_PORT="${FRONTEND_PORT:-3000}"
URL="http://localhost:${FRONTEND_PORT}"

open_browser() {
    if command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        xdg-open "$URL" >/dev/null 2>&1 &
    else
        echo "No desktop session detected -- open this URL yourself: $URL"
    fi
}

# Already up? Skip every startup step -- the common case, shouldn't pay for
# a sudo prompt or a wait it doesn't need.
if hg_test_backend_health && hg_test_frontend_health; then
    open_browser
    exit 0
fi

hg_assert_root

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

open_browser
