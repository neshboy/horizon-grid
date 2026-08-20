# Windows Administration

Day-to-day operation of a Windows-installed HORIZON GRID: the
Start Menu shortcuts, backups, upgrades, and where things live. For install
steps see [WINDOWS_INSTALLATION.md](WINDOWS_INSTALLATION.md); for problems,
see [WINDOWS_TROUBLESHOOTING.md](WINDOWS_TROUBLESHOOTING.md).

## Start Menu shortcuts

All under **Start Menu → IOC Intelligence Platform**. Every one of these
runs elevated (you'll see a UAC prompt) — this is required, not a bug: the
platform's configuration file is locked down to Administrators-only via NTFS
permissions, and being a member of the Administrators group is not, by
itself, enough to read an Administrators-ACL'd file from a normally-launched
process. Windows UAC hands a normal (non-elevated) process a *filtered*
token even for an admin account, and that filtered token cannot satisfy the
ACL. Every shortcut here calls `Assert-Elevated` first specifically to
handle this correctly rather than failing with a confusing "not configured"
message.

| Shortcut | What it does |
|---|---|
| **Open Platform** | Opens the web interface in your default browser. |
| **Configuration** | Re-runs the setup wizard against your existing install — change the AI backend, provider keys, ports, or reset the administrator password. Pre-fills every field with your current values. |
| **Start Platform** | Starts all Docker containers (`docker compose up -d`) and waits for the backend to report healthy. |
| **Stop Platform** | Stops all containers without deleting anything — your data stays in the Docker volumes untouched. |
| **Restart Platform** | Stop + Start in one step — the first thing to try if something seems stuck. |
| **Service Status** | Shows container status, backend/frontend health, and whether Docker Desktop itself is running. Opens a console window and stays open so you can read it. |
| **Backup Database Now** | Takes an immediate `pg_dump` snapshot into the backups folder (see below). Runs automatically before every upgrade too — this is for backing up on demand, e.g. right before you try something risky. |
| **Diagnostics** | Builds a redacted `.zip` on your Desktop with container logs, status, and system info — secrets are stripped before anything is written. Use this if you need to share details for troubleshooting. |
| **Documentation** | Opens the docs folder (this file and everything else under `docs/`). |
| **Uninstall** | Standard Windows uninstaller — see [WINDOWS_INSTALLATION.md](WINDOWS_INSTALLATION.md#uninstalling). |

## Where things live

- **`C:\Program Files\IOC Intelligence Platform\app\`** — the application
  itself. Docker builds images from here; you shouldn't need to edit
  anything in this folder directly.
- **`C:\ProgramData\IOC Intelligence Platform\`**
  - **`config\.env`** — your real configuration: API keys, database
    credentials, JWT signing secret. Locked to Administrators + SYSTEM.
    Never edit this by hand — use **Configuration** from the Start Menu,
    which regenerates it correctly and re-applies the file permissions
    every time.
  - **`logs\setup.log`** — a plain-text, human-readable log of every
    install/upgrade/configuration action. No secret values are ever
    written here — only variable names and "was set" / "was not set", not
    the actual key material.
  - **`backups\`** — automatic `pg_dump` snapshots (`postgres-<timestamp>.sql`),
    taken before every upgrade and by the "Backup Database Now" shortcut.
    The 10 most recent are kept; older ones are pruned automatically so this
    folder doesn't grow forever.

## Backups

A backup is taken **automatically** every time the setup wizard detects an
upgrade (i.e., you already have a configuration and you're re-running the
wizard or reinstalling) — before it touches anything. You don't have to
remember to do this yourself for the one case that matters most.

For anything else — before manually poking at the database, before a risky
provider/AI backend change, or just for peace of mind — use **Backup Database
Now** from the Start Menu.

**Restoring** a backup is a manual step, deliberately not automated (an
automatic restore is one of the more dangerous things a setup wizard could
silently do wrong): use **Restore Database** from the Start Menu, which
stops only the services that write to the database (backend, celery worker,
celery beat) -- Postgres itself stays running, since a restore needs a live
server to connect to -- drops and recreates the database, replays the
backup file, then restarts what it stopped. It asks for an explicit typed
confirmation first, since this permanently discards anything written since
the backup was taken. Pass a specific file with `-BackupFile <path>`, or
run it with no arguments to restore the most recent backup automatically.

## Upgrading

Re-run a newer installer, or just launch **Configuration** to review/change
settings on the current version. Either way:

1. A database backup is taken automatically first.
2. Your configuration is pre-loaded — nothing is reset to defaults.
3. `docker compose up --build` picks up any code/image changes.
4. Your cases, investigations, watchlists, and notes are all untouched —
   they live in Docker volumes the upgrade path never deletes.

## Changing the administrator password

Currently there's no dedicated "reset password" flow distinct from the setup
wizard — leaving the Administrator Account page's password fields blank
during a reconfigure keeps your existing account and password unchanged. To
actually change the password, use the platform's own web UI once logged in
(if that flow exists); re-registering is not an option once an admin account
exists — `POST /api/v1/auth/register` now rejects every attempt with `403
Forbidden` after the first account is created, rather than creating a second,
non-admin account — this is a known gap, tracked for a future version rather
than something the installer works around.

## Stopping the platform without uninstalling

Use **Stop Platform**, or just quit Docker Desktop — either stops the
containers. Nothing is deleted either way; **Start Platform** (or just
starting Docker Desktop again, if you'd set up containers to auto-start)
brings everything back exactly as it was.
