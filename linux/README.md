# HORIZON GRID -- Linux packaging

This directory is the Linux counterpart to `windows/`: it packages the same
Docker Compose application (`backend/`, `frontend/`, `docker-compose.yml`,
`docker-compose.prod.yml`) for Debian/Ubuntu, the same way `windows/`
packages it for Windows via Inno Setup. **It does not modify anything under
`backend/`, `frontend/`, `docker-compose*.yml`, or `windows/`** -- the
Windows installer is unaffected by anything in this directory.

## Layout

| Path | Role | Windows equivalent |
|---|---|---|
| `linux/debian/` | `.deb` control files (`control`, `postinst`, `prerm`, `postrm`) | `windows/installer.iss` |
| `linux/scripts/*.sh` | Service lifecycle, backup, diagnostics, prerequisite check | `windows/scripts/*.ps1` |
| `linux/wizard/setup_wizard.py` | CLI setup wizard (admin account, AI backend, providers, ports) | `windows/wizard/Setup-Wizard.ps1` |
| `linux/systemd/horizon-grid.service` | systemd unit wrapping `docker compose` | Start Menu "Start/Stop/Restart Platform" shortcuts |
| `linux/bin/horizon-grid` | Single CLI entrypoint (`horizon-grid start\|stop\|status\|configure\|...`) | Start Menu shortcut group |
| `linux/horizon-grid.desktop` | Desktop menu launcher | Desktop/Start Menu "Open Platform" icon |
| `linux/build-deb.sh` | Assembles and builds the `.deb` | `ISCC.exe installer.iss` |

## Installed paths (FHS, not Program Files/ProgramData)

| Purpose | Linux path | Windows equivalent |
|---|---|---|
| Application (read-mostly) | `/opt/horizon-grid/app/` | `C:\Program Files\IOC Intelligence Platform\app\` |
| Configuration (`.env`, real secrets) | `/etc/horizon-grid/.env` (root:root, 0600) | `C:\ProgramData\IOC Intelligence Platform\config\.env` |
| Backups | `/var/lib/horizon-grid/backups/` | `...\ProgramData\...\backups\` |
| Logs | `/var/log/horizon-grid/setup.log` | `...\ProgramData\...\logs\setup.log` |
| CLI entrypoint | `/usr/bin/horizon-grid` | Start Menu shortcuts |

Both platforms' compose project directory has the same basename (`app`), so
both produce the identical Docker Compose project label
(`com.docker.compose.project=app`) -- this is by design, not a coincidence,
and is what lets the uninstall/purge logic identify containers and volumes
by label rather than needing a hardcoded container-name guess.

## Building the `.deb`

`dpkg-deb` is a Debian-family tool with no Windows equivalent, so this
**must** run on a real Debian/Ubuntu machine or container -- there is no way
to build it from the Windows dev checkout directly, exactly as `ISCC.exe`
can only build the Windows installer on Windows. From a checkout of this
repository:

```bash
docker run --rm -v "$PWD":/src -w /src debian:12 bash linux/build-deb.sh
```

This produces `release/horizon-grid_<version>_amd64.deb`. The build script
does **not** vendor `node_modules`/pip dependencies or pre-built Docker
images into the package -- those install the same way on every platform,
inside the containers, the first time `docker compose up --build` runs
(matching the ~69 MB Windows installer, which doesn't contain Docker images
either -- only source, the wizard, and the packaging scripts).

## Installing

```bash
sudo apt install ./horizon-grid_<version>_amd64.deb
sudo horizon-grid configure   # admin account, AI backend, providers, ports
```

`apt install ./file.deb` resolves the package's declared dependencies
(`python3`, `curl`, `ca-certificates`) from your normal repositories. Docker
Engine itself is a `Recommends:`, not a hard `Depends:` -- the exact package
name that provides the Compose v2 plugin differs across Ubuntu 24.04/22.04
and Debian 12 (see `linux/scripts/check-prerequisites.sh`'s own detection
logic), so this package checks for a working `docker compose` at configure
time with a clear message, the same way the Windows installer's prerequisite
check does for Docker Desktop, rather than guessing a single package name
that might not resolve on every target and breaking `apt install` outright.

## Removing

```bash
sudo apt remove horizon-grid    # keeps /etc/horizon-grid, /var/lib/horizon-grid, and all Docker volumes
sudo apt purge horizon-grid     # deletes everything, including all case/investigation data -- no undo
```

This maps directly onto Debian's own remove-vs-purge distinction instead of
a custom confirmation dialog (Windows's uninstaller has to build one by hand,
since Inno Setup has no equivalent built-in verb pair) -- seeAdd
`linux/debian/prerm`/`postrm` for exactly what each does.

## Testing

See `HORIZON_GRID_LINUX_QA_REPORT.pdf` (in `documentation/`) for the real,
executed test results across Ubuntu 24.04, Ubuntu 22.04, and Debian 12, and
that report's own "Test Environment" section for the honest disclosure of
how those tests were actually run (real Linux containers via Docker, not a
bare-metal machine, and no real desktop-GUI/AppImage double-click
verification was possible from this build environment).
