#!/usr/bin/env bash
# Restores a pg_dump snapshot (taken by backup-database.sh) into the
# platform's Postgres database, replacing its current contents. Mirrors
# windows/scripts/Restore-Database.ps1 -- see that script's header comment
# for the full rationale, including the self-contradictory manual procedure
# this replaces (stopping the whole platform also stops Postgres, leaving
# no running container to restore into).
#
# Destructive by design: REPLACES the current database with whatever the
# backup file contains. Requires an explicit typed confirmation unless
# --force is passed.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
. "$SCRIPT_DIR/common.sh"
hg_assert_root

BACKUP_FILE=""
FORCE=false
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --backup-file=*) BACKUP_FILE="${arg#--backup-file=}" ;;
        *) BACKUP_FILE="$arg" ;;
    esac
done

if [ ! -f "$HORIZON_GRID_ENV_FILE" ]; then
    echo "No configuration found -- nothing to restore into. Run 'sudo horizon-grid configure' first."
    exit 1
fi

if [ -z "$BACKUP_FILE" ]; then
    BACKUP_FILE=$(ls -1t "$HORIZON_GRID_BACKUPS_DIR"/postgres-*.sql 2>/dev/null | head -n1)
    if [ -z "$BACKUP_FILE" ]; then
        echo "No backup file specified and none found in $HORIZON_GRID_BACKUPS_DIR."
        echo "Usage: horizon-grid restore [/path/to/postgres-YYYYMMDD-HHMMSS.sql] [--force]"
        exit 1
    fi
    echo "No backup file given -- using the most recent backup: $BACKUP_FILE"
fi
if [ ! -f "$BACKUP_FILE" ]; then
    echo "Backup file not found: $BACKUP_FILE"
    exit 1
fi

hg_sync_compose_env_file
CONTAINER_ID=$(cd "$HORIZON_GRID_APP_REPO_DIR" && docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$HORIZON_GRID_ENV_FILE" ps -q postgres 2>/dev/null)
if [ -z "$CONTAINER_ID" ] || ! docker ps -q --no-trunc | grep -q "^${CONTAINER_ID}$"; then
    echo "Postgres container is not running -- starting it first..."
    hg_invoke_docker_compose up -d postgres
    for _ in $(seq 1 20); do
        CONTAINER_ID=$(cd "$HORIZON_GRID_APP_REPO_DIR" && docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$HORIZON_GRID_ENV_FILE" ps -q postgres 2>/dev/null)
        [ -n "$CONTAINER_ID" ] && docker ps -q --no-trunc | grep -q "^${CONTAINER_ID}$" && break
        sleep 2
    done
    if [ -z "$CONTAINER_ID" ] || ! docker ps -q --no-trunc | grep -q "^${CONTAINER_ID}$"; then
        echo "Postgres container did not come up -- aborting restore."
        exit 1
    fi
fi

PG_USER="$(hg_read_env_var POSTGRES_USER)"; PG_USER="${PG_USER:-ioc}"
PG_DB="$(hg_read_env_var POSTGRES_DB)"; PG_DB="${PG_DB:-ioc_intel}"

if [ "$FORCE" != "true" ]; then
    echo ""
    echo "WARNING: this will REPLACE the current '$PG_DB' database with the contents of:"
    echo "  $BACKUP_FILE"
    echo "Every case, investigation, watchlist, and note added since that backup was taken will be PERMANENTLY LOST."
    read -r -p "Type RESTORE (in capitals) to continue, or anything else to cancel: " CONFIRM
    if [ "$CONFIRM" != "RESTORE" ]; then
        echo "Cancelled -- no changes made."
        exit 0
    fi
fi

hg_log "Restoring database from $BACKUP_FILE"

echo "Stopping services that write to the database (backend, celery_worker, celery_beat)..."
hg_invoke_docker_compose stop backend celery_worker celery_beat

echo "Terminating any other connections to '$PG_DB'..."
docker exec "$CONTAINER_ID" psql -U "$PG_USER" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$PG_DB' AND pid <> pg_backend_pid();" \
    >/dev/null 2>&1 || true

echo "Dropping and recreating '$PG_DB'..."
# Real gap found live during overnight QA (mirrors windows/scripts/Restore-
# Database.ps1's identical fix): neither of these two commands' exit codes
# was checked -- a DROP that fails (e.g. "database is being accessed by
# other users", a real, common race if the connection-termination step
# above didn't win in time) or a CREATE that fails left the script
# barrelling ahead into the dump-replay step regardless, against whatever
# half-broken DB state resulted.
DROP_OUTPUT=$(docker exec "$CONTAINER_ID" psql -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS $PG_DB;" 2>&1)
DROP_EXIT=$?
CREATE_OUTPUT=$(docker exec "$CONTAINER_ID" psql -U "$PG_USER" -d postgres -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" 2>&1)
CREATE_EXIT=$?
if [ "$DROP_EXIT" -ne 0 ] || [ "$CREATE_EXIT" -ne 0 ]; then
    hg_log "Database restore FAILED: could not drop/recreate '$PG_DB' -- drop output: $DROP_OUTPUT | create output: $CREATE_OUTPUT" "ERROR"
    echo "Failed to drop/recreate '$PG_DB':"
    echo "$DROP_OUTPUT"
    echo "$CREATE_OUTPUT"
    echo "Restarting backend/celery anyway so the platform isn't left fully down..."
    hg_invoke_docker_compose start backend celery_worker celery_beat
    exit 1
fi

echo "Restoring $BACKUP_FILE ..."
# Real gap found live during overnight QA: without -v ON_ERROR_STOP=1,
# psql's default behavior is to log an individual statement error to
# stderr and KEEP GOING, then still exit 0 as long as no connection-level
# FATAL error occurred -- so a dump replay with some failing statements
# could silently leave the restored database missing data/schema while
# the exit-code check below saw nothing wrong and reported success.
RESTORE_OUTPUT=$(docker exec -i "$CONTAINER_ID" psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" <"$BACKUP_FILE" 2>&1)
RESTORE_EXIT=$?

if [ "$RESTORE_EXIT" -ne 0 ]; then
    hg_log "Database restore FAILED (exit code $RESTORE_EXIT) from $BACKUP_FILE -- psql output: $RESTORE_OUTPUT" "ERROR"
    echo "Restore failed (exit code $RESTORE_EXIT):"
    echo "$RESTORE_OUTPUT"
    echo "The database may be in a partial state -- see $HORIZON_GRID_SETUP_LOG and consider restoring again."
    echo "Restarting backend/celery anyway so the platform isn't left fully down..."
    hg_invoke_docker_compose start backend celery_worker celery_beat
    exit 1
fi

echo "Restore complete. Restarting backend and celery..."
hg_invoke_docker_compose start backend celery_worker celery_beat

echo "Waiting for the backend to become healthy..."
HEALTHY=false
for _ in $(seq 1 30); do
    if hg_test_backend_health; then HEALTHY=true; break; fi
    sleep 3
done

hg_log "Database restore from $BACKUP_FILE completed successfully."
if [ "$HEALTHY" = "true" ]; then
    echo "Restore complete and the backend is healthy."
else
    echo "Restore complete, but the backend did not report healthy within 90s -- run 'sudo horizon-grid status' or 'sudo horizon-grid diagnostics'."
fi
