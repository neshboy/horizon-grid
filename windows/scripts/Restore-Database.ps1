<#
.SYNOPSIS
    Restores a pg_dump snapshot (taken by Backup-Database.ps1) into the
    platform's Postgres database, replacing its current contents.

.DESCRIPTION
    Real gap fixed: no restore script existed anywhere -- only backup
    scripts -- and the one documented manual restore procedure
    (docs/WINDOWS_ADMINISTRATION.md) was self-contradictory: it said to
    "stop the platform, then restore into the running Postgres container,"
    but stopping the platform (docker compose stop, or the "Stop Platform"
    shortcut) stops Postgres too, so there is no running container left to
    restore into by the time you get to that step.

    This script gets the ordering right: it stops only the services that
    WRITE to the database (backend, celery_worker, celery_beat) so no
    concurrent write can race the restore, leaves Postgres running (a
    restore needs a live server to connect to), drops and recreates the
    target database (a plain pg_dump with no --clean/--if-exists, which is
    what Backup-Database.ps1 produces, cannot be replayed on top of
    already-existing data without primary-key/relation-already-exists
    errors), replays the dump, then restarts what it stopped.

    Destructive by design -- this REPLACES the current database with
    whatever the backup file contains. Everything written since that
    backup was taken is permanently lost. Requires an explicit
    confirmation unless -Force is passed.
#>
param(
    [string]$BackupFile,
    [switch]$Force
)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")
Assert-Elevated

if (-not (Test-Path $script:EnvFilePath)) {
    Write-Host "No configuration found -- nothing to restore into. Run setup first." -ForegroundColor Yellow
    exit 1
}

if (-not $BackupFile) {
    $latest = Get-ChildItem $script:BackupsDir -Filter "postgres-*.sql" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Host "No backup file specified and none found in $script:BackupsDir." -ForegroundColor Red
        Write-Host "Usage: Restore-Database.ps1 -BackupFile <path\to\postgres-YYYYMMDD-HHMMSS.sql> [-Force]"
        exit 1
    }
    $BackupFile = $latest.FullName
    Write-Host "No -BackupFile given -- using the most recent backup: $BackupFile" -ForegroundColor Cyan
}
if (-not (Test-Path $BackupFile)) {
    Write-Host "Backup file not found: $BackupFile" -ForegroundColor Red
    exit 1
}

$containerName = "app-postgres-1"
$running = & docker.exe ps --filter "name=$containerName" --format "{{.Names}}" 2>$null
if (-not $running) {
    Write-Host "Postgres container is not running -- starting it first..." -ForegroundColor Cyan
    $exitCode = Invoke-DockerCompose "up" "-d" "postgres"
    if ($exitCode -ne 0) {
        Write-Host "Could not start the Postgres container -- aborting restore." -ForegroundColor Red
        exit 1
    }
    for ($i = 0; $i -lt 20; $i++) {
        $running = & docker.exe ps --filter "name=$containerName" --format "{{.Names}}" 2>$null
        if ($running) { break }
        Start-Sleep -Seconds 2
    }
    if (-not $running) {
        Write-Host "Postgres container did not come up -- aborting restore." -ForegroundColor Red
        exit 1
    }
}

$pgUser = "ioc"
$pgDb = "ioc_intel"
Get-Content $script:EnvFilePath | ForEach-Object {
    if ($_ -match '^\s*POSTGRES_USER\s*=\s*(.+)$') { $pgUser = $Matches[1].Trim() }
    if ($_ -match '^\s*POSTGRES_DB\s*=\s*(.+)$') { $pgDb = $Matches[1].Trim() }
}

if (-not $Force) {
    Write-Host ""
    Write-Host "WARNING: this will REPLACE the current '$pgDb' database with the contents of:" -ForegroundColor Yellow
    Write-Host "  $BackupFile" -ForegroundColor Yellow
    Write-Host "Every case, investigation, watchlist, and note added since that backup was taken will be PERMANENTLY LOST." -ForegroundColor Yellow
    $confirm = Read-Host "Type RESTORE (in capitals) to continue, or anything else to cancel"
    if ($confirm -ne "RESTORE") {
        Write-Host "Cancelled -- no changes made." -ForegroundColor Cyan
        exit 0
    }
}

Write-SetupLog "Restoring database from $BackupFile"

Write-Host "Stopping services that write to the database (backend, celery_worker, celery_beat)..." -ForegroundColor Cyan
Invoke-DockerCompose "stop" "backend" "celery_worker" "celery_beat" | Out-Null

Write-Host "Terminating any other connections to '$pgDb'..." -ForegroundColor Cyan
& docker.exe exec $containerName psql -U $pgUser -d postgres -c `
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$pgDb' AND pid <> pg_backend_pid();" 2>$null | Out-Null

Write-Host "Dropping and recreating '$pgDb'..." -ForegroundColor Cyan
& docker.exe exec $containerName psql -U $pgUser -d postgres -c "DROP DATABASE IF EXISTS $pgDb;" 2>$null | Out-Null
& docker.exe exec $containerName psql -U $pgUser -d postgres -c "CREATE DATABASE $pgDb OWNER $pgUser;" 2>$null | Out-Null

Write-Host "Restoring $BackupFile ..." -ForegroundColor Cyan
$restoreOutput = Get-Content $BackupFile -Raw | & docker.exe exec -i $containerName psql -U $pgUser -d $pgDb 2>&1
$restoreExitCode = $LASTEXITCODE

if ($restoreExitCode -ne 0) {
    Write-SetupLog "Database restore FAILED (exit code $restoreExitCode) from $BackupFile -- psql output: $($restoreOutput -join ' | ')" "ERROR"
    Write-Host "Restore failed (exit code $restoreExitCode):" -ForegroundColor Red
    $restoreOutput | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "The database may be in a partial state -- see $script:SetupLogPath and consider restoring again." -ForegroundColor Red
    Write-Host "Restarting backend/celery anyway so the platform isn't left fully down..." -ForegroundColor Yellow
    Invoke-DockerCompose "start" "backend" "celery_worker" "celery_beat" | Out-Null
    exit 1
}

Write-Host "Restore complete. Restarting backend and celery..." -ForegroundColor Cyan
Invoke-DockerCompose "start" "backend" "celery_worker" "celery_beat" | Out-Null

Write-Host "Waiting for the backend to become healthy..." -ForegroundColor Cyan
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    if (Test-BackendHealth) { $healthy = $true; break }
    Start-Sleep -Seconds 3
}

Write-SetupLog "Database restore from $BackupFile completed successfully."
if ($healthy) {
    Write-Host "Restore complete and the backend is healthy." -ForegroundColor Green
} else {
    Write-Host "Restore complete, but the backend did not report healthy within 90s -- check 'horizon-grid status' / Start Menu -> Diagnostics." -ForegroundColor Yellow
}
Pause
