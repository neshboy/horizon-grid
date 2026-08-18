<#
.SYNOPSIS
    Restarts the IOC Intelligence Platform. Wired to the "Restart Platform"
    Start Menu shortcut -- the usual first step for troubleshooting.
#>
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")
Assert-Elevated

if (-not (Test-Path $script:EnvFilePath)) {
    Write-Host "No configuration found. Run 'Configuration' from the Start Menu first." -ForegroundColor Yellow
    exit 1
}

Write-Host "Restarting HORIZON GRID..." -ForegroundColor Cyan
$exitCode = Invoke-DockerCompose "restart"
if ($exitCode -ne 0) {
    Write-Host "Failed to restart (exit code $exitCode). See $script:LogsDir for details." -ForegroundColor Red
    exit $exitCode
}

Write-Host "Waiting for the backend to become healthy..." -ForegroundColor Cyan
$healthy = $false
for ($i = 0; $i -lt 40; $i++) {
    if (Test-BackendHealth) { $healthy = $true; break }
    Start-Sleep -Seconds 3
}

if ($healthy) {
    Write-Host "Platform is running." -ForegroundColor Green
} else {
    Write-Host "Containers restarted but the backend did not report healthy in time. Check 'Service Status' shortly." -ForegroundColor Yellow
}
