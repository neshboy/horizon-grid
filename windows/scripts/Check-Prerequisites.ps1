<#
.SYNOPSIS
    Verifies the host machine can actually run the IOC Intelligence Platform
    before the installer proceeds. Called by the Inno Setup installer (as a
    [Code] Exec step) and independently runnable by an administrator for
    diagnostics.

.DESCRIPTION
    The platform's real runtime is Docker Compose (Postgres, Redis, Neo4j,
    OpenSearch, backend, frontend, celery_worker, celery_beat -- see
    docker-compose.yml at the repo root). This script checks every real
    precondition for that to work: 64-bit Windows 10/11, Docker Desktop
    installed AND running (checked via `docker info`, not process/service
    name -- WSL2-backed Docker Desktop does not always run the legacy
    com.docker.service), the required TCP ports free, sufficient disk space,
    and administrator privileges (needed to write to Program Files/
    ProgramData and manage the Windows service wrapper).

    Exit code 0 = all checks passed. Exit code 1 = one or more hard failures.
    Emits one JSON object to stdout (and nothing else) so the calling Inno
    Setup [Code] step or the PowerShell wizard can parse results
    programmatically; human-readable detail goes to stderr.
#>

[CmdletBinding()]
param(
    # Ports the platform's docker-compose.yml actually publishes to the host:
    # postgres(5433), redis(6379), neo4j(7475,7688), opensearch(9200),
    # backend(8000), frontend(3000). See docker-compose.yml at the repo root.
    [int[]]$RequiredPorts = @(3000, 8000, 5433, 6379, 7475, 7688, 9200),
    [int64]$MinFreeDiskBytes = 8GB
)

$ErrorActionPreference = "Stop"
$results = [ordered]@{
    ok = $true
    checks = @()
}

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail, [bool]$Hard = $true)
    $script:results.checks += [ordered]@{ name = $Name; passed = $Passed; detail = $Detail; hard = $Hard }
    if ($Hard -and -not $Passed) { $script:results.ok = $false }
}

# --- OS version / architecture ---
$os = Get-CimInstance Win32_OperatingSystem
$is64 = [Environment]::Is64BitOperatingSystem
$buildNumber = [int]$os.BuildNumber
# Windows 10 = build >= 10240; Windows 11 = build >= 22000. Both are fine --
# the platform has no Windows-11-specific requirement, just "64-bit Win10+".
Add-Check -Name "64-bit Windows 10 or later" -Passed ($is64 -and $buildNumber -ge 10240) `
    -Detail "OS build $buildNumber, 64-bit: $is64"

# --- Administrator privileges ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
Add-Check -Name "Running as Administrator" -Passed $isAdmin `
    -Detail $(if ($isAdmin) { "Elevated" } else { "Not elevated -- re-run the installer as Administrator." })

# --- RAM (Docker Desktop + Postgres + Redis + Neo4j + OpenSearch + backend +
# frontend genuinely need headroom; 8GB total system RAM is a practical floor,
# not a hard platform requirement, but below it the stack becomes unusable) ---
$totalRamGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
Add-Check -Name "At least 8 GB RAM" -Passed ($totalRamGb -ge 7.5) -Hard $false `
    -Detail "$totalRamGb GB detected -- the full Docker Compose stack (8 containers: postgres, redis, neo4j, opensearch, backend, frontend, celery_worker, celery_beat) is heavy on less."

# --- Disk space on the drive the installer will target (checked again with
# the real chosen path once the installer knows it; this is a pre-flight
# estimate against the system drive) ---
$systemDrive = (Get-Item $env:SystemDrive).PSDrive
$freeBytes = (Get-PSDrive -Name $systemDrive.Name).Free
Add-Check -Name "Sufficient free disk space" -Passed ($freeBytes -ge $MinFreeDiskBytes) `
    -Detail "$([math]::Round($freeBytes / 1GB, 1)) GB free on $($systemDrive.Name): (need at least $([math]::Round($MinFreeDiskBytes / 1GB, 1)) GB for Docker images + data)"

# --- Docker Desktop installed ---
$dockerCmd = Get-Command docker.exe -ErrorAction SilentlyContinue
Add-Check -Name "Docker Desktop installed" -Passed ($null -ne $dockerCmd) `
    -Detail $(if ($dockerCmd) { $dockerCmd.Source } else { "docker.exe not found on PATH -- install Docker Desktop from https://www.docker.com/products/docker-desktop/" })

# --- Docker daemon actually reachable (the real signal -- not service/process
# name, since WSL2-backed Docker Desktop doesn't always run the legacy
# com.docker.service Windows service) ---
$dockerRunning = $false
$dockerVersionDetail = "Docker Desktop is installed but not running, or its daemon isn't ready yet."
if ($dockerCmd) {
    try {
        $verJson = & docker.exe info --format '{{json .ServerVersion}}' 2>$null
        if ($LASTEXITCODE -eq 0 -and $verJson) {
            $dockerRunning = $true
            $dockerVersionDetail = "Docker engine $($verJson.Trim('"')) is running."
        }
    } catch {
        # docker.exe present but daemon unreachable -- dockerRunning stays false.
    }
}
Add-Check -Name "Docker Desktop is running" -Passed $dockerRunning -Detail $dockerVersionDetail

# --- Docker Compose v2 available (docker-compose.yml at the repo root uses
# the `docker compose` plugin syntax, not the standalone docker-compose.exe) ---
$composeOk = $false
$composeDetail = "docker compose (v2 plugin) not available."
if ($dockerRunning) {
    try {
        $composeVer = & docker.exe compose version --short 2>$null
        if ($LASTEXITCODE -eq 0 -and $composeVer) {
            $composeOk = $true
            $composeDetail = "docker compose v$($composeVer.Trim())"
        }
    } catch {}
}
Add-Check -Name "Docker Compose v2 available" -Passed $composeOk -Detail $composeDetail

# --- Required ports free ---
foreach ($port in $RequiredPorts) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    $free = ($null -eq $listener -or $listener.Count -eq 0)
    $owner = ""
    if (-not $free) {
        $pid0 = ($listener | Select-Object -First 1).OwningProcess
        $proc = Get-Process -Id $pid0 -ErrorAction SilentlyContinue
        $owner = if ($proc) { " (in use by $($proc.ProcessName), PID $pid0)" } else { " (in use by PID $pid0)" }
    }
    # Not a hard failure: the setup wizard's port-conflict page lets the
    # administrator remap it (see Configure-Setup.ps1's port-selection step).
    Add-Check -Name "Port $port available" -Passed $free -Hard $false `
        -Detail $(if ($free) { "Free" } else { "In use$owner -- the setup wizard will offer an alternate port." })
}

# --- Existing installation detection (for upgrade vs. fresh-install framing;
# not a pass/fail check, just informational) ---
$dataDir = Join-Path $env:ProgramData "IOC Intelligence Platform"
# Real gap found live during overnight QA: $ErrorActionPreference = "Stop"
# is set globally at the top of this script -- Test-Path against a folder
# whose ACL denies this process even STAT access (a leftover, permissions-
# hardened folder from a previous install attempt, or a locked-down
# enterprise environment) can throw rather than just returning $false, and
# with Stop in effect that terminates the ENTIRE script before it ever
# reaches the final ConvertTo-Json line -- breaking this script's own
# documented contract of "emits one JSON object to stdout, always" that the
# calling Inno Setup step / wizard depends on to parse results at all.
$existingInstall = $false
try {
    $existingInstall = Test-Path (Join-Path $dataDir "config\.env")
} catch {
    Write-Warning "Could not check for an existing installation at $dataDir (access denied?): $_"
}
Add-Check -Name "Existing installation detected" -Passed $true -Hard $false `
    -Detail $(if ($existingInstall) { "Found existing configuration at $dataDir -- this will be an upgrade." } else { "No existing installation found -- this will be a fresh install." })

$results | ConvertTo-Json -Depth 5 -Compress
if (-not $results.ok) { exit 1 } else { exit 0 }
