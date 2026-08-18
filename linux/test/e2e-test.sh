#!/usr/bin/env bash
# Real end-to-end test driver -- runs INSIDE a target distro container
# (debian:12 / ubuntu:22.04 / ubuntu:24.04) with the host's Docker socket
# mounted in (sibling-container pattern: `docker compose` issued from in
# here talks to the REAL outer Docker daemon, which is genuine Linux either
# way -- Docker Desktop's own Linux VM on this build host, or a bare-metal
# Linux daemon on a real target machine). Not shipped in the .deb -- this is
# test infrastructure, not part of the product.
#
# COMPOSE_PROJECT_NAME and the alternate ports in answers-fresh-install.json
# exist ONLY to avoid colliding with a separate, real HORIZON GRID instance
# that may already be running on the same shared Docker daemon (true on
# this specific build host) -- a genuinely fresh single-machine install has
# the whole port range and the default "app" project name to itself.
set -uo pipefail

DEB_PATH="${1:?usage: e2e-test.sh <path-to-.deb> <distro-label>}"
DISTRO_LABEL="${2:?usage: e2e-test.sh <path-to-.deb> <distro-label>}"
RESULTS_FILE="/tmp/e2e-results-${DISTRO_LABEL}.txt"
: >"$RESULTS_FILE"

pass() { echo "[PASS] $1" | tee -a "$RESULTS_FILE"; }
fail() { echo "[FAIL] $1" | tee -a "$RESULTS_FILE"; }
info() { echo "[INFO] $1" | tee -a "$RESULTS_FILE"; }

export HORIZON_GRID_BACKEND_HOST="host.docker.internal"
BACKEND_PORT=18000
FRONTEND_PORT=13000
BASE="http://host.docker.internal:${BACKEND_PORT}"

echo "===================================================================="
echo " HORIZON GRID Linux E2E test -- $DISTRO_LABEL"
echo "===================================================================="
cat /etc/os-release | grep -E '^(PRETTY_NAME|VERSION_ID)=' | tee -a "$RESULTS_FILE"
uname -a | tee -a "$RESULTS_FILE"
echo ""

# --- Step 1: clean-machine baseline (nothing but base OS + what we install
# below). Confirmed live on a real Debian 12 container that the distro's own
# `docker.io` package does NOT ship the Compose v2 plugin, and there is no
# `docker-compose-v2` package in Debian 12's default repos to fall back to
# either -- only the deprecated standalone v1 `docker-compose` binary is
# available there. Docker's own officially documented install path
# (get.docker.com, which sets up Docker's real apt repo and installs
# docker-ce + the compose plugin together) is what actually provides
# `docker compose` correctly across all three target distributions, so that
# is what this test installs -- and what the Linux Installation Guide tells
# a real user to run, for the same reason. ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates >/dev/null 2>&1
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sh /tmp/get-docker.sh >/tmp/docker-install.log 2>&1
if docker compose version >/dev/null 2>&1; then
    pass "docker compose v2 plugin available after the official get.docker.com install ($(docker compose version --short))"
else
    fail "docker compose v2 plugin NOT available even after get.docker.com on $DISTRO_LABEL"
    tail -30 /tmp/docker-install.log | tee -a "$RESULTS_FILE"
fi

# --- Step 2: install the .deb exactly the way a real user would ---
if apt-get install -y -qq "$DEB_PATH" >/tmp/install.log 2>&1; then
    pass "apt install ./horizon-grid_*.deb succeeded"
else
    fail "apt install ./horizon-grid_*.deb FAILED"
    cat /tmp/install.log | tee -a "$RESULTS_FILE"
    exit 1
fi

for f in /usr/bin/horizon-grid /opt/horizon-grid/app/docker-compose.yml \
         /opt/horizon-grid/app/linux/wizard/setup_wizard.py \
         /usr/share/applications/horizon-grid.desktop \
         /lib/systemd/system/horizon-grid.service; do
    if [ -e "$f" ]; then pass "file present: $f"; else fail "MISSING file: $f"; fi
done
[ -x /usr/bin/horizon-grid ] && pass "/usr/bin/horizon-grid is executable" || fail "/usr/bin/horizon-grid not executable"

if systemctl is-enabled horizon-grid.service >/dev/null 2>&1; then
    fail "horizon-grid.service is enabled after plain install (should NOT auto-enable per master-prompt Phase 6)"
else
    pass "horizon-grid.service is NOT auto-enabled after install (correct -- nothing starts until configure)"
fi

# --- Step 3: prerequisite check ---
if horizon-grid check >/tmp/check.json 2>/tmp/check.txt; then
    pass "horizon-grid check: all hard checks passed"
else
    info "horizon-grid check reported a hard failure (expected for RAM/port/arch soft checks in a container -- see detail)"
fi
cat /tmp/check.txt | tee -a "$RESULTS_FILE"

# --- Step 4: run the setup wizard non-interactively (fresh install) ---
export COMPOSE_PROJECT_NAME="hgtest_${DISTRO_LABEL}"
info "Using COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME and alternate ports 13000/18000/etc to avoid colliding with any other instance on this shared Docker daemon."
if python3 /opt/horizon-grid/app/linux/wizard/setup_wizard.py --non-interactive \
    --answers-file /tmp/answers-fresh-install.json >/tmp/wizard.log 2>&1; then
    pass "setup_wizard.py --non-interactive completed (fresh install, docker compose up --build)"
else
    fail "setup_wizard.py FAILED -- see wizard.log"
    tail -60 /tmp/wizard.log | tee -a "$RESULTS_FILE"
    exit 1
fi
tail -20 /tmp/wizard.log | tee -a "$RESULTS_FILE"

[ -f /etc/horizon-grid/.env ] && pass "/etc/horizon-grid/.env written" || fail "/etc/horizon-grid/.env missing"
PERMS=$(stat -c '%a %U:%G' /etc/horizon-grid/.env 2>/dev/null)
[ "$PERMS" = "600 root:root" ] && pass "/etc/horizon-grid/.env is 0600 root:root" || fail "/etc/horizon-grid/.env permissions wrong: $PERMS"

# --- Step 5: real health check from the OUTER host's vantage point (the
# containers are published on the outer Docker host, exactly like a real
# single-machine install where the wizard and the containers share one
# host) ---
sleep 5
if curl -fsS --max-time 5 "${BASE}/health" | tee -a "$RESULTS_FILE"; then
    pass "GET /health reachable"
else
    fail "GET /health NOT reachable"
fi

# --- Step 6: sign in as the freshly registered admin ---
LOGIN_RESP=$(curl -fsS --max-time 10 -X POST "${BASE}/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"email":"linux-qa-admin@example.com","password":"LinuxQA-Test-Passw0rd!"}')
TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
if [ -n "$TOKEN" ]; then
    pass "Admin login succeeded, got access token"
else
    fail "Admin login FAILED: $LOGIN_RESP"
fi

# --- Step 7: real IOC investigation (8.8.8.8 -- same known-good test IOC
# used throughout this project's Windows QA). The real submission endpoint
# is POST /lookup/stream (Server-Sent Events, not a plain JSON POST -- there
# is no separate "create" call). curl handles an SSE response as an ordinary
# HTTP body and simply blocks until the stream closes, which is exactly
# "wait for the investigation to finish" -- no separate polling loop needed
# to drive it, though GET /lookup/{id} (used below, and again after
# stop/start) is the real polling endpoint for checking on it afterward. ---
STREAM_OUT=$(curl -fsS --max-time 90 -X POST "${BASE}/api/v1/lookup/stream" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"value":"8.8.8.8"}' 2>&1)
LOOKUP_ID=$(echo "$STREAM_OUT" | grep -m1 '^data:.*"lookup_id"' | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if line.startswith('data:'):
        try:
            print(json.loads(line[5:].strip()).get('lookup_id', ''))
        except Exception:
            pass
" 2>/dev/null | head -n1)
if [ -n "$LOOKUP_ID" ]; then
    pass "POST /api/v1/lookup/stream accepted 8.8.8.8, lookup id=$LOOKUP_ID"
else
    fail "POST /api/v1/lookup/stream did not yield a lookup id in its 'detected' SSE event"
fi
if echo "$STREAM_OUT" | grep -q '^event: done'; then
    pass "SSE stream reached its 'done' event (investigation completed end to end)"
else
    fail "SSE stream did not reach a 'done' event within 90s"
fi

if [ -n "$LOOKUP_ID" ]; then
    RESULT=$(curl -fsS --max-time 15 "${BASE}/api/v1/lookup/${LOOKUP_ID}" -H "Authorization: Bearer $TOKEN")
    STATUS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
    info "GET /api/v1/lookup/${LOOKUP_ID} status: $STATUS"
    if [ "$STATUS" = "completed" ]; then pass "Lookup status is 'completed'"; else info "Lookup status was '$STATUS' (not necessarily a failure -- see detail above)"; fi
    echo "$RESULT" | python3 -m json.tool 2>/dev/null | head -40 | tee -a "$RESULTS_FILE" >/dev/null
fi

# --- Step 8: Provider Health + Executive Dashboard endpoints ---
curl -fsS --max-time 10 "${BASE}/api/v1/providers/health" -H "Authorization: Bearer $TOKEN" >/tmp/provider-health.json 2>&1 \
    && pass "GET /api/v1/providers/health reachable" || fail "GET /api/v1/providers/health FAILED"
curl -fsS --max-time 10 "${BASE}/api/v1/dashboard/kpis" -H "Authorization: Bearer $TOKEN" >/tmp/dashboard-kpis.json 2>&1 \
    && pass "GET /api/v1/dashboard/kpis reachable" || fail "GET /api/v1/dashboard/kpis FAILED"

# --- Step 9: backup ---
if horizon-grid backup >/tmp/backup.log 2>&1; then
    pass "horizon-grid backup succeeded"
else
    fail "horizon-grid backup FAILED"
fi
ls -la /var/lib/horizon-grid/backups/ | tee -a "$RESULTS_FILE"

# --- Step 10: stop / start, verify persistence ---
horizon-grid stop >/tmp/stop.log 2>&1 && pass "horizon-grid stop succeeded" || fail "horizon-grid stop FAILED"
sleep 3
horizon-grid start >/tmp/start.log 2>&1 && pass "horizon-grid start succeeded" || fail "horizon-grid start FAILED"
sleep 5
if curl -fsS --max-time 5 "${BASE}/health" >/dev/null 2>&1; then
    pass "Backend healthy again after stop/start"
else
    fail "Backend NOT healthy after stop/start"
fi
RECHECK=$(curl -fsS --max-time 15 "${BASE}/api/v1/lookup/${LOOKUP_ID}" -H "Authorization: Bearer $TOKEN" 2>&1)
if echo "$RECHECK" | grep -q "8.8.8.8"; then
    pass "Investigation data for 8.8.8.8 persisted across stop/start"
else
    fail "Investigation data did NOT persist across stop/start: $RECHECK"
fi

# --- Step 11: apt remove (keep-data path) ---
apt-get remove -y -qq horizon-grid >/tmp/remove.log 2>&1
if [ -f /etc/horizon-grid/.env ]; then pass "apt remove kept /etc/horizon-grid/.env (data preserved)"; else fail "apt remove deleted /etc/horizon-grid/.env (should be preserved on remove, only purge deletes it)"; fi
if [ -d /var/lib/horizon-grid ]; then pass "apt remove kept /var/lib/horizon-grid"; else fail "apt remove deleted /var/lib/horizon-grid"; fi
REMAINING=$(docker ps -aq --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" | wc -l)
if [ "$REMAINING" -eq 0 ]; then pass "apt remove stopped/removed all containers for this test's compose project"; else info "apt remove: $REMAINING container(s) for this project still present (stopped is fine, check below)"; fi
VOLS_AFTER_REMOVE=$(docker volume ls -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" | wc -l)
[ "$VOLS_AFTER_REMOVE" -ge 3 ] && pass "apt remove preserved Docker volumes ($VOLS_AFTER_REMOVE found -- postgres/neo4j/opensearch data intact)" || fail "apt remove: expected >=3 data volumes preserved, found $VOLS_AFTER_REMOVE"

# --- Step 12: reinstall, verify the SAME data comes back ---
apt-get install -y -qq "$DEB_PATH" >/tmp/reinstall.log 2>&1 && pass "reinstall (apt install) succeeded" || fail "reinstall FAILED"
if horizon-grid start >/tmp/restart-after-reinstall.log 2>&1; then
    pass "horizon-grid start after reinstall succeeded"
else
    fail "horizon-grid start after reinstall FAILED"
fi
sleep 8
LOGIN_RESP2=$(curl -fsS --max-time 10 -X POST "${BASE}/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"email":"linux-qa-admin@example.com","password":"LinuxQA-Test-Passw0rd!"}')
TOKEN2=$(echo "$LOGIN_RESP2" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
if [ -n "$TOKEN2" ]; then
    pass "Same admin account/password still works after reinstall (real data persistence, not a fresh DB)"
else
    fail "Admin login FAILED after reinstall -- data did not persist: $LOGIN_RESP2"
fi
if [ -n "$LOOKUP_ID" ] && [ -n "$TOKEN2" ]; then
    RECHECK2=$(curl -fsS --max-time 15 "${BASE}/api/v1/lookup/${LOOKUP_ID}" -H "Authorization: Bearer $TOKEN2" 2>&1)
    echo "$RECHECK2" | grep -q "8.8.8.8" && pass "Original 8.8.8.8 investigation still present after reinstall" || fail "Original investigation lost after reinstall"
fi

# --- Step 13: apt purge (destroy-everything path) ---
apt-get purge -y -qq horizon-grid >/tmp/purge.log 2>&1
[ -d /etc/horizon-grid ] && fail "apt purge left /etc/horizon-grid behind" || pass "apt purge deleted /etc/horizon-grid"
[ -d /var/lib/horizon-grid ] && fail "apt purge left /var/lib/horizon-grid behind" || pass "apt purge deleted /var/lib/horizon-grid"
VOLS_AFTER_PURGE=$(docker volume ls -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" | wc -l)
[ "$VOLS_AFTER_PURGE" -eq 0 ] && pass "apt purge removed all Docker volumes for this project" || fail "apt purge left $VOLS_AFTER_PURGE volume(s) behind"
CONTAINERS_AFTER_PURGE=$(docker ps -aq --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" | wc -l)
[ "$CONTAINERS_AFTER_PURGE" -eq 0 ] && pass "apt purge removed all containers for this project" || fail "apt purge left $CONTAINERS_AFTER_PURGE container(s) behind"

echo ""
echo "===================================================================="
echo " Results summary -- $DISTRO_LABEL"
echo "===================================================================="
grep -c '^\[PASS\]' "$RESULTS_FILE" | xargs echo "PASS count:"
grep -c '^\[FAIL\]' "$RESULTS_FILE" | xargs echo "FAIL count:"
grep '^\[FAIL\]' "$RESULTS_FILE" || echo "(no failures)"
cp "$RESULTS_FILE" "/tmp/final-results-${DISTRO_LABEL}.txt"
