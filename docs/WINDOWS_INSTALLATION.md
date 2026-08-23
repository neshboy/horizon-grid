# Windows Installation

A guided, wizard-driven install for Windows 10/11 (64-bit). No command line, no
editing config files by hand, no prior knowledge of Docker, Python, Node, or
environment variables required.

The installer packages the *same* platform described in
[INSTALL.md](INSTALL.md) / [DEPLOYMENT.md](DEPLOYMENT.md) — it does not
reimplement anything. Docker Compose is still the real runtime; the installer
and setup wizard exist purely to make getting there a normal Windows
install experience.

## What you need before you start

- **Windows 10 or 11, 64-bit.** The installer checks this and will not
  proceed on 32-bit Windows or unsupported builds.
- **Administrator rights** on the machine. You'll see a UAC ("Do you want to
  allow this app...") prompt — this is required, not optional, because the
  installer writes to `Program Files` and `ProgramData` and manages Docker
  containers.
- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)**,
  installed and running, *before* you run the setup wizard. The installer's
  prerequisite check will tell you clearly if Docker Desktop isn't detected
  or isn't running yet — install/start it and re-run the check rather than
  proceeding with a broken install.
- **At least 8 GB RAM and ~8 GB free disk space.** The full stack (Postgres,
  Redis, Neo4j, OpenSearch, the backend, the frontend, two Celery processes)
  is genuinely heavy; the prerequisite check warns if you're under 8 GB RAM
  but doesn't hard-block it — the platform will just feel slow.
- **Internet access**, at least for the initial install (pulling base Docker
  images, and for whichever AI backend / providers you configure — see
  [Internet requirements](#internet-requirements) below).

You do **not** need: Python, Node.js, PostgreSQL, Redis, a code editor, or any
familiarity with `.env` files or the command line. The wizard handles all of
that.

## Step 1: Run the installer

Download `HORIZON-GRID-Setup-<version>.exe` and double-click it.

1. **UAC prompt** — click Yes. The installer needs admin rights to write to
   `Program Files` and `ProgramData` and to manage Docker.
2. **Destination folder** — defaults to
   `C:\Program Files\IOC Intelligence Platform`. Most people should leave
   this as-is; change it only if you have a specific reason to.
3. **Ready to Install** — the installer runs a prerequisite check here
   (Docker Desktop installed and running, disk space, RAM, Administrator
   privileges). If something's missing, you'll see exactly what and can fix
   it and retry, or choose to continue anyway at your own risk.
4. Files copy in. This is fast — copying source files, not downloading
   anything yet.
5. At the end, check **"Launch the setup wizard now"** (checked by default)
   and click Finish.

## Step 2: The setup wizard

This is where the platform actually gets configured. Every page has a
**Back** button if you want to change something before finishing, and
nothing is written to disk or started until you click **Start Installation**
on the final page.

1. **Welcome** — a plain overview of what's about to happen.
2. **Administrator Account** — the email and password for your first user
   account. The platform's own rule is that the *first* account registered
   becomes the Administrator automatically — there's no separate "make
   someone an admin" step to forget.
3. **AI Configuration** — pick an AI backend:
   - **Ollama** (default) — runs locally, no API key, no cost, but you need
     [Ollama](https://ollama.com) installed separately and a model pulled
     (`ollama pull llama3.2:3b` or similar) *on the Windows host*, not inside
     a container.
   - **Anthropic**, **AWS Bedrock**, or **Google Gemini** — cloud-hosted,
     each needs its own API key/credentials, entered directly in this page.
   - You can leave this on Ollama and switch later by re-running the wizard
     from the Start Menu ("Configuration").
4. **Threat Intelligence Providers** — every provider is optional. Paste in
   whichever API keys you have; leave the rest blank. Each card has a **Test**
   button, but it only works *after* the platform is actually running with an
   admin account (i.e., not yet, on this page, the first time through) — the
   status text explains this and tells you to come back via "Configuration"
   later to verify a key.
5. **Network Ports** — the platform needs 7 ports on your machine (web
   interface, backend API, and 5 internal service ports). If something else
   on your machine is already using one, the wizard detects it and suggests
   the next free port automatically — you don't have to go hunting for a
   free port yourself.
6. **Summary** — a plain-language recap of what you configured, then a
   **Start Installation** button. Clicking it:
   - Writes your configuration to a protected file.
   - Runs `docker compose up --build`, which builds and starts every
     container. **This step genuinely takes a few minutes the first time**
     (subsequent starts are fast) — a progress log shows what's happening.
   - Waits for the backend to report healthy.
   - Creates your administrator account and signs you in.
   - Only then does the page let you click Next.
7. **Finish** — a link to open the platform in your browser (checked by
   default), and you're done.

## Internet requirements

- **Docker image pulls** (first install only) need internet access.
- **Ollama** runs fully offline once a model is pulled — no ongoing internet
  requirement.
- **Anthropic / Bedrock / Gemini** all require internet access for every AI
  request, since they're cloud APIs.
- **Threat intelligence providers** (VirusTotal, AbuseIPDB, OTX, NVD,
  abuse.ch, etc.) each require internet access to their respective API when
  used — the platform works fine with any subset of them configured,
  including none.

None of this is hidden or silent: if a provider or the AI backend can't reach
the internet, you'll see a clear error in that specific result, not a crash.

## Where things live

Matching standard Windows conventions:

- **`C:\Program Files\IOC Intelligence Platform\app\`** — the application
  itself (backend, frontend, Docker Compose files). Read-mostly; you
  shouldn't need to touch anything here directly.
- **`C:\ProgramData\IOC Intelligence Platform\`**:
  - `config\.env` — your real configuration (API keys, database
    credentials, JWT signing secret). Locked down to Administrators and
    SYSTEM only via NTFS permissions — a non-administrator account on the
    same machine cannot read it.
  - `logs\setup.log` — a plain-text log of what the wizard/installer did.
  - `backups\` — automatic database backups taken before every upgrade (see
    [WINDOWS_ADMINISTRATION.md](WINDOWS_ADMINISTRATION.md)).

## Upgrading an existing install

Re-run the installer with a newer version, or launch **Configuration** from
the Start Menu on an existing install. The wizard detects an existing
configuration automatically ("Reconfigure HORIZON GRID" instead
of "Welcome") and:

- Pre-fills every setting with your current values.
- Leaves the administrator account and password fields blank by default —
  blank means "keep the existing account unchanged," not "no account."
- Takes an automatic database backup before touching anything, whenever it
  detects this is an upgrade rather than a fresh install.
- All your cases, investigations, watchlists, and notes are untouched —
  they live in the Postgres/Neo4j Docker volumes, which the wizard never
  deletes during a normal reconfigure/upgrade.

## Uninstalling

Uninstall from **Settings → Apps** or the Start Menu's "Uninstall" shortcut.
You'll be asked to choose:

- **Remove Application** (the default) — removes the installed files and
  stops the containers, but keeps your configuration, credentials, and all
  investigation data. A future reinstall picks up exactly where you left
  off.
- **Remove Everything** — permanently deletes the database, all cases and
  investigations, and every saved credential. This requires typing `DELETE`
  to confirm; there is no undo and no automatic backup for this path, since
  it exists specifically for people who genuinely want a clean slate.

See [WINDOWS_TROUBLESHOOTING.md](WINDOWS_TROUBLESHOOTING.md) if anything
here doesn't go as described.
