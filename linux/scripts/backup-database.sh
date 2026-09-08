#!/usr/bin/env bash
# Takes a pg_dump snapshot of the platform's Postgres database into
# $HORIZON_GRID_BACKUPS_DIR. Mirrors windows/scripts/Backup-Database.ps1,
# including running pg_dump INSIDE the running postgres container (docker
# exec) rather than requiring a host-installed psql/pg_dump -- that's the
# only Postgres client guaranteed to match the server's version, since it
# ships in the same official postgres image docker-compose.yml already pulls.
set -u
QUIET=false
[ "${1:-}" = "--quiet" ] && QUIET=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"
hg_assert_root

say() { [ "$QUIET" = "true" ] || echo "$1"; }

if [ ! -f "$HORIZON_GRID_ENV_FILE" ]; then
    say "No configuration found -- nothing to back up."
    exit 0
fi

# Resolved via `docker compose ps -q postgres` (asking Compose itself, in
# the real project context -- respecting COMPOSE_PROJECT_NAME if it's set)
# rather than a hardcoded "app-postgres-1" container name. This is a
# deliberate, small robustness improvement over the Windows script's own
# hardcoded name (which only ever matches Compose's default "app" project,
# derived from the compose project directory's basename): a real single-
# machine install always uses that same default and is unaffected either
# way, but this version also works correctly for anyone who customizes
# COMPOSE_PROJECT_NAME, and for the automated multi-distro test harness,
# which deliberately uses a non-default project name per distro to avoid
# colliding with another instance on a shared test host.
hg_sync_compose_env_file
CONTAINER_ID=$(cd "$HORIZON_GRID_APP_REPO_DIR" && docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$HORIZON_GRID_ENV_FILE" ps -q postgres 2>/dev/null)
if [ -z "$CONTAINER_ID" ] || ! docker ps -q --no-trunc | grep -q "^${CONTAINER_ID}$"; then
    say "Postgres container is not running -- skipping backup (nothing to snapshot)."
    exit 0
fi

hg_init_data_directories
STAMP="$(date '+%Y%m%d-%H%M%S')"
DUMP_PATH="$HORIZON_GRID_BACKUPS_DIR/postgres-${STAMP}.sql"

PG_USER="$(hg_read_env_var POSTGRES_USER)"; PG_USER="${PG_USER:-ioc}"
PG_DB="$(hg_read_env_var POSTGRES_DB)"; PG_DB="${PG_DB:-ioc_intel}"

say "Backing up database to $DUMP_PATH ..."
# Real gaps found live during overnight QA (this script's own, distinct
# from windows/scripts/Backup-Database.ps1's already-fixed missing exit-
# code check): (1) no signal trap / atomic-write pattern -- writing
# directly to the FINAL $DUMP_PATH name meant an interrupted backup (a
# stopped systemd timer, a cancelled wizard step) could leave a partial,
# corrupt file sitting at the exact filename restore-database.sh's own
# "most recent backup" lookup (ls -1t postgres-*.sql | head -1) would pick
# up as if it were a good one. (2) pg_dump's stderr was discarded
# (2>/dev/null), so a failed-backup log entry never contained the actual
# error reason -- just a generic "failed or produced an empty file."
TMP_DUMP_PATH="${DUMP_PATH}.partial"
trap 'rm -f "$TMP_DUMP_PATH"' EXIT INT TERM
PG_DUMP_STDERR=$(docker exec "$CONTAINER_ID" pg_dump -U "$PG_USER" "$PG_DB" 2>&1 1>"$TMP_DUMP_PATH")
PG_DUMP_EXIT=$?
if [ "$PG_DUMP_EXIT" -eq 0 ] && [ -s "$TMP_DUMP_PATH" ]; then
    mv -f "$TMP_DUMP_PATH" "$DUMP_PATH"
    chmod 600 "$DUMP_PATH"
    hg_log "Database backup written to $DUMP_PATH"
    say "Backup complete: $DUMP_PATH"

    # Keep the 10 most recent backups; older ones are pruned so
    # $HORIZON_GRID_BACKUPS_DIR doesn't grow unbounded across repeated backups.
    ls -1t "$HORIZON_GRID_BACKUPS_DIR"/postgres-*.sql 2>/dev/null | tail -n +11 | xargs -r rm -f
else
    hg_log "Database backup failed or produced an empty file: $DUMP_PATH -- pg_dump output: $PG_DUMP_STDERR" "ERROR"
    say "Backup failed -- see $HORIZON_GRID_SETUP_LOG for details."
    rm -f "$TMP_DUMP_PATH"
    exit 1
fi
