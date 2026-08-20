<#
.SYNOPSIS
    Shared constants and helper functions used by every Windows packaging
    script (setup wizard, service control, diagnostics, uninstall). Dot-
    sourced, not run directly.

.DESCRIPTION
    Defines the real on-disk layout this installer uses:

        C:\Program Files\IOC Intelligence Platform\app\   -- the actual repo
            (backend/, frontend/, docker-compose.yml, etc.) copied in by the
            Inno Setup installer. Read-mostly; docker compose builds images
            from here.

        C:\ProgramData\IOC Intelligence Platform\
            config\.env       -- the real environment file docker-compose.yml
                                  reads (env_file: .env, plus the ${VAR}
                                  substitutions docker-compose.yml itself
                                  uses for ports/DB credentials).
            logs\setup.log    -- wizard/installer log (human-readable).
            backups\          -- pg_dump snapshots taken before an upgrade.

    This mirrors the installer master prompt's own required split (binaries
    under Program Files, writable data under ProgramData) and matches how
    every other well-behaved Windows application separates the two.
#>

# HORIZON GRID rebrand (visible strings only): $script:AppDisplayName is
# DISPLAY TEXT ONLY (firewall rule name, and any script that wants a label
# for a window title/message) -- it must NOT be used to derive any path
# below. $script:AppFolderName is the literal on-disk folder name and is
# pinned to the original string: the one real existing install already has
# its Program Files/ProgramData folders under that exact name, and every
# script here (Invoke-DockerCompose, Assert-Elevated's callers, etc.) relies
# on $script:InstallDir/$script:DataDir resolving to those exact folders.
# Changing AppDisplayName's VALUE is safe; changing which variable feeds
# InstallDir/DataDir is not.
$script:AppDisplayName = "HORIZON GRID"
$script:AppFolderName = "IOC Intelligence Platform"

# Resolved once, here, so every script that dot-sources Common.ps1 agrees on
# the same paths regardless of where it's invoked from.
$script:InstallDir = if ($env:IOC_INSTALL_DIR) { $env:IOC_INSTALL_DIR } else { Join-Path ${env:ProgramFiles} $script:AppFolderName }
$script:AppRepoDir = Join-Path $script:InstallDir "app"
$script:DataDir = Join-Path $env:ProgramData $script:AppFolderName
$script:ConfigDir = Join-Path $script:DataDir "config"
$script:LogsDir = Join-Path $script:DataDir "logs"
$script:BackupsDir = Join-Path $script:DataDir "backups"
$script:EnvFilePath = Join-Path $script:ConfigDir ".env"
$script:SetupLogPath = Join-Path $script:LogsDir "setup.log"
$script:SetupCompleteMarker = Join-Path $script:ConfigDir ".setup-complete"

function Assert-Elevated {
    <# Re-launches the CURRENT script elevated and exits, if not already
       running with a real elevated token.

       Being a member of the Administrators group is not enough on its own:
       Windows UAC gives a split-token admin account a FILTERED token for
       any normally-launched process (this includes every process Explorer
       starts from a Start Menu shortcut, and -- confirmed live -- even a
       [Run] postinstall step launched by an already-elevated Inno Setup
       installer). That filtered token carries the Administrators SID as
       deny-only, so it cannot pass the icacls grant Initialize-
       DataDirectories applies to ProgramData\...\config\.env. Every script
       that reads or writes that file needs to call this first. #>
    $isElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if ($isElevated) { return }

    $scriptPath = $MyInvocation.PSCommandPath
    if (-not $scriptPath) {
        # Called from a script that doesn't set $MyInvocation.PSCommandPath
        # (e.g. dot-sourced oddly) -- nothing safe to relaunch, so just warn
        # and let the caller's own subsequent ACL-restricted operations fail
        # with a clear underlying error instead of silently doing nothing.
        Write-Warning "Not running elevated, and could not determine the calling script path to relaunch. Re-run this as Administrator."
        return
    }

    try {
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$scriptPath`"") `
            -Verb RunAs | Out-Null
    } catch {
        Write-Warning "Administrator privileges are required and the elevation prompt was declined or failed. Re-run this as Administrator."
    }
    exit 0
}

function Initialize-DataDirectories {
    <# Creates the ProgramData tree and locks it down to Administrators +
       SYSTEM only -- the .env file it will contain has real API keys and a
       JWT signing secret in it. #>
    foreach ($dir in @($script:DataDir, $script:ConfigDir, $script:LogsDir, $script:BackupsDir)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    # Restrict ProgramData\IOC Intelligence Platform to Administrators and
    # SYSTEM -- icacls, not Set-Acl, because it's the most reliable way to
    # do a recursive, inheritance-resetting grant from a script (Set-Acl's
    # object model requires more code for the same effect and is easier to
    # get subtly wrong around inheritance flags).
    $null = & icacls.exe $script:DataDir /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" 2>&1
}

function Write-SetupLog {
    param([string]$Message, [string]$Level = "INFO")
    if (-not (Test-Path (Split-Path $script:SetupLogPath))) {
        New-Item -ItemType Directory -Path (Split-Path $script:SetupLogPath) -Force | Out-Null
    }
    $line = "[{0:yyyy-MM-dd HH:mm:ss}] [{1}] {2}" -f (Get-Date), $Level, $Message
    Add-Content -Path $script:SetupLogPath -Value $line -Encoding utf8
}

function New-RandomSecret {
    <# Cryptographically random secret for JWT_SECRET_KEY / generated DB
       passwords -- RNGCryptoServiceProvider-backed via .NET, not
       Get-Random (which is not a CSPRNG). #>
    param([int]$Bytes = 48)
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer) -replace '[+/=]', '' # URL/shell-safe
}

function Test-PortFree {
    param([int]$Port)
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -eq $listener -or $listener.Count -eq 0)
}

function Find-FreePort {
    <# Returns $PreferredPort if free, else the next free port upward, capped
       after 50 attempts so a pathological environment can't hang the wizard. #>
    param([int]$PreferredPort, [int]$MaxAttempts = 50)
    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        $candidate = $PreferredPort + $i
        if (Test-PortFree -Port $candidate) { return $candidate }
    }
    throw "Could not find a free port near $PreferredPort after $MaxAttempts attempts."
}

function ConvertTo-DpapiProtectedFile {
    <# Encrypts $PlainTextPath in place to $PlainTextPath + ".dpapi" using
       Windows DPAPI (CurrentUser scope would be wrong here since the backend
       runs as SYSTEM under NSSM -- LocalMachine scope, so any admin-context
       process on this machine can unprotect it, which is the correct
       tradeoff: docker compose itself has to read the plaintext .env at
       container-start time, so DPAPI protects the file at rest on disk
       between installs/reboots, not from the running Docker daemon that
       legitimately needs the real values). #>
    param([string]$PlainTextPath)
    Add-Type -AssemblyName System.Security
    $bytes = [System.IO.File]::ReadAllBytes($PlainTextPath)
    $protected = [System.Security.Cryptography.ProtectedData]::Protect(
        $bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    [System.IO.File]::WriteAllBytes("$PlainTextPath.dpapi", $protected)
}

function ConvertFrom-DpapiProtectedFile {
    param([string]$ProtectedPath, [string]$OutputPath)
    Add-Type -AssemblyName System.Security
    $bytes = [System.IO.File]::ReadAllBytes($ProtectedPath)
    $plain = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    [System.IO.File]::WriteAllBytes($OutputPath, $plain)
}

function Invoke-DockerCompose {
    <# Runs `docker compose` with the correct working directory and the
       correct env file every time, so no caller can accidentally run it
       against the wrong .env or the wrong compose project.

       docker.exe's own build/status output goes to the console via
       Out-Host rather than the function's own output stream -- if it were
       left on the pipeline it would merge with the `return $LASTEXITCODE`
       below, turning the caller's `$exitCode = Invoke-DockerCompose ...`
       into an array of [...build log lines..., exit code]. Comparing that
       array with -ne 0 is truthy for ANY output at all, which reports
       failure even when docker compose actually succeeded (confirmed live:
       an 8/8-container successful `up -d --build` was reported as an error
       by the caller before this fix). #>
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    Sync-ComposeEnvFile
    Push-Location $script:AppRepoDir
    try {
        # docker-compose.prod.yml strips the dev-only source bind-mounts that
        # break under an installed, Program-Files-rooted copy -- see its own
        # header comment for the concrete failures this avoids.
        #
        # docker compose writes its normal progress ("Container ... Starting/
        # Started") to stderr by convention, not because anything failed.
        # PowerShell wraps every redirected native-command stderr line in an
        # ErrorRecord, and piping those straight to Out-Host renders each one
        # as a red "NativeCommandError" block complete with a fake stack
        # trace -- confirmed live on a totally successful `stop`/`up -d`/
        # `restart` (exit code 0 throughout), which still made routine
        # container-status lines look like crashes. Render each line's text
        # instead of the ErrorRecord object so normal progress reads as
        # normal progress.
        & docker.exe compose -f docker-compose.yml -f docker-compose.prod.yml --env-file $script:EnvFilePath @Args 2>&1 |
            ForEach-Object { Write-Host $_.ToString() }
        return $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

function Remove-StaleDatabaseVolumeIfFreshInstall {
    <# Real bug, confirmed live: Postgres only ever applies POSTGRES_PASSWORD
       to an EMPTY data directory -- once a volume has been initialized once,
       every later container start ignores that env var entirely and keeps
       whatever password the volume already has baked in. New-DefaultPlatformSettings
       generates a brand-new random PostgresPassword on every run that finds
       no existing .env to load real values from (Setup-Wizard.ps1's
       $State.IsUpgrade check) -- if a Postgres volume from an EARLIER,
       abandoned/incomplete install attempt is still sitting on this machine
       (e.g. .env got deleted or never existed for that attempt, but nothing
       ever ran `docker compose down -v` against it) that fresh random
       password will NOT match the old volume's real one, and the backend
       container will crash-loop on a Postgres authentication error the
       instant it starts -- confirmed as the exact real-world failure this
       function exists to prevent.

       Only call this when IsFreshInstall is $true (no existing .env was
       found to recover a real password from) -- an upgrade/reconfigure on a
       genuinely existing install must NEVER reach this function, since that
       path already correctly preserves and reuses the real existing
       password (see Setup-Wizard.ps1's $State.IsUpgrade load block) and any
       volume found in that case is the CORRECT one to keep.

       Looks up the volume by Compose's own project/volume labels rather
       than a hardcoded name string ("app_postgres_data" only holds because
       the compose project happens to be named after the "app" directory
       today -- label lookup stays correct even if that ever changes).
       Without a matching .env, that old volume's data is unreachable
       anyway (nothing knows its real password either), so removing it
       trades an inaccessible, silently-broken volume for a clean, working
       fresh install -- a strictly better outcome, not a data-loss risk,
       since the alternative is a backend that can never start at all. #>
    param([Parameter(Mandatory = $true)][bool]$IsFreshInstall)

    if (-not $IsFreshInstall) { return }

    $staleVolumeId = & docker.exe volume ls -q `
        --filter "label=com.docker.compose.project=app" `
        --filter "label=com.docker.compose.volume=postgres_data"
    if ($staleVolumeId) {
        Write-SetupLog "Fresh install: found a leftover Postgres volume ($staleVolumeId) from an earlier install attempt with no matching .env -- removing it so the new password can initialize cleanly."
        & docker.exe volume rm $staleVolumeId 2>&1 | ForEach-Object { Write-SetupLog "  $_" }
    }
}

function Sync-ComposeEnvFile {
    <# docker-compose.yml declares env_file: .env on the backend and
       celery_worker services. Docker Compose resolves that path relative to
       the COMPOSE PROJECT DIRECTORY ({app}\app), completely independent of
       the top-level --env-file CLI flag -- --env-file only controls ${VAR}
       substitution inside the YAML itself, not env_file: lookups. Confirmed
       live: a fresh install failed 100% of the time with "env file ...\app\
       .env not found", even though --env-file correctly pointed at the real
       ProgramData\...\config\.env, because Compose was never told to look
       there for THIS specific directive -- these are two unrelated
       mechanisms that happen to share a flag name in casual reading of the
       docs.

       The obvious fix -- copy .env into {app}\app -- was rejected after
       checking real ACLs on this machine: `icacls "C:\Program Files"` shows
       BUILTIN\Users:(RX) by default, i.e. every standard account on the
       box can read anything under Program Files unless a subfolder
       overrides that. Copying real API keys/DB passwords/JWT secret there
       would make them world-readable, directly undoing the Administrators-
       only ACL Initialize-DataDirectories applies to the real ProgramData
       copy.

       Real fix: lock down {app}\app\.env with the SAME Administrators+
       SYSTEM-only ACL as the ProgramData original, immediately after
       writing it -- so the file exists where Compose's env_file: .env
       needs it, but isn't newly exposed to other accounts on the machine.
       Whichever token invoked docker compose (always a genuinely elevated
       one, per Assert-Elevated) already has access either way. #>
    if (Test-Path $script:EnvFilePath) {
        $target = Join-Path $script:AppRepoDir ".env"
        Copy-Item -Path $script:EnvFilePath -Destination $target -Force
        $null = & icacls.exe $target /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" 2>&1
    }
}

function Test-BackendHealth {
    <# Hits /health/detailed, not the plain /health -- confirmed live that
       plain /health returns 200 unconditionally even with Postgres fully
       stopped, so it can never tell an operator/watchdog whether the
       backend can actually serve a real request. /health/detailed
       genuinely pings Postgres and Redis and returns 503 if the database
       is unreachable. #>
    param([string]$BaseUrl = "http://localhost:8000")
    try {
        $resp = Invoke-WebRequest -Uri "$BaseUrl/health/detailed" -UseBasicParsing -TimeoutSec 5
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-FrontendHealth {
    param([string]$BaseUrl = "http://localhost:3000")
    try {
        $resp = Invoke-WebRequest -Uri $BaseUrl -UseBasicParsing -TimeoutSec 5
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-LanIpAddress {
    <#
    .SYNOPSIS
        Best-effort detection of this machine's real LAN-facing IPv4
        address, for DISPLAY purposes only -- confirmed live that a
        container can never discover this itself (the UDP-connect
        self-detection trick run inside the backend container returned
        Docker's own bridge address, and host.docker.internal resolved to
        Docker Desktop's internal VM gateway, neither of which is the
        host's real interface). Runs here, on the Windows host, not in the
        backend.
    .PARAMETER AllCandidates
        Returns every qualifying interface's address instead of just the
        single best one, for a future "show detected choices" UI.
    #>
    param([switch]$AllCandidates)

    $excludePattern = 'Docker|Hyper-V|VMware|VirtualBox|Virtual|WSL|Bluetooth|Loopback|TAP|VPN'

    try {
        $candidates = Get-NetIPConfiguration | Where-Object {
            $_.IPv4DefaultGateway -and
            $_.NetAdapter.Status -eq 'Up' -and
            $_.InterfaceDescription -notmatch $excludePattern
        } | ForEach-Object { $_.IPv4Address.IPAddress } | Where-Object {
            # Defense in depth even though the gateway/adapter filters above
            # should already exclude virtual adapters.
            $_ -match '^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)'
        }
    } catch {
        Write-SetupLog "Get-LanIpAddress failed: $_" "WARN"
        return $null
    }

    if ($AllCandidates) { return $candidates }
    return $candidates | Select-Object -First 1
}

function New-AppFirewallRule {
    <#
    .SYNOPSIS
        Opens inbound TCP access to the platform's web/API ports, scoped to
        Private networks only (never Domain/Public) -- LAN access is meant
        for a trusted home/office network, not the public internet. Removes
        any existing rule first so a port change on reconfigure doesn't
        leave a stale duplicate rule behind with the old ports baked in.
    #>
    param([Parameter(Mandatory)][int]$FrontendPort, [Parameter(Mandatory)][int]$BackendPort)
    Remove-AppFirewallRule
    New-NetFirewallRule -DisplayName $script:AppDisplayName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort @($FrontendPort, $BackendPort) -Profile Private | Out-Null
    Write-SetupLog "Created firewall rule '$script:AppDisplayName' for ports $FrontendPort,$BackendPort (Private profile only)."
}

function Remove-AppFirewallRule {
    Get-NetFirewallRule -DisplayName $script:AppDisplayName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

$script:StartupTaskName = "$($script:AppDisplayName) Startup"
$script:WatchdogTaskName = "$($script:AppDisplayName) Watchdog"
$script:BackupTaskName = "$($script:AppDisplayName) Daily Backup"

function Register-BootAndWatchdogTasks {
    <#
    .SYNOPSIS
        Real mission-critical gap this closes: before this existed, NOTHING
        on Windows restarted the platform after a host reboot -- only a
        human clicking the "Start Platform" Start Menu shortcut. For a
        remote, physically-inaccessible site, a power-loss-induced reboot
        left the platform down indefinitely. Three Scheduled Tasks, all
        running as SYSTEM (so they work with nobody ever logged on):
        one fires once at boot (Service-Start.ps1, idempotent if already
        running), one fires every 5 minutes indefinitely (Watchdog.ps1, a
        no-op unless the backend is genuinely unhealthy), and one fires
        once a day (Backup-Database.ps1 -Quiet, a no-op if not yet
        configured or not running -- see that script's own early-exit
        checks). Before this, the ONLY backup mechanism was the manual
        "Backup Now" Start Menu shortcut and the wizard's own pre-upgrade
        call -- a remote, unattended site with nobody ever clicking that
        button had literally zero backups of its own investigation data.
        Re-registering (calling this again, e.g. on a reconfigure) replaces
        any existing task of the same name rather than erroring or
        duplicating it.
    #>
    param([Parameter(Mandatory)][string]$ScriptsDir)

    $action1 = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptsDir\Service-Start.ps1`""
    $trigger1 = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

    Unregister-ScheduledTask -TaskName $script:StartupTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $script:StartupTaskName -Action $action1 -Trigger $trigger1 `
        -Principal $principal -Settings $settings -Force | Out-Null

    $action2 = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptsDir\Watchdog.ps1`""
    $trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)

    Unregister-ScheduledTask -TaskName $script:WatchdogTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $script:WatchdogTaskName -Action $action2 -Trigger $trigger2 `
        -Principal $principal -Settings $settings -Force | Out-Null

    $action3 = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptsDir\Backup-Database.ps1`" -Quiet"
    # 02:00 local time -- outside normal investigation hours for most
    # deployments, and well clear of the 5-minute watchdog's own activity.
    $trigger3 = New-ScheduledTaskTrigger -Daily -At "02:00"

    Unregister-ScheduledTask -TaskName $script:BackupTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $script:BackupTaskName -Action $action3 -Trigger $trigger3 `
        -Principal $principal -Settings $settings -Force | Out-Null

    Write-SetupLog "Registered Scheduled Tasks '$script:StartupTaskName' (at boot), '$script:WatchdogTaskName' (every 5 min), and '$script:BackupTaskName' (daily at 02:00)."
}

function Remove-BootAndWatchdogTasks {
    Unregister-ScheduledTask -TaskName $script:StartupTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $script:WatchdogTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $script:BackupTaskName -Confirm:$false -ErrorAction SilentlyContinue
}
