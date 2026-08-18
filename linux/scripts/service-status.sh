#!/usr/bin/env bash
# Shows whether the platform is installed, running, and healthy. Mirrors
# windows/scripts/Service-Status.ps1. Invoked by `horizon-grid status` and
# the systemd unit's own `systemctl status horizon-grid` (this script is a
# richer, application-level view on top of that).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"
hg_assert_root

echo "HORIZON GRID -- Service Status"
echo "============================================"

if [ ! -f "$HORIZON_GRID_ENV_FILE" ]; then
    echo "Not configured yet. Run 'sudo horizon-grid configure' to set up the platform."
    exit 1
fi

echo ""
echo "Containers:"
hg_sync_compose_env_file
(
    cd "$HORIZON_GRID_APP_REPO_DIR" || exit 1
    docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$HORIZON_GRID_ENV_FILE" ps
)

echo ""
echo "Health checks:"
if hg_test_backend_health; then
    echo "  Backend API  : OK"
else
    echo "  Backend API  : NOT RESPONDING"
fi
if hg_test_frontend_health; then
    echo "  Web interface: OK"
else
    echo "  Web interface: NOT RESPONDING"
fi

echo ""
echo "Docker Engine:"
if docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
    echo "  Running ($(docker info --format '{{.ServerVersion}}' 2>/dev/null))"
else
    echo "  NOT RUNNING -- start the docker service first (systemctl start docker)"
fi

echo ""
echo "systemd unit (if enabled):"
if command -v systemctl >/dev/null 2>&1; then
    systemctl is-enabled horizon-grid 2>/dev/null | sed 's/^/  enabled: /' || echo "  enabled: unknown"
    systemctl is-active horizon-grid 2>/dev/null | sed 's/^/  active:  /' || echo "  active:  unknown"
else
    echo "  systemctl not available on this system"
fi
