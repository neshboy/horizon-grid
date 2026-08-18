# Linux Packaging Architecture

## Application layer: unchanged

HORIZON GRID's application layer is identical on Linux and Windows. Both platforms run the same Docker Compose stack -- Postgres, Redis, Neo4j, OpenSearch, the FastAPI backend, the Next.js frontend, and two Celery workers -- built from the same `backend/`, `frontend/`, `docker-compose.yml`, and `docker-compose.prod.yml`. Neither platform bundles Node/pip dependencies or pre-built images in its installer artifact; both install them the same way, inside the containers, on the first `docker compose up --build`. Both platforms' Compose project directory shares the basename `app`, so both produce the identical Docker Compose project label (`com.docker.compose.project=app`). There is no architectural divergence at this layer -- it is the same code, the same images, the same runtime behavior.

## Installer/lifecycle layer: the only difference

All Linux-specific work is confined to the outer packaging and lifecycle-management layer, which replaces the Windows installer stack component-for-component:

| Windows | Linux |
|---|---|
| Inno Setup installer | `.deb` package (`horizon-grid_0.2.0_amd64.deb`) |
| WinForms setup wizard | Python CLI setup wizard (terminal-based, `horizon-grid configure`) |
| Windows service registration | systemd unit (`horizon-grid.service`) |
| Start Menu shortcut group | `horizon-grid` CLI entrypoint + desktop menu launcher |
| ProgramData config (ACL-locked) | `/etc/horizon-grid/.env` (root:root, chmod 600) |

The CLI wizard (`linux/wizard/setup_wizard.py`) follows the same flow and issues the same HTTP calls as its Windows counterpart (`windows/wizard/Setup-Wizard.ps1`): Welcome -> Administrator Account -> AI Configuration -> Threat Intelligence Providers -> Network Ports -> Summary -> write `.env` -> `docker compose up -d --build` -> wait for `/health` -> register the admin account -> confirm login. The systemd unit is registered at install time but never auto-started -- nothing runs until the admin completes the wizard, matching the Windows installer's own "nothing auto-starts before configuration" behavior.

## Installed file layout (FHS)

| Path | Purpose | Windows analog |
|---|---|---|
| `/opt/horizon-grid/app/` | Application code (backend/, frontend/, compose files, docs) | Program Files |
| `/etc/horizon-grid/.env` | Config/secrets, root:root, chmod 600 | ProgramData config (ACL-locked) |
| `/var/lib/horizon-grid/backups/` | `pg_dump` snapshots | ProgramData backups |
| `/var/log/horizon-grid/setup.log` | Setup/runtime log | ProgramData `logs\setup.log` |
| `/usr/bin/horizon-grid` | CLI entrypoint | -- |
| `/lib/systemd/system/horizon-grid.service` | systemd unit | Windows service registration |
| `/usr/share/applications/horizon-grid.desktop` | Desktop menu launcher | Start Menu shortcut |

## Why no AppImage

An AppImage packages a single GUI executable for double-click launch. HORIZON GRID is a multi-container Docker Compose platform accessed via a browser, not a single GUI binary -- there is no one executable to wrap. The `.deb` + systemd + CLI-wizard combination is the direct Linux analog of what the Windows installer already does: neither platform reimplements the application as a native, self-contained desktop program. Docker Compose is the real runtime on both.
