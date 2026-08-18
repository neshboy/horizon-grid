# Linux Release

- Added a first-class Linux release: `horizon-grid_0.1.0_amd64.deb` (~6.1 MB), version 0.1.0 matching Windows exactly, tested on Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, and Debian 12 (bookworm).
- Added a terminal-based CLI setup wizard (`horizon-grid configure`) as the Linux analog of the Windows WinForms wizard, covering Administrator Account, AI Configuration, Threat Intelligence Providers, and Network Ports, then writing `/etc/horizon-grid/.env` and bringing up the platform via Docker Compose.
- Added a `horizon-grid` CLI with `configure`, `start`, `stop`, `restart`, `status`, `open`, `backup`, `diagnostics`, `check`, `uninstall`, and `version` commands.
- Added a systemd unit (`/lib/systemd/system/horizon-grid.service`), registered on install but never auto-started, and a desktop menu launcher (`horizon-grid.desktop`, `Exec=horizon-grid open`).
- Added FHS-standard installed file layout: `/opt/horizon-grid/app` (application), `/etc/horizon-grid/.env` (root:root, chmod 600), `/var/lib/horizon-grid/backups`, `/var/log/horizon-grid/setup.log`.
- Added label-based (not hardcoded-name) cleanup logic for `apt remove` (preserves config/data/volumes) and `apt purge` (removes everything, including all Docker volumes for the Compose project).
- Fixed: excluded two host-only Python virtualenvs (`.venv`, `.venv_test`, ~21,700 files) from being swept into the Linux build by the packaging script.
- Fixed: `apt purge`/`apt remove` leaving behind an untracked runtime-written `/opt/horizon-grid/app/.env` copy that blocked full directory removal; now cleaned up in the package's `postrm` script.
- Fixed: `horizon-grid backup` using a hardcoded Postgres container name, which silently skipped backups under a non-default Compose project name; now resolves the container via `docker compose ps -q postgres`.
