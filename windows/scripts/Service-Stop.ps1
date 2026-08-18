<#
.SYNOPSIS
    Stops the IOC Intelligence Platform (all Docker Compose services), without
    deleting any data -- containers are stopped, not removed with -v.
    Wired to the "Stop Platform" Start Menu shortcut.
#>
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")
Assert-Elevated

if (-not (Test-Path $script:EnvFilePath)) {
    Write-Host "No configuration found -- nothing to stop." -ForegroundColor Yellow
    exit 0
}

Write-Host "Stopping HORIZON GRID..." -ForegroundColor Cyan
$exitCode = Invoke-DockerCompose "stop"
if ($exitCode -ne 0) {
    Write-Host "Failed to stop cleanly (exit code $exitCode). See $script:LogsDir for details." -ForegroundColor Red
    exit $exitCode
}

Write-Host "Platform stopped." -ForegroundColor Green
