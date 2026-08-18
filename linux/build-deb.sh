#!/usr/bin/env bash
# Builds horizon-grid_<version>_amd64.deb from the repository. Mirrors what
# windows/installer.iss's [Files] section does for the Windows installer:
# copies the real application (backend/, frontend/, docker-compose*.yml,
# docs/, README.md) plus this project's own linux/ packaging scripts into a
# staging tree, then packages it -- it does NOT vendor node_modules/pip
# dependencies or pre-build Docker images into the artifact; those are
# installed/built the same way on every platform, inside the containers, the
# first time `docker compose up --build` runs. That is why this package is
# small (source only) despite the application being substantial -- exactly
# the same reason the ~69 MB Windows installer doesn't contain Docker images
# either.
#
# MUST run on a real Debian/Ubuntu system (or container) -- dpkg-deb is a
# Debian-family tool with no Windows equivalent. Typical invocation, from a
# repo checkout, using a throwaway Debian container as the build host:
#
#   docker run --rm -v "$PWD":/src -w /src debian:12 bash linux/build-deb.sh
#
set -euo pipefail

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb not found -- this script must run on Debian/Ubuntu (or inside a debian:12/ubuntu:24.04 container)." >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^Version:\s*//p' "$REPO_ROOT/linux/debian/control")"
PKG_NAME="horizon-grid_${VERSION}_amd64"
BUILD_ROOT="$(mktemp -d)"
STAGE="$BUILD_ROOT/$PKG_NAME"

echo "Building $PKG_NAME.deb in $BUILD_ROOT ..."

mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/opt/horizon-grid/app"
mkdir -p "$STAGE/opt/horizon-grid/app/linux/scripts"
mkdir -p "$STAGE/opt/horizon-grid/app/linux/wizard"
mkdir -p "$STAGE/usr/bin"
mkdir -p "$STAGE/usr/share/applications"
mkdir -p "$STAGE/usr/share/doc/horizon-grid"
mkdir -p "$STAGE/lib/systemd/system"

# --- Control files ---
cp "$REPO_ROOT/linux/debian/control" "$STAGE/DEBIAN/control"
cp "$REPO_ROOT/linux/debian/postinst" "$STAGE/DEBIAN/postinst"
cp "$REPO_ROOT/linux/debian/prerm" "$STAGE/DEBIAN/prerm"
cp "$REPO_ROOT/linux/debian/postrm" "$STAGE/DEBIAN/postrm"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"

# --- The real application -- same excludes as installer.iss's [Files]
# section (__pycache__/node_modules/.next are regenerated at container-build
# time; "nul" is the stray reserved-name artifact that also blocks the
# Windows build; the ad-hoc _qa_*.py/cleanup_qa_*.py scratch scripts have no
# place in a shipping build on either platform), PLUS .venv/.venv_test --
# confirmed live on this dev checkout that those two host-only virtualenvs
# alone account for ~21,700 files directly under backend/, none of which
# installer.iss excludes either (a latent gap there too, flagged separately
# for the Windows regression pass -- not fixed here since this script only
# owns the Linux package). Backend dependencies install the same way on
# every platform: pip install -r requirements.txt runs INSIDE the container
# at image-build time (see backend/Dockerfile) -- a host venv is never
# something either installer should ship. ---
rsync -a \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
    --exclude 'celerybeat-schedule' --exclude 'nul' \
    --exclude '_qa_*.py' --exclude 'cleanup_qa_*.py' \
    --exclude '.venv' --exclude '.venv_test' --exclude 'venv' --exclude '.env' \
    "$REPO_ROOT/backend/" "$STAGE/opt/horizon-grid/app/backend/"
rsync -a \
    --exclude 'node_modules' --exclude '.next' --exclude '*.tsbuildinfo' \
    "$REPO_ROOT/frontend/" "$STAGE/opt/horizon-grid/app/frontend/"
cp "$REPO_ROOT/docker-compose.yml" "$STAGE/opt/horizon-grid/app/"
cp "$REPO_ROOT/docker-compose.prod.yml" "$STAGE/opt/horizon-grid/app/"
cp "$REPO_ROOT/README.md" "$STAGE/opt/horizon-grid/app/"
[ -d "$REPO_ROOT/docs" ] && rsync -a "$REPO_ROOT/docs/" "$STAGE/opt/horizon-grid/app/docs/"

# --- This project's own Linux packaging scripts ---
cp "$REPO_ROOT/linux/scripts/"*.sh "$STAGE/opt/horizon-grid/app/linux/scripts/"
cp "$REPO_ROOT/linux/wizard/setup_wizard.py" "$STAGE/opt/horizon-grid/app/linux/wizard/"
chmod 0755 "$STAGE/opt/horizon-grid/app/linux/scripts/"*.sh
chmod 0755 "$STAGE/opt/horizon-grid/app/linux/wizard/setup_wizard.py"

cp "$REPO_ROOT/linux/bin/horizon-grid" "$STAGE/usr/bin/horizon-grid"
chmod 0755 "$STAGE/usr/bin/horizon-grid"

cp "$REPO_ROOT/linux/systemd/horizon-grid.service" "$STAGE/lib/systemd/system/horizon-grid.service"
cp "$REPO_ROOT/linux/horizon-grid.desktop" "$STAGE/usr/share/applications/horizon-grid.desktop"

cp "$REPO_ROOT/README.md" "$STAGE/usr/share/doc/horizon-grid/README.md" 2>/dev/null || true
cat >"$STAGE/usr/share/doc/horizon-grid/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: HORIZON GRID
Source: (private/internal project)

Files: *
Copyright: HORIZON GRID
License: proprietary
 All rights reserved unless stated otherwise in a LICENSE file at the
 repository root.
EOF
gzip -n -9 "$STAGE/usr/share/doc/horizon-grid/README.md" 2>/dev/null || true

# --- Installed-Size (Debian policy expects this in KB; not required for
# dpkg-deb to build, but included for a correctly-formed package) ---
SIZE_KB=$(du -sk "$STAGE" | cut -f1)
sed -i "s/^Installed-Size:.*/Installed-Size: ${SIZE_KB}/" "$STAGE/DEBIAN/control"

OUT_DIR="$REPO_ROOT/release"
mkdir -p "$OUT_DIR"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT_DIR/${PKG_NAME}.deb"

echo ""
echo "Built: $OUT_DIR/${PKG_NAME}.deb"
dpkg-deb --info "$OUT_DIR/${PKG_NAME}.deb"
rm -rf "$BUILD_ROOT"
