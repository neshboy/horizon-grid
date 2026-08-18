<#
.SYNOPSIS
    Shows whether the platform is installed, running, and healthy. Wired to
    the "Service Status" Start Menu shortcut -- opens a console window and
    stays open (Pause at the end) since this is meant to be read, not piped.
#>
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")
Assert-Elevated

Write-Host "HORIZON GRID -- Service Status" -ForegroundColor Cyan
Write-Host ("=" * 44)

if (-not (Test-Path $script:EnvFilePath)) {
    Write-Host "Not configured yet. Run 'Configuration' from the Start Menu to set up the platform." -ForegroundColor Yellow
    Pause
    exit 1
}

Write-Host "`nContainers:" -ForegroundColor Cyan
Sync-ComposeEnvFile
Push-Location $script:AppRepoDir
try {
    & docker.exe compose -f docker-compose.yml -f docker-compose.prod.yml --env-file $script:EnvFilePath ps
} finally {
    Pop-Location
}

Write-Host "`nHealth checks:" -ForegroundColor Cyan
$backendOk = Test-BackendHealth
$frontendOk = Test-FrontendHealth
Write-Host ("  Backend API : " + $(if ($backendOk) { "OK" } else { "NOT RESPONDING" })) -ForegroundColor $(if ($backendOk) { "Green" } else { "Red" })
Write-Host ("  Web interface: " + $(if ($frontendOk) { "OK" } else { "NOT RESPONDING" })) -ForegroundColor $(if ($frontendOk) { "Green" } else { "Red" })

Write-Host "`nDocker Desktop:" -ForegroundColor Cyan
$dockerRunning = $false
try {
    $null = & docker.exe info --format '{{.ServerVersion}}' 2>$null
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch {}
Write-Host ("  " + $(if ($dockerRunning) { "Running" } else { "NOT RUNNING -- start Docker Desktop first" })) -ForegroundColor $(if ($dockerRunning) { "Green" } else { "Red" })

Write-Host ""
Pause
