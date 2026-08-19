# Welcome to HORIZON GRID for Linux

Welcome, and thank you for installing HORIZON GRID.

HORIZON GRID is an IOC (Indicator of Compromise) threat-intelligence platform. Under the hood it is made up of several coordinated services — a PostgreSQL database, Redis, Neo4j, OpenSearch, a FastAPI backend, a Next.js web frontend, and two background worker processes — all run together using Docker Compose. You interact with all of it through a normal web browser, the same way you would use any website; there is no separate desktop application window to open.

This guide assumes you have never used a Linux terminal, `apt`, or a text-based setup wizard before. Every command you need to type is shown in a gray box exactly as you should type it. You do not need to understand everything happening behind the scenes to follow these steps successfully.

By the end of this guide you will have:

- Verified and installed the HORIZON GRID package
- Installed a working copy of Docker (this has one important gotcha — see below)
- Run the setup wizard to create your administrator account and configure the platform
- Learned how to start, stop, back up, and, if you ever need to, uninstall HORIZON GRID

# Before You Begin: Prerequisites

## Supported Linux distributions

HORIZON GRID has been tested for this release on:

- **Ubuntu 24.04 LTS**
- **Ubuntu 22.04 LTS**
- **Debian 12 ("bookworm")**

These are the only distributions currently supported. HORIZON GRID does not rely on anything unusual — it is a standard Docker Compose application managed by a standard `systemd` service — so other modern Debian- or Ubuntu-based distributions may well work too. However, they have not been tested, so please treat anything outside the three listed above as unsupported and use it at your own risk.

## What you need before starting

1. **A 64-bit (amd64) machine** running one of the distributions above.
2. **A user account with `sudo` access.** Every HORIZON GRID command that changes system state needs to be run with `sudo`.
3. **An internet connection**, at least for the initial install — Docker will need to download the platform's container images the first time you set it up.
4. **The HORIZON GRID package itself**: `horizon-grid_0.2.1_amd64.deb` (approximately 6.1 MB / 5.8 MiB). This package does not contain any application dependencies or pre-built container images — those are downloaded and built inside Docker the first time you run setup, which is exactly why the package itself is so small despite the platform being substantial.
5. **Docker**, installed the correct way — see the critical note below before you do anything else.

# Step 1: Download and Verify the Installer

Download `horizon-grid_0.2.1_amd64.deb` from wherever it was provided to you (for example, a release page or a link shared by your administrator), and save it somewhere convenient, such as your home folder or `~/Downloads`.

Before installing anything, it is good practice to verify that the file you downloaded is genuine and was not corrupted or tampered with in transit. Open a terminal, go to the folder where you saved the file, and run:

```bash
sha256sum horizon-grid_0.2.1_amd64.deb
```

Compare the long string of letters and numbers this prints against the official checksum below. They must match **exactly**:

```
57d0db31d4e67dfd8ccad9f0c9dfbbf6e501382e3972f0a538f8cc4b7b912812
```

If the value printed on your screen does not match this exactly, do not install the file — download it again from a trusted source.

# Step 2: Install Docker (Critical — Read This Before Installing HORIZON GRID)

HORIZON GRID runs entirely on top of Docker and the Docker Compose plugin. This step matters more than it might look, so please read it carefully.

**Do not simply run `sudo apt install docker.io` and assume you're done.** On Debian 12, Ubuntu 22.04, and Ubuntu 24.04, the distribution's own `docker.io` package does **not** include the modern Docker Compose v2 plugin that HORIZON GRID requires. If you install only `docker.io`, running a compose command will fail with an error like:

```
docker: 'compose' is not a docker command.
```

On Debian 12 specifically, there is not even a fallback Compose v2 package in the distribution's own repositories — only the old, deprecated standalone `docker-compose` (v1) binary, which is not what this platform needs.

**The correct, working way to install Docker** is to use Docker's own official convenience script:

```bash
curl -fsSL https://get.docker.com | sh
```

This installs current Docker Engine together with the Compose v2 plugin, which is exactly what HORIZON GRID needs. (If you prefer not to use the convenience script, you can instead follow Docker's own manual instructions for adding their official apt repository at https://docs.docker.com/engine/install/ — just make sure whichever method you choose ends with `docker compose version` working, as a *subcommand* of `docker`, not a separate `docker-compose` binary.)

After installing, confirm it worked:

```bash
docker compose version
```

If this prints a version number instead of an error, Docker is ready and you can move on to Step 3.

If your user account is not already in the `docker` group, you may need to prefix Docker commands with `sudo`, or add yourself to the group and log out and back in. HORIZON GRID's own commands (see later sections) already run with `sudo`, so this mainly matters if you want to run plain `docker` commands yourself.

# Step 3: Install the HORIZON GRID Package

With Docker working, install the `.deb` package itself. From the folder where you downloaded it, run:

```bash
sudo apt update
sudo apt install ./horizon-grid_0.2.1_amd64.deb
```

(The `./` in front of the filename is important — it tells `apt` to install this specific local file rather than searching for a package by that name in a repository.)

This will:

- Install the HORIZON GRID files under `/opt/horizon-grid/app/`
- Install the `horizon-grid` command-line tool to `/usr/bin/horizon-grid`
- Register (but **not** start or enable) a systemd service definition at `/lib/systemd/system/horizon-grid.service`
- Add a HORIZON GRID entry to your desktop's application menu (it will use a generic icon, since no custom icon has been created for this release yet)

Nothing is started automatically at this point — exactly like the Windows installer, HORIZON GRID deliberately waits until you have configured it before anything runs.

Once installation finishes, it's worth double-checking that your system has everything HORIZON GRID needs:

```bash
sudo horizon-grid check
```

This checks your prerequisites (such as Docker being present and working) and tells you plainly if anything is missing before you proceed.

# Step 4: Run the Setup Wizard

Now it's time to configure HORIZON GRID for the first time. Run:

```bash
sudo horizon-grid configure
```

This launches a text-based setup wizard in your terminal. It works like a series of question-and-answer screens — read each one, type your answer or press Enter to accept a default, and move to the next page. It follows the same steps, in the same order, as HORIZON GRID's Windows setup wizard:

**1. Welcome page.** An introduction to the wizard; press Enter/continue to proceed.

**2. Administrator Account.** Here you create the very first login for the platform itself — the email address and password you will use to sign in to the HORIZON GRID web application once it's running. Choose a strong password; this is your primary administrator account.

**3. AI Configuration.** Choose and configure the AI backend that will power HORIZON GRID's AI-generated threat assessments — for example, a locally-run backend such as Ollama, or a cloud-based backend such as Groq — and enter whatever connection details or API key that choice requires.

**4. Threat Intelligence Providers.** This page lets you enter API keys for the threat-intelligence providers that HORIZON GRID's wizard can configure directly:

- VirusTotal
- AbuseIPDB
- AlienVault OTX
- NIST NVD (key optional)
- The shared abuse.ch key (this single key activates three feeds at once: URLhaus, ThreatFox, and MalwareBazaar)
- Hybrid Analysis
- Censys (requires **both** a Personal Access Token and an Organization ID together)
- PhishTank (key optional)

You can leave any of these blank and fill them in later — a provider without a key simply won't be used until you add one.

A number of other providers do **not** need any credential at all (crt.sh, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus, and the built-in Internet Intelligence Collector), and some newer providers (urlscan.io, Google Safe Browsing) are configured after installation from inside the application itself, on the **Providers** page once you're signed in — not from this wizard. This is identical on Windows and Linux, since provider configuration after install is a feature of the application, not the installer.

On a brand-new install, the **Test Connection** option on this page and the AI Configuration page cannot actually contact anything yet, because the backend service isn't running at this point in the setup process — this is true on Windows too, not a Linux limitation. If you ever run `horizon-grid configure` again later to reconfigure an *existing* install, entering your existing administrator email and password early in the wizard signs you in for that session, and Test Connection will work for real at that point.

**5. Network Ports.** Review the network ports HORIZON GRID will use (see the Ports section below for the defaults). If the wizard detects that a port is already in use on your machine, it will offer you the next available one instead.

**6. Summary.** A final review screen showing everything you've entered. Confirm to proceed.

After you confirm the summary, the wizard does the real work automatically:

1. Writes your configuration to `/etc/horizon-grid/.env` (locked down to root-only access)
2. Runs `docker compose up -d --build`, which downloads and builds all the container images — **this can take a while the first time**, since it's downloading a substantial amount of software
3. Waits for the backend to report healthy
4. Creates your administrator account (fresh installs only)
5. Confirms it can sign in with that account

Once the wizard finishes successfully, HORIZON GRID is running and ready to use.

# Accessing HORIZON GRID

HORIZON GRID is a web application — you use it in your browser, not through a separate desktop window.

## From the same machine

Open a browser and go to:

```
http://localhost:3000
```

You can also just run:

```bash
sudo horizon-grid open
```

which starts HORIZON GRID if it isn't already running, then opens it in your default browser for you.

There is also a HORIZON GRID entry in your desktop's application menu, which does the same thing.

## From another device on your network

The frontend (port 3000) and backend API (port 8000) are intentionally published on all network interfaces, so other devices on the same local network can reach HORIZON GRID too — for example, from a laptop elsewhere in your office. From another device, browse to:

```
http://<the-server's-LAN-IP-address>:3000
```

replacing `<the-server's-LAN-IP-address>` with the actual IP address of the machine HORIZON GRID is installed on.

If your machine has a firewall active (such as `ufw` or `firewalld`), the setup wizard makes a best-effort attempt to detect it and open the necessary ports, and will tell you plainly whether it found one to configure or found none at all. Unlike Windows, which always ships with Windows Firewall present, there's no guarantee a firewall is running on any given Linux system, so don't assume LAN access is blocked (or allowed) without checking your own firewall configuration if you have one.

## Ports reference

| Service | Port | Reachable from |
|---|---|---|
| Frontend (web UI) | 3000 | Any device on the network |
| Backend API | 8000 | Any device on the network |
| PostgreSQL | 5433 | This machine only (127.0.0.1) |
| Redis | 6379 | This machine only (127.0.0.1) |
| Neo4j (HTTP) | 7475 | This machine only (127.0.0.1) |
| Neo4j (Bolt) | 7688 | This machine only (127.0.0.1) |
| OpenSearch | 9200 | This machine only (127.0.0.1) |

The frontend and backend are reachable from other machines by design, so you can use HORIZON GRID from anywhere on your LAN. The four data stores (Postgres, Redis, Neo4j, OpenSearch) are deliberately restricted to the local machine only, for security, and are not meant to be reached directly from other devices.

# Managing HORIZON GRID

All day-to-day management is done through the single `horizon-grid` command. Most subcommands need `sudo` because they manage system services and protected files.

## CLI command reference

| Command | What it does |
|---|---|
| `sudo horizon-grid configure` | Runs the setup wizard (initial setup, or to reconfigure an existing install) |
| `sudo horizon-grid start` | Starts HORIZON GRID |
| `sudo horizon-grid stop` | Stops HORIZON GRID |
| `sudo horizon-grid restart` | Restarts HORIZON GRID |
| `sudo horizon-grid status` | Shows whether HORIZON GRID is currently running |
| `sudo horizon-grid open` | Starts HORIZON GRID if needed, then opens it in your browser |
| `sudo horizon-grid backup` | Creates a database backup snapshot |
| `sudo horizon-grid diagnostics` | Produces a diagnostics bundle, with all credentials redacted |
| `sudo horizon-grid check` | Checks that prerequisites (like Docker) are in place |
| `sudo horizon-grid uninstall` | Prints guidance on how to remove or purge HORIZON GRID via `apt` |
| `horizon-grid version` | Prints the installed version |

## Everyday use

Check whether it's currently running:

```bash
sudo horizon-grid status
```

Stop it (for example, before doing system maintenance):

```bash
sudo horizon-grid stop
```

Start it again:

```bash
sudo horizon-grid start
```

Restart it (stop, then start again in one step):

```bash
sudo horizon-grid restart
```

HORIZON GRID is registered with `systemd` when the package is installed, but it is never automatically enabled or started on its own — nothing runs until you've configured it and started it yourself, whether by the wizard or by these commands.

# Backing Up and Restoring Your Data

## Creating a backup

To create a backup of your HORIZON GRID database, run:

```bash
sudo horizon-grid backup
```

This produces a PostgreSQL database snapshot (a `pg_dump` file) and stores it in:

```
/var/lib/horizon-grid/backups/
```

It's good practice to run this periodically, and especially before any major change (such as an upgrade or an uninstall).

## Restoring a backup

There is currently no dedicated one-command `horizon-grid restore` option — only automated backups are provided through the CLI. Restoring a saved snapshot is a standard PostgreSQL restore operation: it involves loading the saved `.sql` file back into the running Postgres container using standard PostgreSQL tools (such as `docker compose exec` together with `psql`). If you need to restore a backup, this should be done carefully by whoever administers the system, following your organization's normal PostgreSQL restore practices, using the snapshot file saved above.

# Where Everything Lives on Disk

HORIZON GRID follows standard Linux filesystem conventions, which keep the application itself separate from its configuration and data — similar in spirit to how a Windows install separates Program Files from ProgramData.

| Location | Contents |
|---|---|
| `/opt/horizon-grid/app/` | The application itself (backend, frontend, Docker Compose files) — read-mostly |
| `/etc/horizon-grid/.env` | Your real configuration and secrets. Locked down: owned by `root:root`, permission `600` (only root can read it) |
| `/var/lib/horizon-grid/backups/` | Database backup snapshots produced by `horizon-grid backup` |
| `/var/log/horizon-grid/setup.log` | Setup wizard log file |
| `/usr/bin/horizon-grid` | The command-line tool itself |
| `/lib/systemd/system/horizon-grid.service` | The systemd service definition |
| `/usr/share/applications/horizon-grid.desktop` | The desktop menu launcher entry |

# Troubleshooting

**`docker: 'compose' is not a docker command`**
This means Docker is installed but the Compose v2 plugin is missing — almost always because Docker was installed via `apt install docker.io` alone instead of Docker's official convenience script. Revisit Step 2 above and install Docker using `curl -fsSL https://get.docker.com | sh`.

**A `horizon-grid` command says permission denied, or seems to silently do nothing**
Almost every `horizon-grid` command needs to modify system-level files or services, so it needs `sudo`. Re-run the command with `sudo` in front of it.

**The setup wizard's "Test Connection" doesn't work on a fresh install**
This is expected. On a brand-new install, the backend service isn't running yet at the point the wizard asks about your AI backend or threat-intelligence providers, so there's nothing to test against yet. Finish the wizard, let it start the platform, and then use the in-app Providers page (or re-run `sudo horizon-grid configure` to reconfigure, signing in with your existing admin account) to actually test a connection.

**A provider shows a status of "not_configured"**
This simply means no API key has been entered for that provider yet. It is not an error — providers that need a key sit idle and report this status honestly until you supply one, either through the setup wizard or from the in-app Providers page after signing in.

**An investigation shows "AI-generated assessment unavailable (generation error)" instead of a verdict**
This is a safety feature working as intended, not a bug. HORIZON GRID's threat score is always calculated deterministically by its own scoring engine — the AI is never allowed to invent or override that score. If the platform's consistency checker detects that the AI's proposed verdict doesn't actually match the real calculated score, it rejects the AI's answer (retrying once) and honestly falls back to "Unknown" rather than show you something misleading. The individual provider results and summaries underneath are unaffected and remain fully available — only the AI's narrative summary is withheld in that case.

**Something else has gone wrong and you need more detail**
Run:

```bash
sudo horizon-grid diagnostics
```

This produces a diagnostics bundle you (or whoever supports your install) can review, with every credential automatically redacted (shown as `KEY=***REDACTED***(set, N chars)` or `KEY=(empty)`) so it's safe to share without exposing secrets. You can also check `/var/log/horizon-grid/setup.log` directly.

**A port the wizard wants to use is already taken by something else**
The setup wizard automatically detects this during the Network Ports page and offers you the next free port instead — you don't need to free the port yourself, just accept the alternative it suggests.

# Uninstalling HORIZON GRID

If you ever need to uninstall, running:

```bash
sudo horizon-grid uninstall
```

will print guidance on your two real options below — it does not remove anything by itself; the actual removal happens through `apt`, using one of the following two commands.

## `sudo apt remove horizon-grid` — keep your data

```bash
sudo apt remove horizon-grid
```

This stops and removes the HORIZON GRID application and its containers, but **keeps**:

- `/etc/horizon-grid` (your configuration)
- `/var/lib/horizon-grid` (your backups)
- All Docker volumes (your Postgres, Neo4j, and OpenSearch data)

If you reinstall HORIZON GRID later, it picks up right where you left off — nothing is lost. Choose this option if you're uninstalling temporarily, upgrading, or just want a clean slate on the application files without losing your data.

## `sudo apt purge horizon-grid` — delete everything

```bash
sudo apt purge horizon-grid
```

This deletes **everything**: every container and every Docker volume belonging to HORIZON GRID (all of your investigation history and settings), plus `/etc/horizon-grid`, `/var/lib/horizon-grid`, and `/var/log/horizon-grid` entirely. **There is no undo.** Only choose purge if you genuinely want no trace of HORIZON GRID or its data left on the machine.

Cleanup in both cases works by identifying containers and volumes that belong to your HORIZON GRID installation, so it correctly finds and removes the right resources even if an administrator has customized the underlying Compose project name.

If you have any data you might want later, run `sudo horizon-grid backup` first, regardless of which of the two commands you plan to use.

# Quick Reference

| Item | Value |
|---|---|
| Supported distributions | Ubuntu 24.04 LTS, Ubuntu 22.04 LTS, Debian 12 (bookworm) |
| Package | `horizon-grid_0.2.1_amd64.deb` (~6.1 MB / 5.8 MiB) |
| Package SHA256 | `57d0db31d4e67dfd8ccad9f0c9dfbbf6e501382e3972f0a538f8cc4b7b912812` |
| Install Docker (required first) | `curl -fsSL https://get.docker.com \| sh` |
| Install the package | `sudo apt install ./horizon-grid_0.2.1_amd64.deb` |
| Check prerequisites | `sudo horizon-grid check` |
| Run setup / reconfigure | `sudo horizon-grid configure` |
| Open in browser | `sudo horizon-grid open` |
| Web UI (this machine) | `http://localhost:3000` |
| Web UI (from LAN) | `http://<server-IP>:3000` |
| Backend API port | 8000 |
| Start / Stop / Restart | `sudo horizon-grid start` / `stop` / `restart` |
| Check status | `sudo horizon-grid status` |
| Back up database | `sudo horizon-grid backup` |
| Backup location | `/var/lib/horizon-grid/backups/` |
| Configuration/secrets | `/etc/horizon-grid/.env` (root-only, mode 600) |
| Setup log | `/var/log/horizon-grid/setup.log` |
| Diagnostics bundle (secrets redacted) | `sudo horizon-grid diagnostics` |
| Uninstall, keep data | `sudo apt remove horizon-grid` |
| Uninstall, delete everything | `sudo apt purge horizon-grid` |
| Version | `horizon-grid version` |
