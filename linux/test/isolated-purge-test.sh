#!/usr/bin/env bash
# Focused, isolated validation of the default-project-name remove/purge
# behavior -- runs against a throwaway Docker-in-Docker daemon (never the
# shared build host's real daemon) specifically so this can use the REAL
# default Compose project name ("app", same as a genuine single-machine
# install) with zero risk to any other real instance's containers/volumes
# on the shared host. Not shipped in the .deb -- test infrastructure only.
set -uo pipefail
DEB_PATH="${1:?usage: isolated-purge-test.sh <path-to-.deb>}"
RESULTS_FILE="/tmp/isolated-purge-results.txt"
: >"$RESULTS_FILE"
pass() { echo "[PASS] $1" | tee -a "$RESULTS_FILE"; }
fail() { echo "[FAIL] $1" | tee -a "$RESULTS_FILE"; }
info() { echo "[INFO] $1" | tee -a "$RESULTS_FILE"; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates >/dev/null 2>&1
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sh /tmp/get-docker.sh >/tmp/docker-install.log 2>&1
docker compose version >/dev/null 2>&1 && pass "docker compose available" || fail "docker compose unavailable"

apt-get install -y -qq "$DEB_PATH" >/tmp/install.log 2>&1 && pass "apt install succeeded" || { fail "apt install failed"; cat /tmp/install.log; exit 1; }

# Real default project name -- NO override -- safe here only because this
# whole container talks to an isolated dind daemon (DOCKER_HOST points at
# it), not the shared build host's real daemon.
export HORIZON_GRID_BACKEND_HOST="hg-dind-daemon"
if python3 /opt/horizon-grid/app/linux/wizard/setup_wizard.py --non-interactive \
    --answers-file /tmp/answers-fresh-install.json >/tmp/wizard.log 2>&1; then
    pass "setup_wizard.py completed with the DEFAULT compose project name"
else
    fail "setup_wizard.py FAILED"; tail -50 /tmp/wizard.log | tee -a "$RESULTS_FILE"; exit 1
fi

sleep 5
curl -fsS --max-time 5 "http://hg-dind-daemon:18000/health" >/dev/null 2>&1 && pass "backend healthy under default project name" || fail "backend not healthy"

REAL_CIDS=$(docker ps -aq --filter "label=com.docker.compose.project=app")
REAL_VIDS=$(docker volume ls -q --filter "label=com.docker.compose.project=app")
info "Before removal: $(echo "$REAL_CIDS" | grep -c .) containers, $(echo "$REAL_VIDS" | grep -c .) volumes labeled project=app"

# --- apt remove: keep data ---
apt-get remove -y -qq horizon-grid >/tmp/remove.log 2>&1
VIDS_AFTER_REMOVE=$(docker volume ls -q --filter "label=com.docker.compose.project=app" | grep -c . || true)
[ "$VIDS_AFTER_REMOVE" -ge 3 ] && pass "apt remove (default project name) preserved $VIDS_AFTER_REMOVE data volumes" || fail "apt remove: expected >=3 volumes preserved, found $VIDS_AFTER_REMOVE"
[ -f /etc/horizon-grid/.env ] && pass "apt remove kept /etc/horizon-grid/.env" || fail "apt remove deleted /etc/horizon-grid/.env"

# --- reinstall + purge ---
apt-get install -y -qq "$DEB_PATH" >/tmp/reinstall.log 2>&1 && pass "reinstall succeeded" || fail "reinstall failed"
apt-get purge -y -qq horizon-grid >/tmp/purge.log 2>&1

CIDS_AFTER_PURGE=$(docker ps -aq --filter "label=com.docker.compose.project=app" | grep -c . || true)
VIDS_AFTER_PURGE=$(docker volume ls -q --filter "label=com.docker.compose.project=app" | grep -c . || true)
[ "$CIDS_AFTER_PURGE" -eq 0 ] && pass "apt purge (default project name) removed ALL containers labeled project=app" || fail "apt purge left $CIDS_AFTER_PURGE container(s) behind"
[ "$VIDS_AFTER_PURGE" -eq 0 ] && pass "apt purge (default project name) removed ALL volumes labeled project=app" || fail "apt purge left $VIDS_AFTER_PURGE volume(s) behind"
[ -d /etc/horizon-grid ] && fail "apt purge left /etc/horizon-grid behind" || pass "apt purge deleted /etc/horizon-grid"
[ -d /opt/horizon-grid/app ] && fail "apt purge left /opt/horizon-grid/app behind (the untracked .env-copy cleanup did not fully work)" || pass "apt purge fully removed /opt/horizon-grid/app"

echo ""
grep -c '^\[PASS\]' "$RESULTS_FILE" | xargs echo "PASS count:"
grep -c '^\[FAIL\]' "$RESULTS_FILE" | xargs echo "FAIL count:"
grep '^\[FAIL\]' "$RESULTS_FILE" || echo "(no failures)"
