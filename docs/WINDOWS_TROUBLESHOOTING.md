# Windows Troubleshooting

Common problems with the Windows installer/wizard and how to fix them. For
general (non-Windows-specific) platform issues, see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## "Docker Desktop is not running" during the prerequisite check

The check looks for a live, responding Docker engine (`docker info`), not
just whether Docker Desktop's process is running or its Windows service is
started — WSL2-backed Docker Desktop installs don't always run the legacy
`com.docker.service` Windows service, so checking for that specifically
would give false negatives. Fix: open Docker Desktop from the Start Menu and
wait for it to fully start (the whale icon in the system tray stops
animating), then retry.

## The setup wizard shows a UAC prompt every time — is that normal?

Yes. The platform's configuration file
(`C:\ProgramData\IOC Intelligence Platform\config\.env`) is locked down to
Administrators + SYSTEM via NTFS permissions specifically so a non-admin
account on the same machine can't read your API keys or database
credentials. Being a *member* of the Administrators group is not enough on
its own to satisfy that ACL from a normally-launched process — Windows UAC
gives even an admin account a filtered token unless a process is genuinely
elevated. Every shortcut this platform installs self-elevates for exactly
this reason. Declining the prompt means that shortcut can't do its job.

## "Application files not found" when clicking Start Installation

This means `C:\Program Files\IOC Intelligence Platform\app\` is missing or
incomplete — the installer's file-copy step didn't finish correctly.
Uninstall and reinstall; if it happens again, check available disk space
(the prerequisite check requires ~8 GB free, but the actual copy needs
noticeably less — a nearly-full drive can still fail partway through a
copy that passed the initial check).

## The wizard's "Test" button on a provider says to come back later

This is expected the *first* time through the wizard, before the platform
is actually running: testing a provider key requires a real HTTP call
through the backend, authenticated as your admin account — and neither
exists yet on a fresh install. Finish the wizard (which starts the platform
and creates your account), then reopen **Configuration** from the Start
Menu to test provider keys against the now-running backend.

## Ports conflict / "In use -- try XXXX"

Something else on your machine already has that port. The wizard already
suggests the next free port automatically on the Network Ports page — accept
the suggestion (or pick your own) and continue. This is not a platform bug;
it's genuinely just port contention with something else on your PC (a
previous install, another Docker project, IIS, etc.).

## `docker compose up` fails or times out during Start Installation

Check, in order:

1. **Is Docker Desktop actually running?** Not just installed — check the
   system tray icon.
2. **Is there enough disk space for image layers?** The full stack pulls/
   builds several images; a low-disk-space failure partway through a build
   can look like a generic timeout.
3. **Run "Diagnostics"** from the Start Menu (works even on a failed
   install, as long as file copy succeeded) and check `logs-backend.txt` /
   `logs-frontend.txt` / `logs-postgres.txt` etc. in the resulting zip for
   the actual error.
4. **Retry.** The wizard's install step is safe to re-run — it doesn't
   duplicate anything if run twice.

## Backend never reports healthy (installation times out waiting)

- If this is the *very first* install and you're on Ollama with a large
  model, the AI backend itself isn't what's being health-checked (health
  only checks the API is up, not that AI calls succeed) — so this is
  unlikely to be an Ollama issue specifically.
- More likely: Postgres didn't finish its own startup/migration in time.
  Check **Service Status** — if Postgres shows `(healthy)` but backend
  doesn't, give it another minute and check again; `alembic upgrade head`
  (the database migration step) can take longer than expected on a slow
  disk.
- If backend shows a restart loop in **Diagnostics**, the actual Python
  traceback in `logs-backend.txt` will say why.

## I ran the uninstaller unattended/scripted (`/VERYSILENT`) and it seemed to hang

Older packaged versions of this installer could hang indefinitely on the
Remove Application / Remove Everything confirmation prompt during a silent
uninstall, since `/SUPPRESSMSGBOXES` only suppresses Inno Setup's own
built-in message boxes, not this installer's custom one. Current versions
check for silent mode and default to the safe, non-destructive **Remove
Application** (keep all data) path automatically when uninstalling silently
— **Remove Everything** is intentionally an interactive-only choice, since
it's irreversible. If you need the destructive path in an unattended
script, there is deliberately no command-line flag for it.

## I want to reinstall from scratch and start completely clean

Uninstall choosing **Remove Everything** (requires typing `DELETE` to
confirm) — this is the only path that deletes the database and all saved
credentials. **Remove Application** (the default) intentionally keeps
everything so a normal reinstall picks up where you left off; if you
actually want a clean slate, Remove Everything is what you want, not a
regular reinstall.

## Something else isn't covered here

Run **Diagnostics** from the Start Menu — it produces a secrets-redacted zip
on your Desktop with container status, recent logs, and system info. Review
it yourself (it's redacted, but review before sharing regardless) before
sending it anywhere for help.
