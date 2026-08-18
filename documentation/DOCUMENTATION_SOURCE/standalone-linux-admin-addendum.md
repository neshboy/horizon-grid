# Administering a Linux Install

This section maps the actions covered in the Windows Admin Guide to their real Linux equivalents. The underlying platform (Docker Compose, the FastAPI backend, the Next.js frontend, Postgres/Redis/Neo4j/OpenSearch) is identical on both platforms -- only the outer packaging/administration layer differs.

## Admin actions: Windows vs. Linux

| Windows Admin Guide action | Linux equivalent | Notes |
|---|---|---|
| Start Platform | `sudo horizon-grid start` | |
| Stop Platform | `sudo horizon-grid stop` | |
| Restart Platform | `sudo horizon-grid restart` | |
| Service Status | `sudo horizon-grid status` | |
| Open in browser (Start Menu shortcut) | `horizon-grid open` | Starts the platform if needed, then opens the browser; also reachable via the `horizon-grid.desktop` menu launcher (Exec=`horizon-grid open`) |
| Backup Database Now | `sudo horizon-grid backup` | Writes a `pg_dump` snapshot to `/var/lib/horizon-grid/backups/`; resolves the real Postgres container via `docker compose ps -q postgres` (label/service-based), so it works correctly under any `COMPOSE_PROJECT_NAME`, not just the default |
| Diagnostics | `sudo horizon-grid diagnostics` | Bundles a redacted copy of `.env` (`KEY=***REDACTED***(set, N chars)` or `KEY=(empty)` -- real values never appear), same redaction behavior as Windows's `Diagnostics.ps1` |
| Configuration / Reconfigure Wizard | `sudo horizon-grid configure` | Terminal wizard (`linux/wizard/setup_wizard.py`) replacing the WinForms wizard; same step order: Welcome -> Administrator Account -> AI Configuration -> Threat Intelligence Providers -> Network Ports -> Summary |
| Check prerequisites | `sudo horizon-grid check` | No Windows Admin Guide analog; verifies Docker/Compose availability before setup |
| Uninstall | `sudo apt remove horizon-grid` / `sudo apt purge horizon-grid` | See below; `horizon-grid uninstall` itself only prints this guidance, it does not perform removal |
| Version | `horizon-grid version` | |

On reconfigure of an existing install, re-entering the existing admin email+password signs in for the wizard session and enables live "Test Connection" calls (`POST /api/v1/providers/{id}/test`, `POST /api/v1/ai/test`) -- identical to Windows. On a fresh install, Test Connection cannot work yet at the provider/AI wizard pages because no backend is running at that point in the flow -- this is an application-level fact true on both platforms, not a Linux limitation.

## File locations: Program Files/ProgramData vs. FHS paths

| Windows | Linux | Contents |
|---|---|---|
| Program Files (app) | `/opt/horizon-grid/app/` | `backend/`, `frontend/`, `docker-compose.yml`, `docker-compose.prod.yml`, `docs/` -- read-mostly |
| ProgramData config | `/etc/horizon-grid/.env` | Real config/secrets; `root:root`, `chmod 600` (verified live) |
| ProgramData backups | `/var/lib/horizon-grid/backups/` | `pg_dump` snapshots |
| ProgramData logs\setup.log | `/var/log/horizon-grid/setup.log` | Setup/wizard log |
| Start Menu shortcut | `/usr/bin/horizon-grid` + `/usr/share/applications/horizon-grid.desktop` | Single CLI entrypoint; desktop menu launcher runs `horizon-grid open` (no custom icon yet -- falls back to a generic one) |
| Windows Service registration | `/lib/systemd/system/horizon-grid.service` | Registered (`daemon-reload`'d) at install time but **not** auto-enabled or started -- nothing starts until you run `horizon-grid configure`, matching the Windows installer's own "nothing auto-starts before configuration" behavior |

Both platforms' Compose project directory shares the basename `app`, so both produce the same Docker Compose project label (`com.docker.compose.project=app`) by design -- useful to know if you're correlating `docker compose ps` output across platforms.

## Uninstall model: remove vs. purge

Linux uses two distinct `apt` verbs, mirroring the Windows uninstaller's own keep-data/remove-everything choice:

- **`sudo apt remove horizon-grid`** -- the direct analog of choosing "keep my data" in the Windows uninstaller. Keeps `/etc/horizon-grid`, `/var/lib/horizon-grid`, and all Docker volumes (Postgres/Neo4j/OpenSearch data). Containers stop, but volumes and config survive; reinstalling later picks up right where you left off. Confirmed live in both the three-distro test suite (33/35 checks passing per distro, both non-blocking exceptions explained in the Linux QA report) and, separately, under the real default project name inside an isolated test environment: containers stopped, volumes/config intact.
- **`sudo apt purge horizon-grid`** -- the direct analog of choosing "remove everything" in the Windows uninstaller. Deletes everything: stops and removes every container and volume labeled for the Compose project, and deletes `/etc/horizon-grid`, `/var/lib/horizon-grid`, and `/var/log/horizon-grid`. No undo.

Cleanup is **label-based** (`com.docker.compose.project=<project>`), not a hardcoded container-name guess, so it works correctly even if you've customized `COMPOSE_PROJECT_NAME`. A dedicated isolated test using the real default project name (`app`) confirmed this logic fully: 12/12 checks passed, including "all containers removed" and "all volumes removed." The full three-distro suite reported the same purge/remove behavior with two non-blocking failures per distro that were specific to that test harness's own project-naming choice (used only to avoid colliding with another instance on the shared test host) -- see **HORIZON_GRID_LINUX_QA_REPORT.pdf** for the complete, unfiltered results.

One packaging fix worth knowing about: earlier builds of `apt purge`/`apt remove` could leave one small untracked file behind (`/opt/horizon-grid/app/.env`, a runtime-written copy dpkg's manifest never tracked), which blocked full removal of that directory. This is fixed in the package's `postrm` script -- the Linux analog (via dpkg not tracking the file, rather than an ACL block) of a documented Windows uninstaller fix for the same underlying problem.

## Firewall handling

Windows Firewall is always present and gets a guaranteed rule from the installer. Linux has no equivalent guarantee -- `horizon-grid configure` and the CLI make a best-effort detection of `ufw` or `firewalld` if active and configure them accordingly, clearly reporting either what it configured or that no firewall manager was detected, rather than assuming one exists.
