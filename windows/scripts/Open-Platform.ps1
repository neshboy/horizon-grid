<#
.SYNOPSIS
    Wired to the "Open Platform" Start Menu/desktop shortcut in place of a
    bare .url file that just opened a browser tab -- confirmed live (real
    Windows reboot test) that a bare .url file left the user staring at a
    connection-refused page for as long as it took Docker Desktop and the
    containers to come back up, with zero indication of what was wrong or
    what to do about it. This checks whether the platform is actually
    reachable first, starts it if not (waiting for Docker Desktop itself if
    that's still starting up too, which is the normal case right after a
    reboot), waits for the backend to report healthy, and only then opens
    the browser -- so "click the icon" is the whole recovery story a user
    ever needs to know, exactly like the master installer requirement this
    was written against.
#>
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptRoot "Common.ps1")

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Show-StatusForm {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "HORIZON GRID"
    $form.Size = New-Object System.Drawing.Size(420, 140)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "Starting the platform..."
    $label.AutoSize = $false
    $label.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $label.Dock = [System.Windows.Forms.DockStyle]::Top
    $label.Height = 60
    $label.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $form.Controls.Add($label)

    $bar = New-Object System.Windows.Forms.ProgressBar
    $bar.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
    $bar.MarqueeAnimationSpeed = 30
    $bar.Dock = [System.Windows.Forms.DockStyle]::Bottom
    $bar.Height = 20
    $form.Controls.Add($bar)

    $form.Show()
    $form.Refresh()
    return @{ Form = $form; Label = $label }
}

function Update-Status($ui, [string]$text) {
    $ui.Label.Text = $text
    $ui.Form.Refresh()
    [System.Windows.Forms.Application]::DoEvents()
}

function Get-ConfiguredFrontendPort {
    # Real gap found live during overnight QA: both Start-Process calls in
    # this script hardcoded "http://localhost:3000", ignoring a HOST_PORT_
    # FRONTEND the setup wizard's own port-conflict page can (and does)
    # remap a real install to (see Check-Prerequisites.ps1's own comment on
    # that page) -- a customized install's shortcut always opened whatever
    # happened to be on port 3000 (a connection-refused page, or worse, an
    # unrelated service) instead of the platform's real frontend port.
    # Wrapped in try/catch: on the pre-elevation fast path below, the
    # ACL-locked config file may throw access-denied for a non-elevated
    # caller (see this script's own existing comment further down) --
    # falling back to the documented default (3000) rather than forcing an
    # elevation prompt just to open a browser tab for the common case.
    try {
        if (Test-Path $script:EnvFilePath) {
            $line = Get-Content $script:EnvFilePath -ErrorAction Stop | Where-Object { $_ -match '^\s*HOST_PORT_FRONTEND\s*=\s*(\d+)' }
            if ($line -and $Matches[1]) { return [int]$Matches[1] }
        }
    } catch {}
    return 3000
}

# Already up? Skip every startup step and go straight to the browser --
# this is the common case (platform already running) and shouldn't pay for
# a UAC prompt or a status window it doesn't need.
if ((Test-BackendHealth) -and (Test-FrontendHealth)) {
    Start-Process "http://localhost:$(Get-ConfiguredFrontendPort)"
    exit 0
}

$ui = Show-StatusForm

Update-Status $ui "Checking Docker Desktop..."
$dockerRunning = $false
try {
    $null = & docker.exe info --format '{{.ServerVersion}}' 2>$null
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch {}

if (-not $dockerRunning) {
    Update-Status $ui "Starting Docker Desktop (this can take a minute after a reboot)..."
    $dockerDesktopExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktopExe) {
        Start-Process -FilePath $dockerDesktopExe
    }
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        try {
            $null = & docker.exe info --format '{{.ServerVersion}}' 2>$null
            if ($LASTEXITCODE -eq 0) { $dockerRunning = $true; break }
        } catch {}
    }
    if (-not $dockerRunning) {
        Update-Status $ui "Docker Desktop did not start in time."
        [System.Windows.Forms.MessageBox]::Show(
            "Docker Desktop did not become ready within 3 minutes. Start it manually from the Start Menu, then try this shortcut again.",
            "HORIZON GRID", "OK", "Warning") | Out-Null
        $ui.Form.Close()
        exit 1
    }
}

# ProgramData\...\config\.env is ACL-locked to Administrators+SYSTEM --
# confirmed live (real post-reboot test) that checking it BEFORE elevating
# doesn't just return false for a non-elevated caller, it throws an
# access-denied error that Test-Path surfaces as "the path doesn't exist",
# which then incorrectly told a fully-configured platform's owner to go
# run Configuration first, on exactly the cold-start path this script
# exists to handle. Assert-Elevated (relaunching this whole script) only
# fires here, on the actual cold-start path, not on the common
# already-running path above, so a user who left the platform running
# doesn't see a UAC prompt just for clicking the desktop icon -- but
# everything from here on on this path needs to run elevated to even ask
# the ACL-locked filesystem an honest question.
#
# Real gaps found live during overnight QA, both around this exact
# relaunch: (1) Assert-Elevated (Common.ps1) has no idea this script has a
# visible WinForms dialog open ($ui) -- it just exits the current process,
# leaving that dialog to be torn down by raw process termination rather
# than a clean Form.Close(), which can leave a stale/frozen window image on
# screen for a moment. (2) Assert-Elevated's own Start-Process -Verb RunAs
# call has no -WindowStyle Hidden, so the relaunched elevated PowerShell
# process shows a plain console window alongside this GUI-only tool's own
# status dialog -- jarring on exactly the cold-start path a user is most
# likely to hit right after a reboot. Assert-Elevated is shared by several
# other, genuinely console-based scripts (Restore-Database.ps1 etc.) that
# DO want a visible console, so this does its own scoped relaunch here
# instead of changing that shared helper for everyone.
$isElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isElevated) {
    $ui.Form.Close()
    $scriptPath = $MyInvocation.PSCommandPath
    try {
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$scriptPath`"") `
            -WindowStyle Hidden -Verb RunAs | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show(
            "Administrator privileges are required and the elevation prompt was declined or failed. Try this shortcut again.",
            "HORIZON GRID", "OK", "Warning") | Out-Null
    }
    exit 0
}

if (-not (Test-Path $script:EnvFilePath)) {
    $ui.Form.Close()
    [System.Windows.Forms.MessageBox]::Show(
        "Not configured yet. Run 'Configuration' from the Start Menu first.",
        "HORIZON GRID", "OK", "Warning") | Out-Null
    exit 1
}

Update-Status $ui "Starting platform services..."
$exitCode = Invoke-DockerCompose "up" "-d"
if ($exitCode -ne 0) {
    Update-Status $ui "Failed to start (exit code $exitCode)."
    [System.Windows.Forms.MessageBox]::Show(
        "Failed to start the platform (exit code $exitCode). See $script:LogsDir for details, or run 'Service Status' from the Start Menu.",
        "HORIZON GRID", "OK", "Error") | Out-Null
    $ui.Form.Close()
    exit 1
}

Update-Status $ui "Waiting for the platform to become healthy..."
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    if ((Test-BackendHealth) -and (Test-FrontendHealth)) { $healthy = $true; break }
    Start-Sleep -Seconds 3
}

$ui.Form.Close()

if (-not $healthy) {
    [System.Windows.Forms.MessageBox]::Show(
        "The platform started but did not report healthy within 3 minutes. Run 'Service Status' from the Start Menu to check what's wrong.",
        "HORIZON GRID", "OK", "Warning") | Out-Null
    exit 1
}

Start-Process "http://localhost:$(Get-ConfiguredFrontendPort)"
