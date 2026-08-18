#!/usr/bin/env bash
# Stops HORIZON GRID (all Docker Compose services), without deleting any
# data -- containers are stopped, not removed with -v. Mirrors
# windows/scripts/Service-Stop.ps1.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"
hg_assert_root

if [ ! -f "$HORIZON_GRID_ENV_FILE" ]; then
    echo "No configuration found -- nothing to stop."
    exit 0
fi

echo "Stopping HORIZON GRID..."
if hg_invoke_docker_compose stop; then
    echo "Platform stopped."
else
    echo "Failed to stop cleanly. See $HORIZON_GRID_LOG_DIR for details."
    exit 1
fi
