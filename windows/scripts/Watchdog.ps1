<#
.SYNOPSIS
    Periodic health watchdog. Runs unattended (a Scheduled Task registers
    this to run every few minutes) and restarts the platform if it's
    genuinely unhealthy -- not just "process exists", but the real
    /health/detailed dependency check (see backend/app/main.py).

.DESCRIPTION
    Confirmed live during a mission-critical-readiness review: Docker's own
    restart:unless-stopped policy (added to every service in
    docker-compose.yml in the same pass this script was added) correctly
    recovers a container that crashes or is OOM-killed, but nothing at all
    previously restarted the platform if the CONTAINERS were all still
    "running" while the application inside them was genuinely broken (e.g.
    the backend process hung without exiting, or a config problem left it
    unable to reach Postgres even though the postgres container itself
    reports healthy). This script is the backstop for that gap.

    Deliberately conservative: only acts when Test-BackendHealth (which
    hits /health/detailed, a real dependency check) fails, and only
    attempts a restart, never a destructive action. Every run appends one
    line to the watchdog log regardless of outcome, so "was the watchdog
    even running" is always answerable from LogsDir, not just "did it fire
    an incident".
#>
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")

$watchdogLogPath = Join-Path $script:LogsDir "watchdog.log"

function Write-WatchdogLog {
    param([string]$Message)
    if (-not (Test-Path $script:LogsDir)) { New-Item -ItemType Directory -Path $script:LogsDir -Force | Out-Null }
    $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $Message
    Add-Content -Path $watchdogLogPath -Value $line -Encoding utf8
}

if (-not (Test-Path $script:EnvFilePath)) {
    # Not configured yet -- nothing to watch. Exit quietly; this is a
    # completely normal state right after install, before Configuration
    # has ever been run, not a failure worth logging every few minutes.
    exit 0
}

Assert-Elevated

if (Test-BackendHealth) {
    # Healthy -- no log line on the happy path, so watchdog.log only grows
    # when there is something worth an operator's attention (an incident,
    # or the restart attempt that followed one).
    exit 0
}

Write-WatchdogLog "Backend failed health check (/health/detailed). Attempting recovery restart."
$exitCode = Invoke-DockerCompose "restart"
if ($exitCode -ne 0) {
    Write-WatchdogLog "docker compose restart exited with code $exitCode."
}

Start-Sleep -Seconds 20
if (Test-BackendHealth) {
    Write-WatchdogLog "Recovery restart succeeded -- backend healthy again."
} else {
    Write-WatchdogLog "Recovery restart did NOT resolve the issue -- backend still unhealthy. Manual attention needed; see 'Service Status' for detail."
}
