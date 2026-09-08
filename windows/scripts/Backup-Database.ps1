<#
.SYNOPSIS
    Takes a pg_dump snapshot of the platform's Postgres database into
    $script:BackupsDir. Called automatically by the setup wizard before an
    upgrade re-runs docker compose up --build against an existing install,
    and can be run manually from the Start Menu ("Backup Now").

.DESCRIPTION
    Runs pg_dump INSIDE the running postgres container (docker exec) rather
    than requiring a local psql/pg_dump install on the Windows host --
    that's the only Postgres client guaranteed to exist and match the
    server's version, since it ships in the same official postgres image
    docker-compose.yml already pulls.
#>
param(
    [switch]$Quiet
)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")
Assert-Elevated

function Write-Status($msg, $color = "Cyan") {
    if (-not $Quiet) { Write-Host $msg -ForegroundColor $color }
}

if (-not (Test-Path $script:EnvFilePath)) {
    Write-Status "No configuration found -- nothing to back up." "Yellow"
    exit 0
}

$containerName = "app-postgres-1"
$running = & docker.exe ps --filter "name=$containerName" --format "{{.Names}}" 2>$null
if (-not $running) {
    Write-Status "Postgres container is not running -- skipping backup (nothing to snapshot)." "Yellow"
    exit 0
}

Initialize-DataDirectories
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dumpPath = Join-Path $script:BackupsDir "postgres-$stamp.sql"

# POSTGRES_USER/POSTGRES_DB defaults match docker-compose.yml's own
# ${VAR:-default} fallbacks -- read the real values out of .env so a
# customized install still gets dumped correctly.
$pgUser = "ioc"
$pgDb = "ioc_intel"
Get-Content $script:EnvFilePath | ForEach-Object {
    if ($_ -match '^\s*POSTGRES_USER\s*=\s*(.+)$') { $pgUser = $Matches[1].Trim() }
    if ($_ -match '^\s*POSTGRES_DB\s*=\s*(.+)$') { $pgDb = $Matches[1].Trim() }
}

Write-Status "Backing up database to $dumpPath ..."
& docker.exe exec $containerName pg_dump -U $pgUser $pgDb 2>$null | Out-File -FilePath $dumpPath -Encoding utf8
# Real gap found live during overnight QA: pg_dump's own exit code was
# never checked -- only "does a non-empty file exist" was, which a dump
# that failed PARTWAY through (lost connection, a permission error on one
# table) can still satisfy, producing a truncated/corrupt-but-non-empty
# file silently reported as "Backup complete." $LASTEXITCODE still
# reflects docker.exe's (and pg_dump's, which docker exec forwards) real
# exit status even after piping through Out-File -- checked once, from a
# single pg_dump invocation (not run twice just to inspect its exit code).
$pgDumpFailed = $LASTEXITCODE -ne 0

if ((-not $pgDumpFailed) -and (Test-Path $dumpPath) -and (Get-Item $dumpPath).Length -gt 0) {
    Write-SetupLog "Database backup written to $dumpPath"
    Write-Status "Backup complete: $dumpPath" "Green"

    # Keep the 10 most recent backups; older ones are pruned so BackupsDir
    # doesn't grow unbounded across repeated upgrades.
    Get-ChildItem $script:BackupsDir -Filter "postgres-*.sql" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 10 |
        Remove-Item -Force -ErrorAction SilentlyContinue
} else {
    Write-SetupLog "Database backup failed or produced an empty file: $dumpPath" "ERROR"
    Write-Status "Backup failed -- see $script:SetupLogPath for details." "Red"
    Remove-Item $dumpPath -Force -ErrorAction SilentlyContinue
    exit 1
}

if (-not $Quiet) { Pause }
