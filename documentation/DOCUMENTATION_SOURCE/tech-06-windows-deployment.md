# Windows Deployment Architecture

This section documents the Windows installer for HORIZON GRID: an Inno Setup package (a Windows installer-authoring tool that compiles a self-extracting setup executable) plus a WinForms configuration wizard (.NET's native desktop UI framework — this is not an Electron or browser-based installer). Together they package the same Docker Compose-based runtime described elsewhere in this document for a single-machine Windows install; they do not reimplement the platform as a native Windows service. Docker Compose remains the actual runtime underneath the installer, per an explicit header comment in `windows/installer.iss`.

## 📋 Table of contents

- [What the Installer Actually Does](#-what-the-installer-actually-does)
  - [Prerequisite Checks](#prerequisite-checks)
- [File Layout: Program Files vs. ProgramData](#-file-layout-program-files-vs-programdata)
  - [ACL Protection](#acl-protection)
- [Setup Wizard Page Flow](#-setup-wizard-page-flow)
- [What "Start Installation" Actually Executes](#-what-start-installation-actually-executes)
- [Start Menu Shortcuts](#-start-menu-shortcuts)
- [Upgrade / Reconfigure Flow](#-upgrade--reconfigure-flow)
- [Summary](#-summary)

---

## 🪟 What the Installer Actually Does

`installer.iss` copies the following into `%ProgramFiles%\IOC Intelligence Platform\app\` (Inno Setup's `{autopf}` constant):

- `backend/`
- `frontend/`
- `docker-compose*.yml` (including the production overlay, `docker-compose.prod.yml`, which strips the development bind-mounts and switches the backend/frontend containers to production start commands)
- `docs/`
- `README.md`
- the `windows/scripts` and `windows/wizard` PowerShell used for post-install configuration and day-to-day operation

**Architecture restriction.** The installer sets `ArchitecturesAllowed=x64compatible`, restricting installation to 64-bit-compatible Windows systems. This is consistent with — and enforced a second time by — the prerequisite checker's own verification of a 64-bit Windows 10-or-later host (below): the same constraint is checked once at install-package level and once again at runtime. The source material does not document any further stated engineering rationale (e.g. no claim is made here about 32-bit or ARM64 support one way or the other beyond this).

### Prerequisite Checks

Before any files are copied, a `[Code]`-section step in `installer.iss` runs `Check-Prerequisites.ps1`, which verifies:

- 64-bit Windows 10 or later
- Administrator privileges
- At least 8 GB RAM (soft check)
- Sufficient free disk space
- Docker Desktop installed and running
- Docker Compose v2 available
- The ports the platform needs are free

> [!WARNING]
> Failures surface a "Continue anyway?" prompt rather than a silent abort — the check is advisory-with-friction for at least some of these conditions, not a hard, unbypassable gate.

## 📁 File Layout: Program Files vs. ProgramData

The installer follows the standard Windows split between read-mostly program binaries and writable per-machine application data (`windows/scripts/Common.ps1`, lines 28-40):

| Location | Purpose | Contents |
|---|---|---|
| `%ProgramFiles%\IOC Intelligence Platform\app\` | Installed application code | `backend/`, `frontend/`, compose files, docs, wizard/operational scripts |
| `%ProgramData%\IOC Intelligence Platform\config\.env` | Real runtime secrets and configuration | The generated `.env` consumed by Docker Compose |
| `%ProgramData%\IOC Intelligence Platform\logs\setup.log` | Install/setup logging | Setup Wizard log output |
| `%ProgramData%\IOC Intelligence Platform\backups\` | Database backups | `pg_dump` snapshots; the 10 most recent are retained |

### ACL Protection

`Initialize-DataDirectories` locks the entire `ProgramData\IOC Intelligence Platform\` tree to the Administrators and SYSTEM accounts only, via `icacls` (Windows's command-line ACL — access control list — management tool). This is the only NTFS permission narrowing described in the source material; no per-subfolder differentiation is mentioned beyond this single restrictive ACL applied to the whole tree.

There is one additional wrinkle worth noting precisely because it affects where secrets end up on disk: `docker-compose.yml`'s `env_file: .env` directive resolves relative to the Compose *project* directory, not to whatever path a `--env-file` flag might point at. Because Compose is invoked from inside `{app}\app\`, a helper (`Sync-ComposeEnvFile`) copies the real `.env` from `ProgramData\...\config\.env` into `{app}\app\.env` on every single Compose invocation, and **re-applies the same Administrators+SYSTEM-only ACL to that copy** each time. In other words, there are effectively two on-disk `.env` files with secrets in them by design (the ProgramData original and the app-directory working copy Compose actually reads), and both are kept under the restrictive ACL rather than only the first one.

Secrets themselves are generated using a CSPRNG (cryptographically secure pseudo-random number generator) — specifically .NET's `RandomNumberGenerator` via a `New-RandomSecret` helper, not PowerShell's `Get-Random` — and written out by `Write-EnvFile.ps1`.

## 🧙 Setup Wizard Page Flow

`Setup-Wizard.ps1` is a WinForms application. On launch it self-elevates via UAC (User Account Control) if it isn't already running with a real, non-filtered elevated token. It then walks the operator through a fixed sequence of pages:

**Welcome → Admin Account → AI Configuration → Provider Configuration → Port Review → Summary/Install → Finish**

[FIGURE: tech-06-windows-deployment-diagram-1.png | Diagram: Setup Wizard Page Flow]

Notes on individual pages:

- **Admin Account** — collects the credentials for the operator account the installer will register once the stack is up. Per the platform's own registration logic, the *first* account ever registered against a fresh database is automatically granted the admin role, with no manual database edit required; every registration attempt after that is rejected with `403 Forbidden` rather than silently creating a lesser account. That bootstrap behavior is what makes it safe for this page to simply be "create the admin account" with no separate role picker.
- **Provider Configuration** — presents exactly 8 of the platform's 18 registered intelligence providers, each with a live "Test" button that calls `POST /api/v1/providers/{id}/test` against the running backend: VirusTotal, AbuseIPDB, OTX, the combined abuse.ch group (URLhaus/ThreatFox/MalwareBazaar — one free Auth-Key covers all three), NVD, Hybrid Analysis, Censys, and PhishTank. The wizard's own inline notes match the backend's behavior exactly for the cases checked: Censys requires both a Personal Access Token and an Organization ID, the abuse.ch key is shared across three connectors, and NVD works without a key at a lower rate limit. The remaining 10 backend providers are deliberately absent from this page for two different reasons: 6 (Certificate Transparency lookups, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus, and the internal OSINT crawler) require no credential to collect at all, so there is nothing for this page to configure and no corresponding test handler exists for them either; the other 2 (urlscan.io, Google Safe Browsing) **do** require a credential but are still absent from the wizard on both platforms identically — both are configured after install from the app's own Providers page instead.
- **Port Review** — lets the operator confirm/adjust the host ports the stack will bind, following on from the prerequisite check's "ports free" verification.

## 🏁 What "Start Installation" Actually Executes

Clicking "Start Installation" on the Summary/Install page runs, in order:

1. Writes `.env` via `Write-EnvFile.ps1`, using the values collected across the previous pages plus CSPRNG-generated secrets.
2. Runs `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` — the production overlay swaps in production start commands and drops the development bind-mounts.
3. Polls the backend's `/health` endpoint for up to 3 minutes, waiting for the stack to come up.
4. Registers the admin account by calling `POST /api/v1/auth/register` with the credentials from the Admin Account page, then logs in.

Nothing here is a distinct "installer-native" install step beyond orchestrating the same Docker Compose commands and HTTP calls an operator could run by hand — the wizard's value is sequencing and validating them, not replacing them.

## 📌 Start Menu Shortcuts

The installer's `[Icons]` section creates the following (plus an optional desktop icon):

| Shortcut | What it does |
|---|---|
| Open Platform | Runs `Open-Platform.ps1` (also the default desktop icon action): checks stack health first, starts Docker Desktop if it isn't already running, starts the stack, then opens the browser to the platform. |
| Configuration | Re-runs the Setup Wizard. On an existing install this sets an upgrade flag (`$State.IsUpgrade`) that changes the wizard's behavior — see Upgrade/Reconfigure below. |
| Start Platform | Runs `Service-Start.ps1`: `docker compose up -d`, then polls `/health`. |
| Stop Platform | Runs `Service-Stop.ps1`: `docker compose stop` (no `-v` flag, so container data/volumes are preserved, not deleted). |
| Restart Platform | Listed in the installer's icon set; the facts available do not detail its script-level implementation beyond the name (presumably a stop-then-start sequence, not confirmed). |
| Service Status | Listed in the installer's icon set; specific implementation not detailed in the source material beyond the name. |
| Backup Database Now | Manually triggers an on-demand database backup using the same `pg_dump`-against-the-running-postgres-container mechanism (`Backup-Database.ps1`) that runs automatically before an upgrade (see below). |
| Diagnostics | Listed in the installer's icon set; specific implementation not detailed in the source material beyond the name. |
| Documentation | Opens the installed documentation (`docs/`, `README.md`) copied in at install time. |
| Uninstall | Invoked via `[Code]` in `installer.iss`; offers "Remove Application" (keeps `ProgramData` and Docker volumes intact) versus "Remove Everything" (requires typing `DELETE` to confirm; runs `docker compose down -v` and deletes `ProgramData`). |

## 🆙 Upgrade / Reconfigure Flow

Re-running the Setup Wizard from the **Configuration** shortcut on a machine that already has the platform installed sets `$State.IsUpgrade = true` internally, which changes two things before the operator sees any page:

1. **Pre-population**: the wizard parses the existing `.env` (from `ProgramData\...\config\.env`) and uses it to pre-fill the wizard's fields, so re-running Configuration is a "review and adjust" flow rather than starting from a blank slate.
2. **Pre-install backup**: before anything else changes, the wizard backs up the database by running `Backup-Database.ps1`, which executes `pg_dump` inside the already-running Postgres container. This backup lands in `ProgramData\...\backups\`, alongside the same rolling most-recent-10-retained snapshots used elsewhere.

From there the wizard proceeds through the same page flow (Welcome → Admin Account → … → Summary/Install → Finish) and "Start Installation" re-runs the same `docker compose ... up -d --build` / health-poll sequence described above.

> [!NOTE]
> The source material does not specify whether the final admin-account registration call is skipped or altered on an upgrade path versus a fresh install — this detail is **not confirmed** and should not be assumed either way without checking the wizard script directly.

## 📝 Summary

The Windows installer's job is narrowly scoped: verify the host can run the stack, lay down application files under Program Files, collect configuration through a WinForms wizard, generate and lock down secrets under a restrictive ACL in ProgramData, and drive the same `docker compose` commands and REST calls an operator could otherwise run manually. It intentionally leaves Docker Compose as the real runtime rather than replacing it with a native Windows service, and it protects the resulting secrets primarily through NTFS ACLs (Administrators + SYSTEM only) on the `.env` file(s) and CSPRNG-based secret generation, rather than through any OS-level secret store.
