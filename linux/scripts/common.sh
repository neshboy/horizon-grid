#!/usr/bin/env bash
# Shared constants and helper functions used by every Linux packaging script
# (setup wizard's shell helpers, service control, diagnostics, backup). Sourced,
# not run directly. Mirrors windows/scripts/Common.ps1's role and layout
# 1:1 -- same split (read-mostly app under an installed-package directory,
# writable data under a separate, root-locked location), translated to FHS
# conventions instead of Program Files / ProgramData:
#
#   /opt/horizon-grid/app/        -- the actual repo (backend/, frontend/,
#                                     docker-compose.yml, etc.), installed by
#                                     the .deb package. Read-mostly; docker
#                                     compose builds images from here.
#
#   /etc/horizon-grid/.env        -- the real environment file docker-compose.yml
#                                     reads (env_file: .env, plus the ${VAR}
#                                     substitutions docker-compose.yml itself
#                                     uses for ports/DB credentials). Root-only
#                                     (0600, root:root) -- it holds real API
#                                     keys, DB passwords, and the JWT secret.
#
#   /var/lib/horizon-grid/backups/ -- pg_dump snapshots taken before an
#                                      upgrade or on demand.
#
#   /var/log/horizon-grid/setup.log -- wizard/service log (human-readable).
#
# set -u is deliberately NOT set globally here (this file is sourced into
# scripts with their own strictness settings); every function below still
# guards its own required variables explicitly.

HORIZON_GRID_APP_NAME="HORIZON GRID"

# Overridable via environment for testing (mirrors Common.ps1's
# $env:IOC_INSTALL_DIR override) -- lets the automated Linux test suite point
# a whole run at a scratch directory without touching /opt or /etc for real.
HORIZON_GRID_INSTALL_DIR="${HORIZON_GRID_INSTALL_DIR:-/opt/horizon-grid}"
HORIZON_GRID_APP_REPO_DIR="${HORIZON_GRID_APP_REPO_DIR:-$HORIZON_GRID_INSTALL_DIR/app}"
HORIZON_GRID_CONFIG_DIR="${HORIZON_GRID_CONFIG_DIR:-/etc/horizon-grid}"
HORIZON_GRID_DATA_DIR="${HORIZON_GRID_DATA_DIR:-/var/lib/horizon-grid}"
HORIZON_GRID_BACKUPS_DIR="${HORIZON_GRID_BACKUPS_DIR:-$HORIZON_GRID_DATA_DIR/backups}"
HORIZON_GRID_LOG_DIR="${HORIZON_GRID_LOG_DIR:-/var/log/horizon-grid}"
HORIZON_GRID_ENV_FILE="${HORIZON_GRID_ENV_FILE:-$HORIZON_GRID_CONFIG_DIR/.env}"
HORIZON_GRID_SETUP_LOG="${HORIZON_GRID_SETUP_LOG:-$HORIZON_GRID_LOG_DIR/setup.log}"

hg_log() {
    # $1=message, $2=level (default INFO) -- mirrors Common.ps1's Write-SetupLog.
    local msg="$1" level="${2:-INFO}"
    mkdir -p "$(dirname "$HORIZON_GRID_SETUP_LOG")" 2>/dev/null || true
    printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$msg" >>"$HORIZON_GRID_SETUP_LOG" 2>/dev/null || true
}

hg_assert_root() {
    # Mirrors Common.ps1's Assert-Elevated. Every script that reads/writes
    # $HORIZON_GRID_ENV_FILE or manages containers needs real root -- unlike
    # Windows's split-token UAC nuance, a plain Linux `sudo`/root check is
    # sufficient here since there is no equivalent filtered-token gap.
    if [ "$(id -u)" -ne 0 ]; then
        echo "This command needs root privileges (it manages files under $HORIZON_GRID_CONFIG_DIR and $HORIZON_GRID_DATA_DIR, and starts/stops containers). Re-run with sudo." >&2
        exit 1
    fi
}

hg_init_data_directories() {
    # Mirrors Common.ps1's Initialize-DataDirectories. icacls's
    # Administrators+SYSTEM-only grant becomes a plain root:root 0700 --
    # there is no direct Linux analog of "Administrators group" needed here
    # since this whole toolchain assumes root/sudo execution throughout,
    # matching the Windows installer's own admin-required model.
    local dir
    for dir in "$HORIZON_GRID_CONFIG_DIR" "$HORIZON_GRID_DATA_DIR" "$HORIZON_GRID_BACKUPS_DIR" "$HORIZON_GRID_LOG_DIR"; do
        mkdir -p "$dir"
        chown root:root "$dir"
        chmod 700 "$dir"
    done
}

hg_new_random_secret() {
    # Cryptographically random secret for JWT_SECRET_KEY / generated DB
    # passwords -- mirrors Common.ps1's New-RandomSecret (RNGCryptoServiceProvider).
    # /dev/urandom via openssl is the direct Linux equivalent CSPRNG; falls
    # back to Python's secrets module if openssl isn't on PATH for some reason
    # (it always is on Debian/Ubuntu base images, but no reason not to be safe).
    local bytes="${1:-48}"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 "$bytes" | tr -d '+/=\n'
    else
        python3 -c "import secrets; print(secrets.token_urlsafe($bytes))"
    fi
}

hg_test_port_free() {
    # Mirrors Common.ps1's Test-PortFree. Uses /proc/net/tcp{,6} rather than
    # shelling out to `ss`/`netstat`, which are not guaranteed present on a
    # minimal container/server image -- /proc/net/tcp always is, since it's
    # the kernel's own interface, not a userspace tool that has to be
    # installed. Port numbers in /proc/net/tcp are hex, local address field 2.
    local port="$1" hexport
    hexport=$(printf '%04X' "$port")
    if [ -r /proc/net/tcp ] && grep -qi ":${hexport} " /proc/net/tcp 2>/dev/null; then
        return 1
    fi
    if [ -r /proc/net/tcp6 ] && grep -qi ":${hexport} " /proc/net/tcp6 2>/dev/null; then
        return 1
    fi
    return 0
}

hg_find_free_port() {
    # Mirrors Common.ps1's Find-FreePort -- returns $1 if free, else the next
    # free port upward, capped at 50 attempts.
    local preferred="$1" i candidate
    for i in $(seq 0 49); do
        candidate=$((preferred + i))
        if hg_test_port_free "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    echo "Could not find a free port near $preferred after 50 attempts." >&2
    return 1
}

hg_sync_compose_env_file() {
    # Mirrors Common.ps1's Sync-ComposeEnvFile and its own extensive comment
    # on WHY: docker-compose.yml's env_file: .env directive resolves relative
    # to the compose PROJECT DIRECTORY ($HORIZON_GRID_APP_REPO_DIR), completely
    # independent of the top-level --env-file CLI flag (--env-file only
    # controls ${VAR} substitution inside the YAML itself). A copy has to
    # exist at $HORIZON_GRID_APP_REPO_DIR/.env for Compose to find it via
    # env_file: -- and that copy gets the same root-only lock as the
    # ProgramData/etc original, rather than inheriting /opt's normally
    # world-readable permissions (confirmed the analogous Windows failure
    # mode this avoids: Program Files is BUILTIN\Users:(RX) by default; on
    # Linux, /opt is typically 0755 root:root, i.e. world-readable, so an
    # unprotected copy there would leak every credential to any local user).
    if [ -f "$HORIZON_GRID_ENV_FILE" ]; then
        cp -f "$HORIZON_GRID_ENV_FILE" "$HORIZON_GRID_APP_REPO_DIR/.env"
        chown root:root "$HORIZON_GRID_APP_REPO_DIR/.env"
        chmod 600 "$HORIZON_GRID_APP_REPO_DIR/.env"
    fi
}

hg_invoke_docker_compose() {
    # Mirrors Common.ps1's Invoke-DockerCompose -- always the same working
    # directory, always the same --env-file, so no caller can accidentally
    # run against the wrong .env or the wrong compose project.
    hg_sync_compose_env_file
    (
        cd "$HORIZON_GRID_APP_REPO_DIR" || exit 1
        docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$HORIZON_GRID_ENV_FILE" "$@"
    )
}

hg_remove_stale_database_volume_if_fresh_install() {
    # Mirrors Common.ps1's Remove-StaleDatabaseVolumeIfFreshInstall -- see
    # that function's own extensive comment for the full root-cause story
    # (Postgres only applies POSTGRES_PASSWORD to an empty data directory; a
    # leftover volume from an earlier abandoned install attempt, with no
    # matching .env, will silently mismatch a freshly generated password and
    # crash-loop the backend on every start). Only call with "true" when no
    # existing .env was found to recover a real password from.
    local is_fresh_install="$1"
    [ "$is_fresh_install" = "true" ] || return 0

    local stale_volume_id
    stale_volume_id=$(docker volume ls -q \
        --filter "label=com.docker.compose.project=app" \
        --filter "label=com.docker.compose.volume=postgres_data" 2>/dev/null || true)
    if [ -n "$stale_volume_id" ]; then
        hg_log "Fresh install: found a leftover Postgres volume ($stale_volume_id) from an earlier install attempt with no matching .env -- removing it so the new password can initialize cleanly."
        docker volume rm "$stale_volume_id" >>"$HORIZON_GRID_SETUP_LOG" 2>&1 || true
    fi
}

hg_test_backend_health() {
    # Mirrors Common.ps1's Test-BackendHealth. HORIZON_GRID_BACKEND_HOST
    # defaults to "localhost", which is correct for a real install (the
    # script always runs on the same host as the containers it's checking).
    # Only the automated Docker-sibling-container test harness overrides it
    # to host.docker.internal, since in that rig the containers are actually
    # published on the outer Docker host, not inside the test container's
    # own network namespace -- see the Linux QA report's "Test Environment"
    # section for the full explanation of why that override exists at all.
    local host="${HORIZON_GRID_BACKEND_HOST:-localhost}"
    local port
    port="$(hg_read_env_var HOST_PORT_BACKEND)"; port="${port:-8000}"
    # Real gap fixed: every caller here (watchdog.sh, service-status.sh,
    # service-start.sh, service-restart.sh, open-platform.sh) calls this
    # with no argument, so hardcoding 8000 meant a customized
    # HOST_PORT_BACKEND (set on the wizard's Ports page if 8000 conflicted
    # with something else on the machine) was checked at the WRONG port
    # forever -- either falsely reporting unhealthy, or silently checking
    # an unrelated service that happens to be listening on 8000. Now reads
    # the real configured value via hg_read_env_var, same source of truth
    # every other script already uses for POSTGRES_USER/POSTGRES_DB.
    local base_url="${1:-http://${host}:${port}}"
    # /health/detailed, not plain /health -- confirmed live that plain
    # /health returns 200 unconditionally even with Postgres fully stopped,
    # so it can never tell this watchdog whether the backend can actually
    # serve a real request. /health/detailed genuinely pings Postgres and
    # Redis and returns 503 if the database is unreachable.
    curl -fsS --max-time 5 "${base_url}/health/detailed" >/dev/null 2>&1
}

hg_test_frontend_health() {
    # Mirrors Common.ps1's Test-FrontendHealth. See hg_test_backend_health's
    # comment above for HORIZON_GRID_BACKEND_HOST and the same real
    # customized-port gap, fixed the same way here for HOST_PORT_FRONTEND.
    local host="${HORIZON_GRID_BACKEND_HOST:-localhost}"
    local port
    port="$(hg_read_env_var HOST_PORT_FRONTEND)"; port="${port:-3000}"
    local base_url="${1:-http://${host}:${port}}"
    curl -fsS --max-time 5 "${base_url}" >/dev/null 2>&1
}

hg_get_lan_ip_address() {
    # Best-effort detection of this machine's real LAN-facing IPv4 address,
    # for DISPLAY purposes only -- mirrors Common.ps1's Get-LanIpAddress and
    # its own comment on why this must run on the HOST, not be self-detected
    # from inside a container (a container sees Docker's own bridge address,
    # not the host's real interface). `ip route get 1.1.1.1` reports the
    # source address the kernel would actually use to reach the internet,
    # which is the same practical signal Windows's gateway-adapter filter is
    # after, without needing to enumerate and exclude virtual adapter names.
    if command -v ip >/dev/null 2>&1; then
        ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1
    fi
}

hg_open_firewall_ports() {
    # Mirrors Common.ps1's New-AppFirewallRule -- opens inbound TCP for the
    # frontend/backend ports so the platform is reachable from other devices
    # on the LAN, same intent as the Windows Private-profile-only rule.
    #
    # Unlike Windows (Windows Firewall is always present), a Linux box may
    # have ufw, firewalld, plain iptables/nftables, or nothing active at all
    # -- there is no single guaranteed firewall to target, so this is
    # deliberately best-effort and non-fatal: it detects what's actually
    # active and adds a rule there, or does nothing and says so, rather than
    # guessing or forcing a firewall tool to be installed.
    local frontend_port="$1" backend_port="$2"
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi "^Status: active"; then
        ufw allow "${frontend_port}/tcp" comment "$HORIZON_GRID_APP_NAME" >/dev/null 2>&1
        ufw allow "${backend_port}/tcp" comment "$HORIZON_GRID_APP_NAME" >/dev/null 2>&1
        hg_log "ufw is active -- allowed inbound TCP $frontend_port,$backend_port."
        echo "ufw is active -- allowed inbound TCP $frontend_port and $backend_port."
    elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
        firewall-cmd --permanent --add-port="${frontend_port}/tcp" >/dev/null 2>&1
        firewall-cmd --permanent --add-port="${backend_port}/tcp" >/dev/null 2>&1
        firewall-cmd --reload >/dev/null 2>&1
        hg_log "firewalld is active -- allowed inbound TCP $frontend_port,$backend_port."
        echo "firewalld is active -- allowed inbound TCP $frontend_port and $backend_port."
    else
        hg_log "No active firewall manager (ufw/firewalld) detected -- no rule added. If a firewall is enabled later, allow TCP $frontend_port and $backend_port for LAN access."
        echo "No active firewall manager detected -- nothing to configure. If you enable a firewall later, allow TCP $frontend_port and $backend_port for LAN access."
    fi
}

hg_remove_firewall_ports() {
    local frontend_port="$1" backend_port="$2"
    if command -v ufw >/dev/null 2>&1; then
        ufw delete allow "${frontend_port}/tcp" >/dev/null 2>&1 || true
        ufw delete allow "${backend_port}/tcp" >/dev/null 2>&1 || true
    fi
    if command -v firewall-cmd >/dev/null 2>&1; then
        firewall-cmd --permanent --remove-port="${frontend_port}/tcp" >/dev/null 2>&1 || true
        firewall-cmd --permanent --remove-port="${backend_port}/tcp" >/dev/null 2>&1 || true
        firewall-cmd --reload >/dev/null 2>&1 || true
    fi
}

hg_read_env_var() {
    # Reads a single KEY's value out of $HORIZON_GRID_ENV_FILE, or empty if
    # absent/file missing. Used by scripts (backup, status) that need one or
    # two real values (POSTGRES_USER, POSTGRES_DB) without parsing the whole
    # file into a wizard-style settings map.
    local key="$1"
    [ -f "$HORIZON_GRID_ENV_FILE" ] || return 0
    sed -n "s/^\s*${key}\s*=\s*\(.*\)\s*$/\1/p" "$HORIZON_GRID_ENV_FILE" | tail -n1
}
