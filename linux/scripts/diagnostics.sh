#!/usr/bin/env bash
# Bundles a support diagnostics archive: docker compose ps, the last 200
# lines of every container's logs, the setup log, a prerequisite-check run,
# and a REDACTED copy of .env (variable names and character counts only --
# the real .env is never included). Mirrors windows/scripts/Diagnostics.ps1.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"
hg_assert_root

OUT_DIR="$(mktemp -d)/horizon-grid-diagnostics-$(date '+%Y%m%d-%H%M%S')"
mkdir -p "$OUT_DIR"

echo "Collecting diagnostics into $OUT_DIR ..."

if [ -f "$HORIZON_GRID_ENV_FILE" ]; then
    hg_sync_compose_env_file
    (
        cd "$HORIZON_GRID_APP_REPO_DIR" || exit 1
        docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$HORIZON_GRID_ENV_FILE" ps \
            >"$OUT_DIR/compose-ps.txt" 2>&1
        for svc in postgres redis neo4j opensearch backend frontend celery_worker celery_beat; do
            docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$HORIZON_GRID_ENV_FILE" \
                logs --no-color --tail=200 "$svc" >"$OUT_DIR/logs-${svc}.txt" 2>&1 || true
        done
    )

    # Redacted .env: variable names and character counts only, exactly like
    # the Windows diagnostics bundle -- never the real values.
    {
        echo "# Redacted copy of $HORIZON_GRID_ENV_FILE -- values replaced with"
        echo "# ***REDACTED***(set, N chars) or (empty). No real credential appears below."
        while IFS='=' read -r key value; do
            case "$key" in
                ''|\#*) echo "$key" ;;
                *)
                    if [ -z "$value" ]; then
                        echo "${key}=(empty)"
                    else
                        echo "${key}=***REDACTED***(set, ${#value} chars)"
                    fi
                    ;;
            esac
        done <"$HORIZON_GRID_ENV_FILE"
    } >"$OUT_DIR/env-redacted.txt"
else
    echo "Not configured -- no compose state or .env to collect." >"$OUT_DIR/compose-ps.txt"
fi

[ -f "$HORIZON_GRID_SETUP_LOG" ] && cp "$HORIZON_GRID_SETUP_LOG" "$OUT_DIR/setup.log"

"$SCRIPT_DIR/check-prerequisites.sh" >"$OUT_DIR/prerequisites.json" 2>"$OUT_DIR/prerequisites.txt" || true

{
    echo "distro: $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}")"
    echo "kernel: $(uname -r)"
    echo "arch: $(uname -m)"
    echo "docker: $(docker --version 2>/dev/null || echo 'not found')"
    echo "docker compose: $(docker compose version 2>/dev/null || echo 'not found')"
} >"$OUT_DIR/system-info.txt"

ARCHIVE="/tmp/horizon-grid-diagnostics-$(date '+%Y%m%d-%H%M%S').tar.gz"
# Real gap found live during overnight QA: tar's own exit code was never
# checked -- the source data ($OUT_DIR) was deleted and a "written to"
# success message printed UNCONDITIONALLY, so a tar failure (disk full in
# /tmp, a permission issue) both destroyed the only copy of the collected
# diagnostics AND told the user it had succeeded, exactly during an
# incident where this tool failing silently is worst.
if tar -czf "$ARCHIVE" -C "$(dirname "$OUT_DIR")" "$(basename "$OUT_DIR")" && [ -s "$ARCHIVE" ]; then
    rm -rf "$OUT_DIR"
    # Real gap found live during overnight QA: this archive can contain
    # real operational data (docker logs, setup logs -- .env itself is
    # redacted, but a log line can still echo a real value) and was
    # written world-readable to /tmp with no permission hardening, unlike
    # the root-only 0700/0600 model used everywhere else in this
    # toolchain (this script already runs as root -- hg_assert_root above).
    chmod 600 "$ARCHIVE"
    echo "Diagnostics archive written to: $ARCHIVE"
    echo "This can be shared for support -- it contains no real credential values."
else
    echo "Failed to create the diagnostics archive at $ARCHIVE -- the raw collected files are still available at $OUT_DIR" >&2
    exit 1
fi
