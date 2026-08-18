<#
.SYNOPSIS
    Builds a redacted diagnostic bundle (zip) for support/troubleshooting.
    Wired to the "Diagnostics" Start Menu shortcut.

.DESCRIPTION
    Collects: docker compose ps/logs output, the setup log, prerequisite
    check output, and basic system info -- all with secrets stripped before
    anything is written to the zip. The real .env is NEVER copied in; instead
    a redacted version is generated where every value on a line matching a
    known secret-bearing variable name is replaced with "***REDACTED***",
    keeping the variable name (useful for confirming a key IS set without
    ever revealing it).
#>
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")
Assert-Elevated

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bundleDir = Join-Path $env:TEMP "ioc-diagnostics-$stamp"
$zipPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "ioc-diagnostics-$stamp.zip"
New-Item -ItemType Directory -Path $bundleDir -Force | Out-Null

Write-Host "Collecting diagnostics..." -ForegroundColor Cyan

# --- Redacted .env: variable names only, values scrubbed ---
# Every key the wizard ever writes is secret-shaped enough (API keys, DB
# passwords, JWT secret) to redact wholesale rather than trying to maintain
# an allowlist of "safe" keys that will inevitably go stale.
if (Test-Path $script:EnvFilePath) {
    $redacted = Get-Content $script:EnvFilePath | ForEach-Object {
        if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') {
            $name = $Matches[1]
            $value = $Matches[2]
            if ($value) { "$name=***REDACTED***(set, $($value.Length) chars)" } else { "$name=(not set)" }
        } else {
            $_ # comments/blank lines -- no secret content
        }
    }
    $redacted | Out-File (Join-Path $bundleDir "env-redacted.txt") -Encoding utf8
} else {
    "No .env file found at $script:EnvFilePath" | Out-File (Join-Path $bundleDir "env-redacted.txt") -Encoding utf8
}

# --- Setup log (already human-readable, never contains secret values) ---
if (Test-Path $script:SetupLogPath) {
    Copy-Item $script:SetupLogPath (Join-Path $bundleDir "setup.log") -ErrorAction SilentlyContinue
}

# --- Container status + recent logs (docker logs can theoretically echo
# request bodies if the app logged them, so cap history and note the risk) ---
if (Test-Path $script:AppRepoDir) {
    Sync-ComposeEnvFile
    Push-Location $script:AppRepoDir
    try {
        & docker.exe compose -f docker-compose.yml -f docker-compose.prod.yml --env-file $script:EnvFilePath ps 2>&1 |
            Out-File (Join-Path $bundleDir "container-status.txt") -Encoding utf8
        foreach ($svc in @("backend", "frontend", "celery_worker", "celery_beat", "postgres", "redis", "neo4j", "opensearch")) {
            & docker.exe compose -f docker-compose.yml -f docker-compose.prod.yml --env-file $script:EnvFilePath logs --tail 200 $svc 2>&1 |
                Out-File (Join-Path $bundleDir "logs-$svc.txt") -Encoding utf8
        }
    } finally {
        Pop-Location
    }
}

# --- Prerequisite check (informational, never touches secrets) ---
$prereqScript = Join-Path $ScriptRoot "Check-Prerequisites.ps1"
if (Test-Path $prereqScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $prereqScript 2>&1 |
        Out-File (Join-Path $bundleDir "prerequisites.txt") -Encoding utf8
}

# --- Basic system info ---
@(
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    "OS: $((Get-CimInstance Win32_OperatingSystem).Caption) build $((Get-CimInstance Win32_OperatingSystem).BuildNumber)"
    "InstallDir: $script:InstallDir"
    "DataDir: $script:DataDir"
) -join "`r`n" | Out-File (Join-Path $bundleDir "system-info.txt") -Encoding utf8

Write-Host "Redacting known secret patterns from collected logs..." -ForegroundColor Cyan
# A defense-in-depth second pass: even though the .env itself is never
# copied, application logs (especially a Python traceback on a DB connect
# failure) could echo a full connection string or a raw provider key with
# no "password:"/"api_key:" label anywhere nearby. Confirmed live with a
# synthetic DATABASE_URL=postgresql://user:RealPassword@host/db line and a
# bare sk-ant-... key: the original label-only patterns below missed BOTH
# completely, which would have shipped a "redacted" bundle that actually
# contained live credentials. This list is deliberately shape-based, not
# just label-based, to catch secrets appearing with no nearby label at all.
$secretPatterns = @(
    # Label-adjacent values (original patterns, still useful for anything
    # not already covered by a shape below).
    '(?i)(authorization:\s*bearer\s+)[A-Za-z0-9\-_\.]+', '$1***REDACTED***'
    '(?i)(api[_-]?key["\'':=\s]+)[A-Za-z0-9\-_]{8,}', '$1***REDACTED***'
    '(?i)(password["\'':=\s]+)\S+', '$1***REDACTED***'
    # Connection strings with embedded user:password@host credentials --
    # matches postgresql://, postgresql+asyncpg://, redis://, bolt://,
    # mongodb://, etc. Keeps the scheme and host/db visible (useful for
    # diagnosing a real connectivity problem) and redacts only the
    # credential portion between the scheme and the @. The username group
    # is optional ([^/@\s:]*, not +) because redis:// URLs commonly have no
    # username at all (redis://:password@host) -- confirmed live that
    # requiring 1+ chars there let a real REDIS_URL password through whole.
    '(?i)([a-z][a-z0-9+.-]*://)[^/@\s:]*:[^/@\s]+@', '$1***REDACTED***@'
    # Anthropic API keys.
    'sk-ant-[A-Za-z0-9_-]{20,}', '***REDACTED-ANTHROPIC-KEY***'
    # Generic OpenAI-shaped / other "sk-" prefixed live keys.
    '(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}', '***REDACTED-API-KEY***'
    # AWS access key IDs and the shape of a secret access key value.
    'AKIA[A-Z0-9]{16}', '***REDACTED-AWS-ACCESS-KEY-ID***'
    '(?i)(aws_secret_access_key["\'':=\s]+)[A-Za-z0-9/+=]{30,}', '$1***REDACTED***'
    # Google API keys.
    'AIza[A-Za-z0-9_-]{35}', '***REDACTED-GOOGLE-KEY***'
    # JWTs (three base64url segments separated by dots) -- covers a raw
    # token appearing in a log line with no "Bearer" prefix at all.
    '\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b', '***REDACTED-JWT***'
)
Get-ChildItem $bundleDir -Filter "*.txt" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    for ($i = 0; $i -lt $secretPatterns.Count; $i += 2) {
        $content = $content -replace $secretPatterns[$i], $secretPatterns[$i + 1]
    }
    Set-Content -Path $_.FullName -Value $content -Encoding utf8
}

Compress-Archive -Path (Join-Path $bundleDir "*") -DestinationPath $zipPath -Force
Remove-Item $bundleDir -Recurse -Force

Write-Host "Diagnostic bundle written to:" -ForegroundColor Green
Write-Host "  $zipPath" -ForegroundColor Green
Write-Host "`nThis bundle has secrets redacted, but review it yourself before sharing it with anyone." -ForegroundColor Yellow
Pause
