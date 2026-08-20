#!/usr/bin/env bash
# Periodic health watchdog. Mirrors windows/scripts/Watchdog.ps1 -- a
# systemd timer (horizon-grid-watchdog.timer) runs this every few minutes.
#
# Real gap this closes: horizon-grid.service is Type=oneshot with
# RemainAfterExit=yes -- it runs `docker compose up -d` once at boot and is
# then reported "active" by systemd regardless of what happens to the
# containers afterward, so systemd's own restart-on-failure can never fire
# for this unit. Docker's own restart:unless-stopped policy (added to every
# service in docker-compose.yml in the same pass this script was added)
# correctly recovers a crashed/OOM-killed CONTAINER, but nothing previously
# noticed if the containers stayed "running" while the application inside
# them was genuinely broken (e.g. hung without exiting). This script is
# that backstop -- deliberately conservative: only acts when
# hg_test_backend_health (a real /health/detailed dependency check) fails,
# and only ever attempts a restart, never anything destructive.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"

WATCHDOG_LOG="$HORIZON_GRID_LOG_DIR/watchdog.log"

hg_watchdog_log() {
    mkdir -p "$HORIZON_GRID_LOG_DIR"
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$WATCHDOG_LOG"
}

if [ ! -f "$HORIZON_GRID_ENV_FILE" ]; then
    # Not configured yet -- nothing to watch, and not worth a log line every
    # few minutes for a completely normal pre-configuration state.
    exit 0
fi

if hg_test_backend_health; then
    exit 0
fi

hg_watchdog_log "Backend failed health check (/health/detailed). Attempting recovery restart."
if ! hg_invoke_docker_compose restart; then
    hg_watchdog_log "docker compose restart failed."
fi

sleep 20
if hg_test_backend_health; then
    hg_watchdog_log "Recovery restart succeeded -- backend healthy again."
else
    hg_watchdog_log "Recovery restart did NOT resolve the issue -- backend still unhealthy. Manual attention needed; see 'horizon-grid status' for detail."
fi
