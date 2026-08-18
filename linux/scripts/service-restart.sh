#!/usr/bin/env bash
# Restarts HORIZON GRID. Mirrors windows/scripts/Service-Restart.ps1 -- the
# usual first step for troubleshooting.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"
hg_assert_root

if [ ! -f "$HORIZON_GRID_ENV_FILE" ]; then
    echo "No configuration found. Run 'sudo horizon-grid configure' first."
    exit 1
fi

echo "Restarting HORIZON GRID..."
if ! hg_invoke_docker_compose restart; then
    echo "Failed to restart. See $HORIZON_GRID_LOG_DIR for details."
    exit 1
fi

echo "Waiting for the backend to become healthy..."
healthy=false
for _ in $(seq 1 40); do
    if hg_test_backend_health; then healthy=true; break; fi
    sleep 3
done

if [ "$healthy" = "true" ]; then
    echo "Platform is running."
else
    echo "Containers restarted but the backend did not report healthy in time. Check 'horizon-grid status' shortly."
fi
