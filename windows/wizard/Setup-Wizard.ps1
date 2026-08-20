<#
.SYNOPSIS
    First-run setup wizard for the IOC Intelligence Platform. Launched by
    the Inno Setup installer's [Run] step immediately after files are
    copied, and again later from the Start Menu ("Configuration") if the
    administrator wants to change any setting.

.DESCRIPTION
    Real WinForms GUI (no HTML/Electron) driving the real backend:

        Welcome -> Admin Account -> AI Configuration -> Provider Configuration
            -> Port Review -> Summary -> Install/Start -> Health Check -> Finish

    Every "Test Connection" button makes a real HTTP call to the platform's
    own POST /api/v1/providers/{id}/test endpoint (added specifically for
    this wizard -- see backend/app/providers/connection_test.py) once the
    stack is running; before the stack is up, ports/secrets are collected
    and written, THEN docker compose is started, THEN provider testing and
    admin-account creation happen against the real running backend.
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# Every page after Welcome writes to Program Files / ProgramData and locks
# those paths down with icacls -- without a genuinely elevated token,
# Initialize-DataDirectories creates a directory this process then can't
# write back into, which fails every later step with no visible error at
# all. Being in the Administrators group is not sufficient on its own: UAC
# gives a split-token admin account a FILTERED token for any normally-
# launched process -- confirmed live, this exact check rejected a real
# admin account when launched via the installer's own [Run] postinstall
# step, which does not inherit the installer's elevation. Self-relaunch
# elevated via the UAC prompt rather than just telling the administrator to
# do it manually -- that's a needless extra step for something this script
# can just do itself.
$IsElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $IsElevated) {
    try {
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$($MyInvocation.MyCommand.Path)`"") `
            -Verb RunAs | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show(
            "This setup wizard needs Administrator privileges to write configuration and manage Docker containers, and the elevation prompt was declined or failed.`n`nRight-click the shortcut and choose 'Run as administrator' to try again.",
            "Administrator privileges required",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
    }
    exit 0
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptsDir = Join-Path (Split-Path -Parent $ScriptRoot) "scripts"
. (Join-Path $ScriptsDir "Common.ps1")
. (Join-Path $ScriptsDir "Write-EnvFile.ps1")

# ---------------------------------------------------------------------------
# Shared visual style -- built once so every page looks consistent without
# repeating font/color setup on every control.
# ---------------------------------------------------------------------------
$FormBg = [System.Drawing.Color]::FromArgb(15, 17, 21)
$PanelBg = [System.Drawing.Color]::FromArgb(24, 27, 33)
$AccentColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$TextColor = [System.Drawing.Color]::FromArgb(230, 230, 235)
$MutedColor = [System.Drawing.Color]::FromArgb(150, 155, 165)
$ErrorColor = [System.Drawing.Color]::FromArgb(220, 80, 80)
$SuccessColor = [System.Drawing.Color]::FromArgb(70, 180, 110)
$FontRegular = New-Object System.Drawing.Font("Segoe UI", 9.5)
$FontHeading = New-Object System.Drawing.Font("Segoe UI Semibold", 16)
$FontSubheading = New-Object System.Drawing.Font("Segoe UI", 10)

function New-StyledButton {
    param([string]$Text, [int]$X, [int]$Y, [int]$W = 130, [bool]$Primary = $true)
    $btn = New-Object System.Windows.Forms.Button
    $btn.Text = $Text
    $btn.Location = New-Object System.Drawing.Point($X, $Y)
    $btn.Size = New-Object System.Drawing.Size($W, 34)
    $btn.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $btn.Font = $FontRegular
    if ($Primary) {
        $btn.BackColor = $AccentColor
        $btn.ForeColor = [System.Drawing.Color]::White
        $btn.FlatAppearance.BorderSize = 0
    } else {
        $btn.BackColor = $PanelBg
        $btn.ForeColor = $TextColor
        $btn.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(60, 64, 72)
        $btn.FlatAppearance.BorderSize = 1
    }
    return $btn
}

function New-StyledLabel {
    # $Height defaults to 24 (fine for a short single-line label), but every
    # caller passing a real sentence/paragraph -- confirmed live via a
    # screenshot on the Administrator Account page, where the explanatory
    # note visibly overlapped the Email field below it -- needs enough
    # vertical room for the text to actually wrap into, since this Label has
    # no AutoSize and WinForms will not grow a fixed-size control to fit
    # multi-line text on its own.
    param([string]$Text, [int]$X, [int]$Y, [int]$W = 500, [int]$Height = 24, [System.Drawing.Font]$Font = $FontRegular, [System.Drawing.Color]$Color = $TextColor)
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = $Text
    $lbl.Location = New-Object System.Drawing.Point($X, $Y)
    $lbl.Size = New-Object System.Drawing.Size($W, $Height)
    $lbl.Font = $Font
    $lbl.ForeColor = $Color
    $lbl.BackColor = [System.Drawing.Color]::Transparent
    return $lbl
}

function New-StyledTextBox {
    param([int]$X, [int]$Y, [int]$W = 400, [bool]$Password = $false)
    $tb = New-Object System.Windows.Forms.TextBox
    $tb.Location = New-Object System.Drawing.Point($X, $Y)
    $tb.Size = New-Object System.Drawing.Size($W, 26)
    $tb.Font = $FontRegular
    $tb.BackColor = $PanelBg
    $tb.ForeColor = $TextColor
    $tb.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
    if ($Password) { $tb.UseSystemPasswordChar = $true }
    return $tb
}

# ---------------------------------------------------------------------------
# Main form + page container. Each "page" is a Panel filled/emptied into
# $ContentPanel by Show-Page -- simplest reliable wizard pattern in WinForms
# without a third-party wizard control.
# ---------------------------------------------------------------------------
$Form = New-Object System.Windows.Forms.Form
$Form.Text = "HORIZON GRID -- Setup"
$Form.Size = New-Object System.Drawing.Size(720, 620)
$Form.StartPosition = "CenterScreen"
$Form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
$Form.MaximizeBox = $false
$Form.BackColor = $FormBg
$Form.Font = $FontRegular

$HeaderPanel = New-Object System.Windows.Forms.Panel
$HeaderPanel.Size = New-Object System.Drawing.Size(720, 70)
$HeaderPanel.Location = New-Object System.Drawing.Point(0, 0)
$HeaderPanel.BackColor = $PanelBg
$HeaderTitle = New-StyledLabel -Text "HORIZON GRID" -X 24 -Y 14 -W 500 -Font $FontHeading
$HeaderSubtitle = New-StyledLabel -Text "Setup" -X 24 -Y 42 -W 500 -Font $FontSubheading -Color $MutedColor
$HeaderPanel.Controls.AddRange(@($HeaderTitle, $HeaderSubtitle))

$ContentPanel = New-Object System.Windows.Forms.Panel
$ContentPanel.Size = New-Object System.Drawing.Size(680, 440)
$ContentPanel.Location = New-Object System.Drawing.Point(20, 90)
$ContentPanel.BackColor = $FormBg

$FooterPanel = New-Object System.Windows.Forms.Panel
$FooterPanel.Size = New-Object System.Drawing.Size(720, 70)
$FooterPanel.Location = New-Object System.Drawing.Point(0, 540)
$FooterPanel.BackColor = $PanelBg

$Form.Controls.AddRange(@($HeaderPanel, $ContentPanel, $FooterPanel))

# ---------------------------------------------------------------------------
# Wizard state -- one place, so every page function reads/writes the same
# object rather than passing a dozen parameters around.
# ---------------------------------------------------------------------------
$State = @{
    Settings         = New-DefaultPlatformSettings
    AdminEmail       = ""
    AdminPassword    = ""
    AdminFullName    = ""
    AccessToken      = $null
    IsUpgrade        = Test-Path $script:EnvFilePath
    SetupSucceeded   = $false
}

# Real gap fixed: the AI Configuration and Providers pages let an operator
# click "Next" regardless of whether Test Connection was ever clicked, or
# even after it just failed -- nothing stopped an obviously-broken
# credential/base_url from being written to .env as if it were valid,
# directly contradicting this platform's own "must not save obviously
# invalid config as valid" requirement. Keyed by backend/provider id ->
# @{ Signature; Ok }, where Signature is the exact JSON body that was last
# tested for that id -- each page's Validate block only blocks Next when the
# CURRENT textbox values still match a Signature whose last real test
# result was Ok=$false. Deliberately does NOT block on "never tested": on a
# fresh install the backend isn't running yet, so a live test is genuinely
# impossible before this point -- see the Summary/Install page's own
# post-health-check AI validation for how that case is still honestly
# reported rather than silently assumed to be fine.
$script:AiTestState = @{}
$script:AiGetters = @{}
$script:ProviderTestState = @{}

# If this is a re-run (Configuration from the Start Menu) on an existing
# install, load the real current values instead of starting from scratch.
if ($State.IsUpgrade) {
    try {
        Get-Content $script:EnvFilePath | ForEach-Object {
            if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') {
                $key = $Matches[1]; $val = $Matches[2]
                $map = @{
                    JWT_SECRET_KEY = "JwtSecretKey"; POSTGRES_PASSWORD = "PostgresPassword"; NEO4J_PASSWORD = "Neo4jPassword"
                    HOST_PORT_FRONTEND = "PortFrontend"; HOST_PORT_BACKEND = "PortBackend"; HOST_PORT_POSTGRES = "PortPostgres"
                    HOST_PORT_REDIS = "PortRedis"; HOST_PORT_NEO4J_HTTP = "PortNeo4jHttp"; HOST_PORT_NEO4J_BOLT = "PortNeo4jBolt"
                    HOST_PORT_OPENSEARCH = "PortOpenSearch"; PUBLIC_API_URL = "PublicApiUrl"; DETECTED_LAN_IP = "DetectedLanIp"
                    AI_BACKEND = "AiBackend"; OLLAMA_BASE_URL = "OllamaBaseUrl"
                    OLLAMA_MODEL = "OllamaModel"; BEDROCK_API_KEY = "BedrockApiKey"; AWS_ACCESS_KEY_ID = "AwsAccessKeyId"
                    AWS_SECRET_ACCESS_KEY = "AwsSecretAccessKey"; AWS_REGION = "AwsRegion"; BEDROCK_MODEL_ID = "BedrockModelId"
                    GEMINI_API_KEY = "GeminiApiKey"; GEMINI_MODEL_ID = "GeminiModelId"; ANTHROPIC_API_KEY = "AnthropicApiKey"
                    ANTHROPIC_MODEL_ID = "AnthropicModelId"; GROQ_API_KEY = "GroqApiKey"; GROQ_MODEL_ID = "GroqModelId"
                    OPENAI_API_KEY = "OpenAiApiKey"; OPENAI_MODEL_ID = "OpenAiModelId"
                    KIMI_API_KEY = "KimiApiKey"; KIMI_MODEL_ID = "KimiModelId"
                    DEEPSEEK_API_KEY = "DeepSeekApiKey"; DEEPSEEK_MODEL_ID = "DeepSeekModelId"
                    XAI_API_KEY = "XaiApiKey"; XAI_MODEL_ID = "XaiModelId"
                    MISTRAL_API_KEY = "MistralApiKey"; MISTRAL_MODEL_ID = "MistralModelId"
                    OPENROUTER_API_KEY = "OpenRouterApiKey"; OPENROUTER_MODEL_ID = "OpenRouterModelId"
                    VIRUSTOTAL_API_KEY = "VirusTotalApiKey"; ABUSEIPDB_API_KEY = "AbuseIpdbApiKey"
                    OTX_API_KEY = "OtxApiKey"; NVD_API_KEY = "NvdApiKey"; ABUSECH_AUTH_KEY = "AbuseChAuthKey"
                    HYBRID_ANALYSIS_API_KEY = "HybridAnalysisApiKey"; CENSYS_PERSONAL_ACCESS_TOKEN = "CensysPersonalAccessToken"
                    CENSYS_ORGANIZATION_ID = "CensysOrganizationId"; PHISHTANK_API_KEY = "PhishTankApiKey"
                }
                if ($map.ContainsKey($key)) {
                    $propName = $map[$key]
                    if ($propName -match '^Port') { $State.Settings[$propName] = [int]$val } else { $State.Settings[$propName] = $val }
                }
            }
        }
        Write-SetupLog "Loaded existing configuration from $script:EnvFilePath for re-run."
    } catch {
        Write-SetupLog "Could not parse existing .env, starting from defaults: $_" "WARN"
    }
}

# ---------------------------------------------------------------------------
# Session acquisition for live "Test Connection" calls.
#
# ROOT CAUSE (found during the API-configuration reliability investigation):
# every Test Connection button on the Providers and AI Configuration pages
# requires $State.AccessToken, but the ONLY place that was ever set was deep
# inside the Summary page's "Start Installation" click handler -- meaning
# testing a credential required fully completing installation first (a much
# heavier action than "let me check this key"), and on a reconfigure run
# where the administrator sensibly leaves the Admin Account page blank to
# keep their account unchanged, no login was ever attempted at all, so
# $State.AccessToken stayed $null for the entire session and every Test
# Connection click failed with a confusing "create the admin account first"
# message -- even though the account already existed and the platform was
# already running. Back was also found to be disabled immediately after a
# successful install, so even entering credentials and completing
# installation didn't leave a path back to the Providers page to test with
# the token that install had just obtained.
#
# FIX: decouple "get a session to test with" from "install/save". This
# function is called on demand, directly from a Test Connection click, and
# only ever LOGS IN (never registers/creates an account) -- it cannot change
# or create anything. It works the moment the operator has typed their
# existing admin email + password on the Administrator Account page, with no
# need to visit the Summary page at all.
# ---------------------------------------------------------------------------
function Get-OrCreateWizardSession {
    if ($State.AccessToken) { return $State.AccessToken }
    if (-not $State.AdminEmail -or -not $State.AdminPassword) {
        return $null
    }
    try {
        $loginBody = @{ email = $State.AdminEmail; password = $State.AdminPassword } | ConvertTo-Json
        $loginResp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/auth/login" `
            -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 15
        $State.AccessToken = $loginResp.access_token
        Write-SetupLog "Signed in to obtain a test session for $($State.AdminEmail)."
        return $State.AccessToken
    } catch {
        Write-SetupLog "Get-OrCreateWizardSession: sign-in failed: $($_.Exception.Message)" "WARN"
        return $null
    }
}

function Get-FriendlyHttpError {
    <#
    .SYNOPSIS
        Extracts the backend's real error detail from a failed
        Invoke-RestMethod call, instead of PowerShell's generic
        "The remote server returned an error: (403) Forbidden."-style
        wrapper -- e.g. surfaces "Role 'analyst' lacks permission
        'provider:manage'" verbatim, which is the specific, actionable
        message app/auth/rbac.py's require_permission() already returns.
        Applies Phase 4's "do not hide the error" rule to every Test
        Connection button consistently, not just the ones written for this
        fix -- the same gap existed on the pre-existing intel-provider Test
        buttons too.
    #>
    param($ErrorRecord)
    $raw = $ErrorRecord.ErrorDetails.Message
    if ($raw) {
        try {
            $parsed = $raw | ConvertFrom-Json
            if ($parsed.detail) { return $parsed.detail }
        } catch {
            # Not JSON -- fall through and use the raw body as-is.
        }
        return $raw
    }
    return $ErrorRecord.Exception.Message
}

$Pages = @()
$CurrentPageIndex = 0

function Show-Page {
    param([int]$Index)
    $ContentPanel.Controls.Clear()
    $panel = & $Pages[$Index].Build
    $ContentPanel.Controls.Add($panel)
    $script:CurrentPageIndex = $Index
    $BackButton.Enabled = ($Index -gt 0) -and $Pages[$Index].AllowBack
    $NextButton.Text = if ($Index -eq $Pages.Count - 1) { "Finish" } else { "Next" }
}

$BackButton = New-StyledButton -Text "< Back" -X 380 -Y 18 -W 100 -Primary $false
$NextButton = New-StyledButton -Text "Next >" -X 580 -Y 18 -W 100 -Primary $true
$CancelButton = New-StyledButton -Text "Cancel" -X 24 -Y 18 -W 100 -Primary $false
$FooterPanel.Controls.AddRange(@($BackButton, $NextButton, $CancelButton))

$CancelButton.Add_Click({
    $confirm = [System.Windows.Forms.MessageBox]::Show(
        "Exit setup? You can run it again later from the Start Menu.",
        "Cancel Setup", [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($confirm -eq [System.Windows.Forms.DialogResult]::Yes) { $Form.Close() }
})

$BackButton.Add_Click({
    if ($script:CurrentPageIndex -gt 0) { Show-Page -Index ($script:CurrentPageIndex - 1) }
})

$NextButton.Add_Click({
    $page = $Pages[$script:CurrentPageIndex]
    $proceed = $true
    if ($page.Validate) { $proceed = & $page.Validate }
    if (-not $proceed) { return }
    if ($script:CurrentPageIndex -eq $Pages.Count - 1) {
        $Form.Close()
    } else {
        Show-Page -Index ($script:CurrentPageIndex + 1)
    }
})

# ---------------------------------------------------------------------------
# Page: Welcome
# ---------------------------------------------------------------------------
$Pages += @{
    AllowBack = $false
    Build = {
        $p = New-Object System.Windows.Forms.Panel
        $p.Size = $ContentPanel.Size
        $title = if ($State.IsUpgrade) { "Reconfigure HORIZON GRID" } else { "Welcome" }
        $intro = if ($State.IsUpgrade) {
            "This wizard will update your existing configuration. Your investigation data, cases, and history are not affected -- only settings in this wizard change."
        } else {
            "This wizard will configure HORIZON GRID: an administrator account, your AI backend, and the threat-intelligence providers you want enabled.`n`nYou'll need Docker Desktop installed and running. Provider API keys are optional -- you can add them now, later, or never; the platform works with whichever providers you've configured."
        }
        $p.Controls.Add((New-StyledLabel -Text $title -X 0 -Y 10 -W 640 -Font $FontHeading))
        $lbl = New-StyledLabel -Text $intro -X 0 -Y 60 -W 640 -Font $FontRegular -Color $MutedColor
        $lbl.Size = New-Object System.Drawing.Size(640, 160)
        $lbl.AutoSize = $false
        $p.Controls.Add($lbl)
        return $p
    }
}

# ---------------------------------------------------------------------------
# Page: Administrator Account
# ---------------------------------------------------------------------------
$Pages += @{
    AllowBack = $true
    Build = {
        $p = New-Object System.Windows.Forms.Panel
        $p.Size = $ContentPanel.Size
        $p.Controls.Add((New-StyledLabel -Text "Administrator Account" -X 0 -Y 0 -W 640 -Font $FontHeading))
        $note = if ($State.IsUpgrade) {
            "An administrator account already exists. Leave these fields blank to keep it unchanged, or re-enter your existing email and password to sign in for this session -- that's what enables the live Test Connection buttons below, without changing your account."
        } else {
            "This creates the first user account, which becomes the platform's Administrator automatically (the backend's own rule: the first registered user gets the Admin role -- see docs/SECURITY.md)."
        }
        # Height=64 (up to 3 lines) -- the upgrade note above is longer than
        # the original one-liner it replaced (it now also explains why
        # re-entering existing credentials is worth doing), so this leaves
        # more headroom than the 48px that was measured for the shorter
        # non-upgrade note alone; Email's Y is shifted +16 accordingly.
        $p.Controls.Add((New-StyledLabel -Text $note -X 0 -Y 36 -W 640 -Height 64 -Color $MutedColor))

        $p.Controls.Add((New-StyledLabel -Text "Email" -X 0 -Y 136 -W 400))
        $tbEmail = New-StyledTextBox -X 0 -Y 160 -W 400
        $tbEmail.Text = $State.AdminEmail
        $p.Controls.Add($tbEmail)

        $p.Controls.Add((New-StyledLabel -Text "Full Name (optional)" -X 0 -Y 196))
        $tbName = New-StyledTextBox -X 0 -Y 220 -W 400
        $tbName.Text = $State.AdminFullName
        $p.Controls.Add($tbName)

        $p.Controls.Add((New-StyledLabel -Text "Password (min. 8 characters)" -X 0 -Y 256))
        $tbPass = New-StyledTextBox -X 0 -Y 280 -W 400 -Password $true
        $p.Controls.Add($tbPass)

        $p.Controls.Add((New-StyledLabel -Text "Confirm Password" -X 0 -Y 316))
        $tbConfirm = New-StyledTextBox -X 0 -Y 340 -W 400 -Password $true
        $p.Controls.Add($tbConfirm)

        $lblError = New-StyledLabel -Text "" -X 0 -Y 380 -W 600 -Color $ErrorColor
        $p.Controls.Add($lblError)

        $p.Tag = @{ Email = $tbEmail; Name = $tbName; Pass = $tbPass; Confirm = $tbConfirm; Error = $lblError }
        $script:AdminPagePanel = $p
        return $p
    }
    Validate = {
        $ctrls = $script:AdminPagePanel.Tag
        $email = $ctrls.Email.Text.Trim()
        $pass = $ctrls.Pass.Text
        $confirm = $ctrls.Confirm.Text

        if ($State.IsUpgrade -and -not $email -and -not $pass) {
            return $true # keeping existing admin account unchanged
        }
        # Deliberately stricter than a minimal "has an @ and a dot" check --
        # confirmed live (against the real backend's email_validator, not
        # guessed) that the original regex accepted several inputs the
        # backend rejects: "trailing.dot.@email.com" (period immediately
        # before @), "double..dot@email.com" (consecutive periods), an
        # over-500-char local part (the backend caps the whole address at
        # 254 chars total), and "<script>...@email.com" (unquoted <, >, and
        # other atext-illegal characters in the local part). Each of those
        # used to only surface as a raw "Account creation failed" error at
        # Start Installation, on the Summary page, instead of right where
        # the administrator typed it. Still not a full RFC 5322/IDNA
        # implementation -- deliberately not attempting to replicate
        # email_validator's full ruleset in a regex -- but now catches
        # every one of those confirmed real-world cases.
        if (-not $email -or
            $email.Length -gt 254 -or
            $email -notmatch '^[A-Za-z0-9!#$%&''*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&''*+/=?^_`{|}~-]+)*@[^@\s]+\.[^@\s]+$') {
            $ctrls.Error.Text = "Enter a valid email address."
            return $false
        }
        if ($pass.Length -lt 8) {
            $ctrls.Error.Text = "Password must be at least 8 characters."
            return $false
        }
        if ($pass.Length -gt 64) {
            $ctrls.Error.Text = "Password must be 64 characters or fewer."
            return $false
        }
        if ($pass -ne $confirm) {
            $ctrls.Error.Text = "Passwords do not match."
            return $false
        }
        $State.AdminEmail = $email
        $State.AdminFullName = $ctrls.Name.Text.Trim()
        $State.AdminPassword = $pass
        return $true
    }
}

# ---------------------------------------------------------------------------
# Page: AI Configuration
# ---------------------------------------------------------------------------
function Add-AiTestConnectionRow {
    <#
    .SYNOPSIS
        One consistent "Test Connection" button + live status label for an
        AI backend sub-panel, matching the same pattern (and now the same
        Get-OrCreateWizardSession-backed session fix) used for every
        intelligence-provider row on the Providers page.
    .PARAMETER GetCredentials
        Scriptblock returning the credentials hashtable to send, evaluated
        fresh at click time so it always reads the textbox's current text.
    .PARAMETER GetModel
        Scriptblock returning the candidate model id string (or $null).
    #>
    param($Panel, [int]$Y, [string]$BackendId, [scriptblock]$GetCredentials, [scriptblock]$GetModel)

    # Registered so the AI Configuration page's Validate block can recompute
    # the CURRENT signature for whichever backend is selected at Next-click
    # time, using the exact same credential-gathering logic this button
    # itself uses -- see $script:AiTestState's declaration for why.
    $script:AiGetters[$BackendId] = @{ Creds = $GetCredentials; Model = $GetModel }

    $btn = New-StyledButton -Text "Test Connection" -X 0 -Y $Y -W 160 -Primary $false
    $lblStatus = New-StyledLabel -Text "" -X 172 -Y ($Y + 7) -W 460 -Height 40 -Color $MutedColor
    $Panel.Controls.Add($btn)
    $Panel.Controls.Add($lblStatus)

    $btn.Add_Click({
        $lblStatus.ForeColor = $MutedColor
        $lblStatus.Text = "Testing..."
        $Form.Refresh()

        $token = Get-OrCreateWizardSession
        if (-not $token) {
            $lblStatus.ForeColor = $ErrorColor
            $lblStatus.Text = "Sign-in required: enter your existing administrator email and password on the Administrator Account page, then return here to test."
            return
        }
        $creds = & $GetCredentials
        $model = & $GetModel
        $body = @{ backend = $BackendId; credentials = $creds; model = $model } | ConvertTo-Json -Compress
        try {
            $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/test" `
                -Method Post -Body $body -ContentType "application/json" `
                -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30
            if ($resp.ok) {
                $lblStatus.ForeColor = $SuccessColor
                $lblStatus.Text = "OK: $($resp.message) (model: $($resp.model), $($resp.latency_ms) ms)"
                $script:AiTestState[$BackendId] = @{ Signature = $body; Ok = $true }
            } else {
                $lblStatus.ForeColor = $ErrorColor
                $lblStatus.Text = "FAILED: $($resp.message)"
                $script:AiTestState[$BackendId] = @{ Signature = $body; Ok = $false }
            }
        } catch {
            $lblStatus.ForeColor = $ErrorColor
            $lblStatus.Text = "FAILED: $(Get-FriendlyHttpError $_)"
            $script:AiTestState[$BackendId] = @{ Signature = $body; Ok = $false }
        }
    }.GetNewClosure())
}

$Pages += @{
    AllowBack = $true
    Build = {
        $p = New-Object System.Windows.Forms.Panel
        $p.Size = $ContentPanel.Size
        $p.Controls.Add((New-StyledLabel -Text "AI Configuration" -X 0 -Y 0 -W 640 -Font $FontHeading))
        # Height=48 (2 lines) -- same overlap issue found and fixed on the
        # Administrator Account page applies here: this sentence wraps at
        # 640px width and the default single-line label height doesn't
        # leave room for the wrapped second line before "AI Backend" below.
        $p.Controls.Add((New-StyledLabel -Text "The platform uses an AI backend to summarize provider results and produce a final evidence-based assessment for each investigation." -X 0 -Y 36 -W 640 -Height 48 -Color $MutedColor))

        $p.Controls.Add((New-StyledLabel -Text "AI Backend" -X 0 -Y 110))
        $combo = New-Object System.Windows.Forms.ComboBox
        $combo.Location = New-Object System.Drawing.Point(0, 134)
        $combo.Size = New-Object System.Drawing.Size(300, 26)
        $combo.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
        $combo.Font = $FontRegular
        [void]$combo.Items.AddRange(@(
            "ollama (local, no API key, no cost)",
            "anthropic (Claude direct API key)",
            "bedrock (AWS Bedrock)",
            "gemini (Google Gemini API key)",
            "groq (fast inference, OpenAI-compatible API key)",
            "openai (ChatGPT, api.openai.com)",
            "kimi (Moonshot AI, api.moonshot.ai)",
            "deepseek (DeepSeek, api.deepseek.com)",
            "xai (Grok, api.x.ai)",
            "mistral (Mistral AI, api.mistral.ai)",
            "openrouter (meta-router across many models, openrouter.ai)"
        ))
        $backendMap = @{0="ollama"; 1="anthropic"; 2="bedrock"; 3="gemini"; 4="groq"; 5="openai"; 6="kimi"; 7="deepseek"; 8="xai"; 9="mistral"; 10="openrouter"}
        $reverseMap = @{"ollama"=0; "anthropic"=1; "bedrock"=2; "gemini"=3; "groq"=4; "openai"=5; "kimi"=6; "deepseek"=7; "xai"=8; "mistral"=9; "openrouter"=10}
        $combo.SelectedIndex = $reverseMap[$State.Settings.AiBackend]
        $p.Controls.Add($combo)

        # Sub-panels per backend -- only one visible at a time based on $combo.
        $ollamaPanel = New-Object System.Windows.Forms.Panel
        $ollamaPanel.Location = New-Object System.Drawing.Point(0, 160)
        $ollamaPanel.Size = New-Object System.Drawing.Size(640, 140)
        $ollamaPanel.Controls.Add((New-StyledLabel -Text "Requires Ollama (https://ollama.com) installed and running on this machine, or another host reachable from Docker." -X 0 -Y 0 -W 640 -Color $MutedColor))
        $ollamaPanel.Controls.Add((New-StyledLabel -Text "Ollama Model" -X 0 -Y 40))
        $tbOllamaModel = New-StyledTextBox -X 0 -Y 64 -W 300
        $tbOllamaModel.Text = $State.Settings.OllamaModel
        $ollamaPanel.Controls.Add($tbOllamaModel)
        Add-AiTestConnectionRow -Panel $ollamaPanel -Y 100 -BackendId "ollama" `
            -GetCredentials { @{ base_url = $State.Settings.OllamaBaseUrl } }.GetNewClosure() `
            -GetModel { $tbOllamaModel.Text.Trim() }.GetNewClosure()

        $anthropicPanel = New-Object System.Windows.Forms.Panel
        $anthropicPanel.Location = New-Object System.Drawing.Point(0, 160)
        $anthropicPanel.Size = New-Object System.Drawing.Size(640, 140)
        $anthropicPanel.Controls.Add((New-StyledLabel -Text "Anthropic API Key" -X 0 -Y 0))
        $tbAnthropicKey = New-StyledTextBox -X 0 -Y 24 -W 400 -Password $true
        $tbAnthropicKey.Text = $State.Settings.AnthropicApiKey
        $anthropicPanel.Controls.Add($tbAnthropicKey)
        $lnkAnthropic = New-Object System.Windows.Forms.LinkLabel
        $lnkAnthropic.Text = "console.anthropic.com"
        $lnkAnthropic.Location = New-Object System.Drawing.Point(0, 58)
        $lnkAnthropic.Size = New-Object System.Drawing.Size(300, 20)
        $lnkAnthropic.LinkColor = $AccentColor
        $lnkAnthropic.Add_LinkClicked({ Start-Process "https://console.anthropic.com" })
        $anthropicPanel.Controls.Add($lnkAnthropic)
        Add-AiTestConnectionRow -Panel $anthropicPanel -Y 90 -BackendId "anthropic" `
            -GetCredentials { @{ api_key = $tbAnthropicKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $State.Settings.AnthropicModelId }.GetNewClosure()

        $bedrockPanel = New-Object System.Windows.Forms.Panel
        $bedrockPanel.Location = New-Object System.Drawing.Point(0, 160)
        $bedrockPanel.Size = New-Object System.Drawing.Size(640, 180)
        $bedrockPanel.Controls.Add((New-StyledLabel -Text "AWS Bedrock API Key (bearer token)" -X 0 -Y 0))
        $tbBedrockKey = New-StyledTextBox -X 0 -Y 24 -W 400 -Password $true
        $tbBedrockKey.Text = $State.Settings.BedrockApiKey
        $bedrockPanel.Controls.Add($tbBedrockKey)
        $bedrockPanel.Controls.Add((New-StyledLabel -Text "AWS Region" -X 0 -Y 60))
        $tbBedrockRegion = New-StyledTextBox -X 0 -Y 84 -W 200
        $tbBedrockRegion.Text = $State.Settings.AwsRegion
        $bedrockPanel.Controls.Add($tbBedrockRegion)
        Add-AiTestConnectionRow -Panel $bedrockPanel -Y 124 -BackendId "bedrock" `
            -GetCredentials { @{ bedrock_api_key = $tbBedrockKey.Text.Trim(); aws_region = $tbBedrockRegion.Text.Trim() } }.GetNewClosure() `
            -GetModel { $State.Settings.BedrockModelId }.GetNewClosure()

        $geminiPanel = New-Object System.Windows.Forms.Panel
        $geminiPanel.Location = New-Object System.Drawing.Point(0, 160)
        $geminiPanel.Size = New-Object System.Drawing.Size(640, 140)
        $geminiPanel.Controls.Add((New-StyledLabel -Text "Gemini API Key" -X 0 -Y 0))
        $tbGeminiKey = New-StyledTextBox -X 0 -Y 24 -W 400 -Password $true
        $tbGeminiKey.Text = $State.Settings.GeminiApiKey
        $geminiPanel.Controls.Add($tbGeminiKey)
        $lnkGemini = New-Object System.Windows.Forms.LinkLabel
        $lnkGemini.Text = "aistudio.google.com/apikey"
        $lnkGemini.Location = New-Object System.Drawing.Point(0, 58)
        $lnkGemini.Size = New-Object System.Drawing.Size(300, 20)
        $lnkGemini.LinkColor = $AccentColor
        $lnkGemini.Add_LinkClicked({ Start-Process "https://aistudio.google.com/apikey" })
        $geminiPanel.Controls.Add($lnkGemini)
        Add-AiTestConnectionRow -Panel $geminiPanel -Y 90 -BackendId "gemini" `
            -GetCredentials { @{ api_key = $tbGeminiKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $State.Settings.GeminiModelId }.GetNewClosure()

        # Groq -- new AI backend. Not to be confused with "Grok" (xAI); this
        # is Groq (api.groq.com), an OpenAI-compatible fast-inference API.
        # Model field is an editable combo box, not a hard-coded dropdown --
        # it starts pre-filled with a short known-good fallback list
        # (app/ai/groq_client.py's FALLBACK_MODELS) and Test Connection
        # additionally refreshes it from Groq's own live /models endpoint
        # using whatever key was just typed, per the explicit "don't
        # hard-code a list that goes stale, prefer live discovery" guidance
        # this integration was built against.
        $groqPanel = New-Object System.Windows.Forms.Panel
        $groqPanel.Location = New-Object System.Drawing.Point(0, 160)
        $groqPanel.Size = New-Object System.Drawing.Size(640, 140)
        $groqPanel.Controls.Add((New-StyledLabel -Text "Groq API Key" -X 0 -Y 0))
        # W=300, not 400 -- the "Model" column starts at X=320 (see below); a
        # wider key field visibly overlapped it (confirmed via screenshot).
        $tbGroqKey = New-StyledTextBox -X 0 -Y 24 -W 300 -Password $true
        $tbGroqKey.Text = $State.Settings.GroqApiKey
        $groqPanel.Controls.Add($tbGroqKey)
        $lnkGroq = New-Object System.Windows.Forms.LinkLabel
        $lnkGroq.Text = "console.groq.com/keys"
        $lnkGroq.Location = New-Object System.Drawing.Point(0, 58)
        $lnkGroq.Size = New-Object System.Drawing.Size(300, 20)
        $lnkGroq.LinkColor = $AccentColor
        $lnkGroq.Add_LinkClicked({ Start-Process "https://console.groq.com/keys" })
        $groqPanel.Controls.Add($lnkGroq)
        $groqPanel.Controls.Add((New-StyledLabel -Text "Model" -X 320 -Y 0))
        $comboGroqModel = New-Object System.Windows.Forms.ComboBox
        $comboGroqModel.Location = New-Object System.Drawing.Point(320, 24)
        $comboGroqModel.Size = New-Object System.Drawing.Size(300, 26)
        $comboGroqModel.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
        $comboGroqModel.Font = $FontRegular
        [void]$comboGroqModel.Items.AddRange(@("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"))
        $comboGroqModel.Text = if ($State.Settings.GroqModelId) { $State.Settings.GroqModelId } else { "llama-3.3-70b-versatile" }
        $groqPanel.Controls.Add($comboGroqModel)
        Add-AiTestConnectionRow -Panel $groqPanel -Y 90 -BackendId "groq" `
            -GetCredentials { @{ api_key = $tbGroqKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $comboGroqModel.Text.Trim() }.GetNewClosure()

        # Refresh the Groq model list live once a key is present -- fires on
        # focus-leave (Leave), not every keystroke, so it doesn't hammer the
        # backend while typing.
        $tbGroqKey.Add_Leave({
            $apiKey = $tbGroqKey.Text.Trim()
            if (-not $apiKey) { return }
            $token = Get-OrCreateWizardSession
            if (-not $token) { return }
            try {
                $body = @{ credentials = @{ api_key = $apiKey } } | ConvertTo-Json
                $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/groq/models" `
                    -Method Post -Body $body -ContentType "application/json" `
                    -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                if ($resp.models -and $resp.models.Count -gt 0) {
                    $current = $comboGroqModel.Text
                    $comboGroqModel.Items.Clear()
                    [void]$comboGroqModel.Items.AddRange(@($resp.models))
                    $comboGroqModel.Text = if ($current) { $current } else { $resp.default }
                }
            } catch {
                # Silent -- this is a convenience refresh, not the actual
                # test. Test Connection itself still reports a real error if
                # the key doesn't work.
            }
        }.GetNewClosure())

        # OpenAI (ChatGPT) -- api.openai.com, the same forced-tool-calling
        # chat-completions shape Groq's own API is itself modeled on. Model
        # field is an editable combo box for the same reason as Groq's: it
        # starts pre-filled with a short known-good fallback list
        # (app/ai/openai_client.py's FALLBACK_MODELS) and Test Connection's
        # key-entry additionally refreshes it from OpenAI's own live
        # /models endpoint using whatever key was just typed.
        $openaiPanel = New-Object System.Windows.Forms.Panel
        $openaiPanel.Location = New-Object System.Drawing.Point(0, 160)
        $openaiPanel.Size = New-Object System.Drawing.Size(640, 140)
        $openaiPanel.Controls.Add((New-StyledLabel -Text "OpenAI API Key" -X 0 -Y 0))
        $tbOpenAiKey = New-StyledTextBox -X 0 -Y 24 -W 300 -Password $true
        $tbOpenAiKey.Text = $State.Settings.OpenAiApiKey
        $openaiPanel.Controls.Add($tbOpenAiKey)
        $lnkOpenAi = New-Object System.Windows.Forms.LinkLabel
        $lnkOpenAi.Text = "platform.openai.com/api-keys"
        $lnkOpenAi.Location = New-Object System.Drawing.Point(0, 58)
        $lnkOpenAi.Size = New-Object System.Drawing.Size(300, 20)
        $lnkOpenAi.LinkColor = $AccentColor
        $lnkOpenAi.Add_LinkClicked({ Start-Process "https://platform.openai.com/api-keys" })
        $openaiPanel.Controls.Add($lnkOpenAi)
        $openaiPanel.Controls.Add((New-StyledLabel -Text "Model" -X 320 -Y 0))
        $comboOpenAiModel = New-Object System.Windows.Forms.ComboBox
        $comboOpenAiModel.Location = New-Object System.Drawing.Point(320, 24)
        $comboOpenAiModel.Size = New-Object System.Drawing.Size(300, 26)
        $comboOpenAiModel.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
        $comboOpenAiModel.Font = $FontRegular
        [void]$comboOpenAiModel.Items.AddRange(@("gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "o3-mini"))
        $comboOpenAiModel.Text = if ($State.Settings.OpenAiModelId) { $State.Settings.OpenAiModelId } else { "gpt-4o-mini" }
        $openaiPanel.Controls.Add($comboOpenAiModel)
        Add-AiTestConnectionRow -Panel $openaiPanel -Y 90 -BackendId "openai" `
            -GetCredentials { @{ api_key = $tbOpenAiKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $comboOpenAiModel.Text.Trim() }.GetNewClosure()

        # Refresh the OpenAI model list live once a key is present -- same
        # focus-leave (not every keystroke) pattern as Groq's refresh above.
        $tbOpenAiKey.Add_Leave({
            $apiKey = $tbOpenAiKey.Text.Trim()
            if (-not $apiKey) { return }
            $token = Get-OrCreateWizardSession
            if (-not $token) { return }
            try {
                $body = @{ credentials = @{ api_key = $apiKey } } | ConvertTo-Json
                $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/openai/models" `
                    -Method Post -Body $body -ContentType "application/json" `
                    -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                if ($resp.models -and $resp.models.Count -gt 0) {
                    $current = $comboOpenAiModel.Text
                    $comboOpenAiModel.Items.Clear()
                    [void]$comboOpenAiModel.Items.AddRange(@($resp.models))
                    $comboOpenAiModel.Text = if ($current) { $current } else { $resp.default }
                }
            } catch {
                # Silent -- this is a convenience refresh, not the actual
                # test. Test Connection itself still reports a real error if
                # the key doesn't work.
            }
        }.GetNewClosure())

        # Kimi (Moonshot AI) -- api.moonshot.ai. Default model kimi-k2.5
        # deliberately avoids Moonshot's "thinking"-mode models, which 400
        # on the forced tool_choice this app always sends (see
        # app/ai/kimi_client.py for the full explanation).
        $kimiPanel = New-Object System.Windows.Forms.Panel
        $kimiPanel.Location = New-Object System.Drawing.Point(0, 160)
        $kimiPanel.Size = New-Object System.Drawing.Size(640, 140)
        $kimiPanel.Controls.Add((New-StyledLabel -Text "Kimi (Moonshot) API Key" -X 0 -Y 0))
        $tbKimiKey = New-StyledTextBox -X 0 -Y 24 -W 300 -Password $true
        $tbKimiKey.Text = $State.Settings.KimiApiKey
        $kimiPanel.Controls.Add($tbKimiKey)
        $lnkKimi = New-Object System.Windows.Forms.LinkLabel
        $lnkKimi.Text = "platform.moonshot.ai/console/api-keys"
        $lnkKimi.Location = New-Object System.Drawing.Point(0, 58)
        $lnkKimi.Size = New-Object System.Drawing.Size(300, 20)
        $lnkKimi.LinkColor = $AccentColor
        $lnkKimi.Add_LinkClicked({ Start-Process "https://platform.moonshot.ai/console/api-keys" })
        $kimiPanel.Controls.Add($lnkKimi)
        $kimiPanel.Controls.Add((New-StyledLabel -Text "Model" -X 320 -Y 0))
        $comboKimiModel = New-Object System.Windows.Forms.ComboBox
        $comboKimiModel.Location = New-Object System.Drawing.Point(320, 24)
        $comboKimiModel.Size = New-Object System.Drawing.Size(300, 26)
        $comboKimiModel.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
        $comboKimiModel.Font = $FontRegular
        [void]$comboKimiModel.Items.AddRange(@("kimi-k2.5", "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k", "kimi-k2.6"))
        $comboKimiModel.Text = if ($State.Settings.KimiModelId) { $State.Settings.KimiModelId } else { "kimi-k2.5" }
        $kimiPanel.Controls.Add($comboKimiModel)
        Add-AiTestConnectionRow -Panel $kimiPanel -Y 90 -BackendId "kimi" `
            -GetCredentials { @{ api_key = $tbKimiKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $comboKimiModel.Text.Trim() }.GetNewClosure()
        $tbKimiKey.Add_Leave({
            $apiKey = $tbKimiKey.Text.Trim()
            if (-not $apiKey) { return }
            $token = Get-OrCreateWizardSession
            if (-not $token) { return }
            try {
                $body = @{ credentials = @{ api_key = $apiKey } } | ConvertTo-Json
                $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/kimi/models" `
                    -Method Post -Body $body -ContentType "application/json" `
                    -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                if ($resp.models -and $resp.models.Count -gt 0) {
                    $current = $comboKimiModel.Text
                    $comboKimiModel.Items.Clear()
                    [void]$comboKimiModel.Items.AddRange(@($resp.models))
                    $comboKimiModel.Text = if ($current) { $current } else { $resp.default }
                }
            } catch {
                # Silent -- convenience refresh only, Test Connection reports real errors.
            }
        }.GetNewClosure())

        # DeepSeek -- api.deepseek.com.
        $deepseekPanel = New-Object System.Windows.Forms.Panel
        $deepseekPanel.Location = New-Object System.Drawing.Point(0, 160)
        $deepseekPanel.Size = New-Object System.Drawing.Size(640, 140)
        $deepseekPanel.Controls.Add((New-StyledLabel -Text "DeepSeek API Key" -X 0 -Y 0))
        $tbDeepSeekKey = New-StyledTextBox -X 0 -Y 24 -W 300 -Password $true
        $tbDeepSeekKey.Text = $State.Settings.DeepSeekApiKey
        $deepseekPanel.Controls.Add($tbDeepSeekKey)
        $lnkDeepSeek = New-Object System.Windows.Forms.LinkLabel
        $lnkDeepSeek.Text = "platform.deepseek.com/api_keys"
        $lnkDeepSeek.Location = New-Object System.Drawing.Point(0, 58)
        $lnkDeepSeek.Size = New-Object System.Drawing.Size(300, 20)
        $lnkDeepSeek.LinkColor = $AccentColor
        $lnkDeepSeek.Add_LinkClicked({ Start-Process "https://platform.deepseek.com/api_keys" })
        $deepseekPanel.Controls.Add($lnkDeepSeek)
        $deepseekPanel.Controls.Add((New-StyledLabel -Text "Model" -X 320 -Y 0))
        $comboDeepSeekModel = New-Object System.Windows.Forms.ComboBox
        $comboDeepSeekModel.Location = New-Object System.Drawing.Point(320, 24)
        $comboDeepSeekModel.Size = New-Object System.Drawing.Size(300, 26)
        $comboDeepSeekModel.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
        $comboDeepSeekModel.Font = $FontRegular
        [void]$comboDeepSeekModel.Items.AddRange(@("deepseek-v4-flash", "deepseek-v4-pro"))
        $comboDeepSeekModel.Text = if ($State.Settings.DeepSeekModelId) { $State.Settings.DeepSeekModelId } else { "deepseek-v4-flash" }
        $deepseekPanel.Controls.Add($comboDeepSeekModel)
        Add-AiTestConnectionRow -Panel $deepseekPanel -Y 90 -BackendId "deepseek" `
            -GetCredentials { @{ api_key = $tbDeepSeekKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $comboDeepSeekModel.Text.Trim() }.GetNewClosure()
        $tbDeepSeekKey.Add_Leave({
            $apiKey = $tbDeepSeekKey.Text.Trim()
            if (-not $apiKey) { return }
            $token = Get-OrCreateWizardSession
            if (-not $token) { return }
            try {
                $body = @{ credentials = @{ api_key = $apiKey } } | ConvertTo-Json
                $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/deepseek/models" `
                    -Method Post -Body $body -ContentType "application/json" `
                    -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                if ($resp.models -and $resp.models.Count -gt 0) {
                    $current = $comboDeepSeekModel.Text
                    $comboDeepSeekModel.Items.Clear()
                    [void]$comboDeepSeekModel.Items.AddRange(@($resp.models))
                    $comboDeepSeekModel.Text = if ($current) { $current } else { $resp.default }
                }
            } catch {
                # Silent -- convenience refresh only, Test Connection reports real errors.
            }
        }.GetNewClosure())

        # xAI (Grok) -- api.x.ai. Not to be confused with Groq (api.groq.com).
        $xaiPanel = New-Object System.Windows.Forms.Panel
        $xaiPanel.Location = New-Object System.Drawing.Point(0, 160)
        $xaiPanel.Size = New-Object System.Drawing.Size(640, 140)
        $xaiPanel.Controls.Add((New-StyledLabel -Text "xAI (Grok) API Key" -X 0 -Y 0))
        $tbXaiKey = New-StyledTextBox -X 0 -Y 24 -W 300 -Password $true
        $tbXaiKey.Text = $State.Settings.XaiApiKey
        $xaiPanel.Controls.Add($tbXaiKey)
        $lnkXai = New-Object System.Windows.Forms.LinkLabel
        $lnkXai.Text = "console.x.ai"
        $lnkXai.Location = New-Object System.Drawing.Point(0, 58)
        $lnkXai.Size = New-Object System.Drawing.Size(300, 20)
        $lnkXai.LinkColor = $AccentColor
        $lnkXai.Add_LinkClicked({ Start-Process "https://console.x.ai" })
        $xaiPanel.Controls.Add($lnkXai)
        $xaiPanel.Controls.Add((New-StyledLabel -Text "Model" -X 320 -Y 0))
        $comboXaiModel = New-Object System.Windows.Forms.ComboBox
        $comboXaiModel.Location = New-Object System.Drawing.Point(320, 24)
        $comboXaiModel.Size = New-Object System.Drawing.Size(300, 26)
        $comboXaiModel.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
        $comboXaiModel.Font = $FontRegular
        [void]$comboXaiModel.Items.AddRange(@("grok-4.6", "grok-4.5", "grok-4.3", "grok-code-fast-1"))
        $comboXaiModel.Text = if ($State.Settings.XaiModelId) { $State.Settings.XaiModelId } else { "grok-4.6" }
        $xaiPanel.Controls.Add($comboXaiModel)
        Add-AiTestConnectionRow -Panel $xaiPanel -Y 90 -BackendId "xai" `
            -GetCredentials { @{ api_key = $tbXaiKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $comboXaiModel.Text.Trim() }.GetNewClosure()
        $tbXaiKey.Add_Leave({
            $apiKey = $tbXaiKey.Text.Trim()
            if (-not $apiKey) { return }
            $token = Get-OrCreateWizardSession
            if (-not $token) { return }
            try {
                $body = @{ credentials = @{ api_key = $apiKey } } | ConvertTo-Json
                $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/xai/models" `
                    -Method Post -Body $body -ContentType "application/json" `
                    -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                if ($resp.models -and $resp.models.Count -gt 0) {
                    $current = $comboXaiModel.Text
                    $comboXaiModel.Items.Clear()
                    [void]$comboXaiModel.Items.AddRange(@($resp.models))
                    $comboXaiModel.Text = if ($current) { $current } else { $resp.default }
                }
            } catch {
                # Silent -- convenience refresh only, Test Connection reports real errors.
            }
        }.GetNewClosure())

        # Mistral AI -- api.mistral.ai.
        $mistralPanel = New-Object System.Windows.Forms.Panel
        $mistralPanel.Location = New-Object System.Drawing.Point(0, 160)
        $mistralPanel.Size = New-Object System.Drawing.Size(640, 140)
        $mistralPanel.Controls.Add((New-StyledLabel -Text "Mistral API Key" -X 0 -Y 0))
        $tbMistralKey = New-StyledTextBox -X 0 -Y 24 -W 300 -Password $true
        $tbMistralKey.Text = $State.Settings.MistralApiKey
        $mistralPanel.Controls.Add($tbMistralKey)
        $lnkMistral = New-Object System.Windows.Forms.LinkLabel
        $lnkMistral.Text = "console.mistral.ai/api-keys"
        $lnkMistral.Location = New-Object System.Drawing.Point(0, 58)
        $lnkMistral.Size = New-Object System.Drawing.Size(300, 20)
        $lnkMistral.LinkColor = $AccentColor
        $lnkMistral.Add_LinkClicked({ Start-Process "https://console.mistral.ai/api-keys" })
        $mistralPanel.Controls.Add($lnkMistral)
        $mistralPanel.Controls.Add((New-StyledLabel -Text "Model" -X 320 -Y 0))
        $comboMistralModel = New-Object System.Windows.Forms.ComboBox
        $comboMistralModel.Location = New-Object System.Drawing.Point(320, 24)
        $comboMistralModel.Size = New-Object System.Drawing.Size(300, 26)
        $comboMistralModel.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
        $comboMistralModel.Font = $FontRegular
        [void]$comboMistralModel.Items.AddRange(@("mistral-small-2506", "mistral-large-2411", "mistral-medium-2508", "codestral-2501"))
        $comboMistralModel.Text = if ($State.Settings.MistralModelId) { $State.Settings.MistralModelId } else { "mistral-small-2506" }
        $mistralPanel.Controls.Add($comboMistralModel)
        Add-AiTestConnectionRow -Panel $mistralPanel -Y 90 -BackendId "mistral" `
            -GetCredentials { @{ api_key = $tbMistralKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $comboMistralModel.Text.Trim() }.GetNewClosure()
        $tbMistralKey.Add_Leave({
            $apiKey = $tbMistralKey.Text.Trim()
            if (-not $apiKey) { return }
            $token = Get-OrCreateWizardSession
            if (-not $token) { return }
            try {
                $body = @{ credentials = @{ api_key = $apiKey } } | ConvertTo-Json
                $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/mistral/models" `
                    -Method Post -Body $body -ContentType "application/json" `
                    -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                if ($resp.models -and $resp.models.Count -gt 0) {
                    $current = $comboMistralModel.Text
                    $comboMistralModel.Items.Clear()
                    [void]$comboMistralModel.Items.AddRange(@($resp.models))
                    $comboMistralModel.Text = if ($current) { $current } else { $resp.default }
                }
            } catch {
                # Silent -- convenience refresh only, Test Connection reports real errors.
            }
        }.GetNewClosure())

        # OpenRouter -- openrouter.ai, a meta-router across many underlying
        # model providers. Model field defaults to a well-known stable id;
        # the live refresh below filters to models that actually support
        # tool_choice (see app/ai/openrouter_client.py's list_models()).
        $openrouterPanel = New-Object System.Windows.Forms.Panel
        $openrouterPanel.Location = New-Object System.Drawing.Point(0, 160)
        $openrouterPanel.Size = New-Object System.Drawing.Size(640, 140)
        $openrouterPanel.Controls.Add((New-StyledLabel -Text "OpenRouter API Key" -X 0 -Y 0))
        $tbOpenRouterKey = New-StyledTextBox -X 0 -Y 24 -W 300 -Password $true
        $tbOpenRouterKey.Text = $State.Settings.OpenRouterApiKey
        $openrouterPanel.Controls.Add($tbOpenRouterKey)
        $lnkOpenRouter = New-Object System.Windows.Forms.LinkLabel
        $lnkOpenRouter.Text = "openrouter.ai/keys"
        $lnkOpenRouter.Location = New-Object System.Drawing.Point(0, 58)
        $lnkOpenRouter.Size = New-Object System.Drawing.Size(300, 20)
        $lnkOpenRouter.LinkColor = $AccentColor
        $lnkOpenRouter.Add_LinkClicked({ Start-Process "https://openrouter.ai/keys" })
        $openrouterPanel.Controls.Add($lnkOpenRouter)
        $openrouterPanel.Controls.Add((New-StyledLabel -Text "Model" -X 320 -Y 0))
        $comboOpenRouterModel = New-Object System.Windows.Forms.ComboBox
        $comboOpenRouterModel.Location = New-Object System.Drawing.Point(320, 24)
        $comboOpenRouterModel.Size = New-Object System.Drawing.Size(300, 26)
        $comboOpenRouterModel.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDown
        $comboOpenRouterModel.Font = $FontRegular
        [void]$comboOpenRouterModel.Items.AddRange(@("openai/gpt-4o", "anthropic/claude-sonnet-4.5", "google/gemini-2.5-pro", "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct"))
        $comboOpenRouterModel.Text = if ($State.Settings.OpenRouterModelId) { $State.Settings.OpenRouterModelId } else { "openai/gpt-4o" }
        $openrouterPanel.Controls.Add($comboOpenRouterModel)
        Add-AiTestConnectionRow -Panel $openrouterPanel -Y 90 -BackendId "openrouter" `
            -GetCredentials { @{ api_key = $tbOpenRouterKey.Text.Trim() } }.GetNewClosure() `
            -GetModel { $comboOpenRouterModel.Text.Trim() }.GetNewClosure()
        $tbOpenRouterKey.Add_Leave({
            $apiKey = $tbOpenRouterKey.Text.Trim()
            if (-not $apiKey) { return }
            $token = Get-OrCreateWizardSession
            if (-not $token) { return }
            try {
                $body = @{ credentials = @{ api_key = $apiKey } } | ConvertTo-Json
                $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/openrouter/models" `
                    -Method Post -Body $body -ContentType "application/json" `
                    -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
                if ($resp.models -and $resp.models.Count -gt 0) {
                    $current = $comboOpenRouterModel.Text
                    $comboOpenRouterModel.Items.Clear()
                    [void]$comboOpenRouterModel.Items.AddRange(@($resp.models))
                    $comboOpenRouterModel.Text = if ($current) { $current } else { $resp.default }
                }
            } catch {
                # Silent -- convenience refresh only, Test Connection reports real errors.
            }
        }.GetNewClosure())

        $allPanels = @($ollamaPanel, $anthropicPanel, $bedrockPanel, $geminiPanel, $groqPanel, $openaiPanel, $kimiPanel, $deepseekPanel, $xaiPanel, $mistralPanel, $openrouterPanel)
        foreach ($sub in $allPanels) { $p.Controls.Add($sub); $sub.Visible = $false }
        $allPanels[$combo.SelectedIndex].Visible = $true

        $combo.Add_SelectedIndexChanged({
            foreach ($sub in $allPanels) { $sub.Visible = $false }
            $allPanels[$combo.SelectedIndex].Visible = $true
        })

        $p.Tag = @{
            Combo = $combo; BackendMap = $backendMap
            OllamaModel = $tbOllamaModel; AnthropicKey = $tbAnthropicKey
            BedrockKey = $tbBedrockKey; BedrockRegion = $tbBedrockRegion; GeminiKey = $tbGeminiKey
            GroqKey = $tbGroqKey; GroqModel = $comboGroqModel
            OpenAiKey = $tbOpenAiKey; OpenAiModel = $comboOpenAiModel
            KimiKey = $tbKimiKey; KimiModel = $comboKimiModel
            DeepSeekKey = $tbDeepSeekKey; DeepSeekModel = $comboDeepSeekModel
            XaiKey = $tbXaiKey; XaiModel = $comboXaiModel
            MistralKey = $tbMistralKey; MistralModel = $comboMistralModel
            OpenRouterKey = $tbOpenRouterKey; OpenRouterModel = $comboOpenRouterModel
        }
        $script:AiPagePanel = $p
        return $p
    }
    Validate = {
        $t = $script:AiPagePanel.Tag
        $selectedBackend = $t.BackendMap[$t.Combo.SelectedIndex]

        # Blocks Next only when a live test for the CURRENT settings of the
        # SELECTED backend already ran and failed -- never blocks on
        # "never tested" (a fresh install has no backend running yet to
        # test against). See $script:AiTestState's declaration for the full
        # rationale.
        $getters = $script:AiGetters[$selectedBackend]
        if ($getters) {
            $currentSignature = @{
                backend = $selectedBackend
                credentials = (& $getters.Creds)
                model = (& $getters.Model)
            } | ConvertTo-Json -Compress
            $lastResult = $script:AiTestState[$selectedBackend]
            if ($lastResult -and $lastResult.Signature -eq $currentSignature -and -not $lastResult.Ok) {
                [System.Windows.Forms.MessageBox]::Show(
                    "The last connection test for '$selectedBackend' failed with these exact settings. Fix the settings and click 'Test Connection' again before continuing, or change a value.",
                    "AI Configuration",
                    [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                ) | Out-Null
                return $false
            }
        }

        $State.Settings.AiBackend = $selectedBackend
        $State.Settings.OllamaModel = $t.OllamaModel.Text.Trim()
        $State.Settings.AnthropicApiKey = $t.AnthropicKey.Text.Trim()
        $State.Settings.BedrockApiKey = $t.BedrockKey.Text.Trim()
        $State.Settings.AwsRegion = $t.BedrockRegion.Text.Trim()
        $State.Settings.GeminiApiKey = $t.GeminiKey.Text.Trim()
        $State.Settings.GroqApiKey = $t.GroqKey.Text.Trim()
        $State.Settings.GroqModelId = $t.GroqModel.Text.Trim()
        $State.Settings.OpenAiApiKey = $t.OpenAiKey.Text.Trim()
        $State.Settings.OpenAiModelId = $t.OpenAiModel.Text.Trim()
        $State.Settings.KimiApiKey = $t.KimiKey.Text.Trim()
        $State.Settings.KimiModelId = $t.KimiModel.Text.Trim()
        $State.Settings.DeepSeekApiKey = $t.DeepSeekKey.Text.Trim()
        $State.Settings.DeepSeekModelId = $t.DeepSeekModel.Text.Trim()
        $State.Settings.XaiApiKey = $t.XaiKey.Text.Trim()
        $State.Settings.XaiModelId = $t.XaiModel.Text.Trim()
        $State.Settings.MistralApiKey = $t.MistralKey.Text.Trim()
        $State.Settings.MistralModelId = $t.MistralModel.Text.Trim()
        $State.Settings.OpenRouterApiKey = $t.OpenRouterKey.Text.Trim()
        $State.Settings.OpenRouterModelId = $t.OpenRouterModel.Text.Trim()
        return $true
    }
}

# ---------------------------------------------------------------------------
# Page: Threat Intelligence Providers
# ---------------------------------------------------------------------------
# provider_id => @{ Label, Field ("api_key"|"auth_key"|"censys"), Setting(s), HomeUrl, Note }
$ProviderDefs = [ordered]@{
    virustotal = @{ Label = "VirusTotal"; Field = "api_key"; Setting = "VirusTotalApiKey"; Url = "https://www.virustotal.com"; Note = "Free tier: 4 req/min, 500/day." }
    abuseipdb  = @{ Label = "AbuseIPDB"; Field = "api_key"; Setting = "AbuseIpdbApiKey"; Url = "https://www.abuseipdb.com"; Note = "Free tier: 1,000 checks/day." }
    otx        = @{ Label = "AlienVault OTX"; Field = "api_key"; Setting = "OtxApiKey"; Url = "https://otx.alienvault.com"; Note = "Free account required." }
    abusech    = @{ Label = "abuse.ch (URLhaus / ThreatFox / MalwareBazaar)"; Field = "auth_key"; Setting = "AbuseChAuthKey"; Url = "https://auth.abuse.ch"; Note = "One free Auth-Key covers all three abuse.ch connectors." }
    nvd        = @{ Label = "NIST NVD"; Field = "api_key"; Setting = "NvdApiKey"; Url = "https://nvd.nist.gov/developers/request-an-api-key"; Note = "Optional -- works without a key at a lower rate limit." }
    hybrid_analysis = @{ Label = "Hybrid Analysis"; Field = "api_key"; Setting = "HybridAnalysisApiKey"; Url = "https://www.hybrid-analysis.com"; Note = "Free registered account." }
    censys     = @{ Label = "Censys"; Field = "censys"; Setting = "CensysPersonalAccessToken"; Setting2 = "CensysOrganizationId"; Url = "https://platform.censys.io"; Note = "Requires both a Personal Access Token and an Organization ID." }
    phishtank  = @{ Label = "PhishTank"; Field = "api_key"; Setting = "PhishTankApiKey"; Url = "https://www.phishtank.com"; Note = "No key required -- optional key only raises rate limits." }
}

$Pages += @{
    AllowBack = $true
    Build = {
        $p = New-Object System.Windows.Forms.Panel
        $p.Size = $ContentPanel.Size
        $p.Controls.Add((New-StyledLabel -Text "Threat Intelligence Providers" -X 0 -Y 0 -W 640 -Font $FontHeading))
        # Height=40 -- confirmed via Label.GetPreferredSize (the real WinForms
        # wrapping calculation) that this sentence needs 37px at 640px width,
        # not the default 24px; same visual-overlap bug found and fixed on
        # the Administrator Account page. Scroll panel below shifted from
        # Y=64 to Y=72 (8px gap after the note's new height) and shrunk by
        # the same 8px so the page still fits within the 440px content area
        # instead of overflowing it.
        $p.Controls.Add((New-StyledLabel -Text "All optional. Leave a key blank to skip that provider -- the platform works fine with any subset configured, including none." -X 0 -Y 32 -W 640 -Height 40 -Color $MutedColor))

        $scroll = New-Object System.Windows.Forms.Panel
        $scroll.Location = New-Object System.Drawing.Point(0, 72)
        $scroll.Size = New-Object System.Drawing.Size(660, 362)
        $scroll.AutoScroll = $true
        $p.Controls.Add($scroll)

        $y = 0
        $rowControls = @{}
        foreach ($providerId in $ProviderDefs.Keys) {
            $def = $ProviderDefs[$providerId]
            $card = New-Object System.Windows.Forms.Panel
            $card.Location = New-Object System.Drawing.Point(0, $y)
            # Height=116, not 96 -- confirmed via Label.GetPreferredSize that
            # the Test button's own "Start the platform and create the admin
            # account first..." status message (set below) needs 37px at
            # this label's width, not the ~20px a single line takes. Panel
            # does not clip child controls by default, so at the old height
            # that 2-line message rendered past the card's own bottom edge
            # and into the next provider card in the scrollable list.
            $card.Size = New-Object System.Drawing.Size(630, 116)
            $card.BackColor = $PanelBg

            $card.Controls.Add((New-StyledLabel -Text $def.Label -X 12 -Y 8 -W 400 -Font $FontSubheading))
            $lnk = New-Object System.Windows.Forms.LinkLabel
            $lnk.Text = ($def.Url -replace '^https?://', '')
            $lnk.Location = New-Object System.Drawing.Point(420, 10)
            $lnk.Size = New-Object System.Drawing.Size(190, 20)
            $lnk.LinkColor = $AccentColor
            $lnk.Add_LinkClicked({ Start-Process $def.Url }.GetNewClosure())
            $card.Controls.Add($lnk)

            if ($def.Field -eq "censys") {
                $tbToken = New-StyledTextBox -X 12 -Y 34 -W 300 -Password $true
                $tbToken.Text = $State.Settings.CensysPersonalAccessToken
                $tbToken.Tag = "placeholder:Personal Access Token"
                $card.Controls.Add($tbToken)
                $tbOrg = New-StyledTextBox -X 322 -Y 34 -W 200
                $tbOrg.Text = $State.Settings.CensysOrganizationId
                $card.Controls.Add($tbOrg)
                $card.Controls.Add((New-StyledLabel -Text "Token" -X 12 -Y 60 -W 100 -Color $MutedColor))
                $card.Controls.Add((New-StyledLabel -Text "Organization ID" -X 322 -Y 60 -W 150 -Color $MutedColor))
                $rowControls[$providerId] = @{ Token = $tbToken; Org = $tbOrg }
            } else {
                $tb = New-StyledTextBox -X 12 -Y 34 -W 400 -Password $true
                $tb.Text = $State.Settings[$def.Setting]
                $card.Controls.Add($tb)
                $rowControls[$providerId] = @{ Key = $tb }
            }

            $btnTest = New-StyledButton -Text "Test" -X 528 -Y 33 -W 90 -Primary $false
            $lblStatus = New-StyledLabel -Text $def.Note -X 12 -Y 68 -W 600 -Height 40 -Color $MutedColor
            $card.Controls.Add($lblStatus)
            $card.Controls.Add($btnTest)
            $rowControls[$providerId].Status = $lblStatus
            $rowControls[$providerId].DefaultNote = $def.Note

            $btnTest.Add_Click({
                param($sender, $e)
                $pid0 = $providerId
                $ctrls = $rowControls[$pid0]
                $ctrls.Status.ForeColor = $MutedColor
                $ctrls.Status.Text = "Testing..."
                $Form.Refresh()

                if (-not (Get-OrCreateWizardSession)) {
                    $ctrls.Status.ForeColor = $ErrorColor
                    $ctrls.Status.Text = "Sign-in required to test live: go back to the Administrator Account page and enter your existing email and password (this only signs you in for this session -- it will not change your account), then return here."
                    return
                }

                $creds = @{}
                if ($def.Field -eq "censys") {
                    $creds = @{ personal_access_token = $ctrls.Token.Text.Trim(); organization_id = $ctrls.Org.Text.Trim() }
                } else {
                    $creds = @{ $def.Field = $ctrls.Key.Text.Trim() }
                }
                $body = @{ credentials = $creds } | ConvertTo-Json -Compress
                try {
                    $resp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/providers/$pid0/test" `
                        -Method Post -Body $body -ContentType "application/json" `
                        -Headers @{ Authorization = "Bearer $($State.AccessToken)" } -TimeoutSec 15
                    if ($resp.ok) {
                        $ctrls.Status.ForeColor = $SuccessColor
                        $ctrls.Status.Text = "OK: $($resp.message) ($($resp.latency_ms) ms)"
                        $script:ProviderTestState[$pid0] = @{ Signature = $body; Ok = $true }
                    } else {
                        $ctrls.Status.ForeColor = $ErrorColor
                        $ctrls.Status.Text = "FAILED: $($resp.message)"
                        $script:ProviderTestState[$pid0] = @{ Signature = $body; Ok = $false }
                    }
                } catch {
                    $ctrls.Status.ForeColor = $ErrorColor
                    $ctrls.Status.Text = "FAILED: $(Get-FriendlyHttpError $_)"
                    $script:ProviderTestState[$pid0] = @{ Signature = $body; Ok = $false }
                }
            }.GetNewClosure())

            $scroll.Controls.Add($card)
            $y += 126
        }

        $p.Tag = @{ Rows = $rowControls }
        $script:ProvidersPagePanel = $p
        return $p
    }
    Validate = {
        $rows = $script:ProvidersPagePanel.Tag.Rows
        foreach ($providerId in $ProviderDefs.Keys) {
            $def = $ProviderDefs[$providerId]
            $ctrls = $rows[$providerId]

            # Same "block only on a known-failed test for these exact
            # current values" gate as the AI Configuration page -- see
            # $script:ProviderTestState's declaration for the rationale.
            # Every provider here is optional, so a blank/never-tested
            # field is never blocked, only a field that was actively tested
            # and failed with the value still unchanged.
            if ($def.Field -eq "censys") {
                $currentCreds = @{ personal_access_token = $ctrls.Token.Text.Trim(); organization_id = $ctrls.Org.Text.Trim() }
            } else {
                $currentCreds = @{ $def.Field = $ctrls.Key.Text.Trim() }
            }
            $currentSignature = @{ credentials = $currentCreds } | ConvertTo-Json -Compress
            $lastResult = $script:ProviderTestState[$providerId]
            if ($lastResult -and $lastResult.Signature -eq $currentSignature -and -not $lastResult.Ok) {
                [System.Windows.Forms.MessageBox]::Show(
                    "The last connection test for '$($def.Label)' failed with these exact settings. Fix the value and click 'Test' again before continuing, clear the field to skip this provider, or change the value.",
                    "Threat Intelligence Providers",
                    [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                ) | Out-Null
                return $false
            }

            if ($def.Field -eq "censys") {
                $State.Settings.CensysPersonalAccessToken = $ctrls.Token.Text.Trim()
                $State.Settings.CensysOrganizationId = $ctrls.Org.Text.Trim()
            } else {
                $State.Settings[$def.Setting] = $ctrls.Key.Text.Trim()
            }
        }
        return $true
    }
}

# ---------------------------------------------------------------------------
# Page: Ports
# ---------------------------------------------------------------------------
$Pages += @{
    AllowBack = $true
    Build = {
        $p = New-Object System.Windows.Forms.Panel
        $p.Size = $ContentPanel.Size
        $p.Controls.Add((New-StyledLabel -Text "Network Ports" -X 0 -Y 0 -W 640 -Font $FontHeading))
        # Height=40 for consistency with the same fix elsewhere on this page
        # set -- the first port row (Y=80) already leaves enough real
        # clearance (confirmed via Label.GetPreferredSize: 37px needed) even
        # without this, but sizing the label correctly is still the right
        # fix rather than relying on incidental extra spacing.
        $p.Controls.Add((New-StyledLabel -Text "Each service needs its own port on this machine. Conflicts with something already running are shown below -- pick a different port or accept the suggested free one." -X 0 -Y 32 -W 640 -Height 40 -Color $MutedColor))

        $portFields = [ordered]@{
            PortFrontend = "Web interface"
            PortBackend = "Backend API"
            PortPostgres = "PostgreSQL (internal)"
            PortRedis = "Redis (internal)"
            PortNeo4jHttp = "Neo4j HTTP (internal)"
            PortNeo4jBolt = "Neo4j Bolt (internal)"
            PortOpenSearch = "OpenSearch (internal)"
        }
        $y = 80
        $tbMap = @{}
        foreach ($key in $portFields.Keys) {
            $p.Controls.Add((New-StyledLabel -Text $portFields[$key] -X 0 -Y $y -W 260))
            $tb = New-StyledTextBox -X 280 -Y ($y - 4) -W 100
            $tb.Text = $State.Settings[$key]
            $lblConflict = New-StyledLabel -Text "" -X 400 -Y $y -W 240 -Color $ErrorColor
            if (-not (Test-PortFree -Port $State.Settings[$key])) {
                $free = Find-FreePort -PreferredPort $State.Settings[$key]
                $lblConflict.Text = "In use -- try $free"
            }
            $p.Controls.Add($tb)
            $p.Controls.Add($lblConflict)
            $tbMap[$key] = $tb
            $y += 36
        }
        $lblError = New-StyledLabel -Text "" -X 0 -Y $y -W 600 -Color $ErrorColor
        $p.Controls.Add($lblError)
        $p.Tag = @{ Ports = $tbMap; Error = $lblError }
        $script:PortsPagePanel = $p
        return $p
    }
    Validate = {
        $t = $script:PortsPagePanel.Tag
        $seen = @{}
        foreach ($key in $t.Ports.Keys) {
            $val = 0
            if (-not [int]::TryParse($t.Ports[$key].Text, [ref]$val) -or $val -lt 1024 -or $val -gt 65535) {
                $t.Error.Text = "Enter a valid port number (1024-65535) for every field."
                return $false
            }
            if ($seen.ContainsKey($val)) {
                $t.Error.Text = "Port $val is used more than once -- each service needs a distinct port."
                return $false
            }
            $seen[$val] = $true
            $State.Settings[$key] = $val
        }
        return $true
    }
}

# ---------------------------------------------------------------------------
# Page: Summary + Install
# ---------------------------------------------------------------------------
$Pages += @{
    AllowBack = $true
    Build = {
        $p = New-Object System.Windows.Forms.Panel
        $p.Size = $ContentPanel.Size
        $p.Controls.Add((New-StyledLabel -Text "Ready to Install" -X 0 -Y 0 -W 640 -Font $FontHeading))

        $configuredCount = ($ProviderDefs.Keys | Where-Object {
            $def = $ProviderDefs[$_]
            if ($def.Field -eq "censys") { $State.Settings.CensysPersonalAccessToken -and $State.Settings.CensysOrganizationId }
            else { $State.Settings[$def.Setting] }
        }).Count

        # LAN IP isn't written to $State.Settings until Start Installation
        # runs (below) -- this is a second, independent, read-only preview
        # call, same pattern as this page's own live Test-PortFree check.
        $lanPreview = Get-LanIpAddress
        $lanLine = if ($lanPreview) {
            "LAN (other devices): http://$($lanPreview):$($State.Settings.PortFrontend)"
        } else {
            "LAN (other devices): not detected -- will still work from this computer"
        }
        $summaryText = @(
            "Administrator:  $(if ($State.AdminEmail) { $State.AdminEmail } else { '(keeping existing account)' })"
            "AI Backend:     $($State.Settings.AiBackend)"
            "Providers configured: $configuredCount of $($ProviderDefs.Count)"
            "Web interface:  http://localhost:$($State.Settings.PortFrontend)"
            "Backend API:    http://localhost:$($State.Settings.PortBackend)"
            $lanLine
        ) -join "`r`n"
        $lblSummary = New-StyledLabel -Text $summaryText -X 0 -Y 50 -W 640 -Color $TextColor
        $lblSummary.Size = New-Object System.Drawing.Size(640, 140)
        $p.Controls.Add($lblSummary)

        $progressList = New-Object System.Windows.Forms.ListBox
        $progressList.Location = New-Object System.Drawing.Point(0, 210)
        $progressList.Size = New-Object System.Drawing.Size(640, 180)
        $progressList.BackColor = $PanelBg
        $progressList.ForeColor = $TextColor
        $progressList.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
        $progressList.Font = New-Object System.Drawing.Font("Consolas", 9)
        $p.Controls.Add($progressList)

        $btnInstall = New-StyledButton -Text "Start Installation" -X 0 -Y 400 -W 200 -Primary $true
        $p.Controls.Add($btnInstall)

        $addLine = {
            param($text)
            $progressList.Items.Add($text)
            $progressList.TopIndex = $progressList.Items.Count - 1
            $Form.Refresh()
        }.GetNewClosure()

        # $script:-scoped variables do not resolve inside a .GetNewClosure()
        # scriptblock when that scriptblock is itself defined inside another
        # invoked scriptblock (this page's own Build block) -- confirmed by
        # isolated repro. Capture everything the click handler needs as plain
        # locals here instead; plain lexical captures work fine through
        # GetNewClosure (see $addLine above, and $btnTest's closure elsewhere
        # on this page).
        $appRepoDir = $script:AppRepoDir
        $envFilePath = $script:EnvFilePath
        $logsDir = $script:LogsDir
        $setupCompleteMarker = $script:SetupCompleteMarker
        $backupScriptPath = Join-Path $ScriptsDir "Backup-Database.ps1"

        $btnInstall.Add_Click({
            $btnInstall.Enabled = $false
            $NextButton.Enabled = $false
            $BackButton.Enabled = $false

            # Everything below runs inside a WinForms button-click event handler --
            # an uncaught exception here does not crash the process or print
            # anywhere visible, it just silently aborts the handler and leaves the
            # UI stuck with no explanation. Every failure path must go through
            # $addLine so the administrator always sees what happened.
            try {
                if (-not (Test-Path $appRepoDir)) {
                    & $addLine "ERROR: Application files not found at $appRepoDir -- the installer did not copy them correctly. Try reinstalling."
                    Write-SetupLog "AppRepoDir missing: $appRepoDir" "ERROR"
                    $btnInstall.Enabled = $true
                    $BackButton.Enabled = $true
                    return
                }

                if ($State.IsUpgrade) {
                    & $addLine "Backing up the database before upgrading..."
                    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $backupScriptPath -Quiet
                    # Confirmed live: this used to unconditionally print "Backup
                    # complete." even when Backup-Database.ps1 silently skipped
                    # (e.g. no postgres container running yet, which is the
                    # normal case on a retry after a first attempt failed before
                    # ever starting containers) -- giving false confidence that
                    # a real snapshot was taken when none was. Reflect what
                    # actually happened via the real exit code instead.
                    if ($LASTEXITCODE -eq 0) {
                        & $addLine "Backup step finished (see the Backups folder, or the Diagnostics bundle, if you need to confirm a snapshot was actually taken)."
                    } else {
                        & $addLine "WARNING: Database backup failed (exit code $LASTEXITCODE) -- continuing with the upgrade anyway. See $script:SetupLogPath for details."
                        Write-SetupLog "Pre-upgrade backup failed with exit code $LASTEXITCODE" "WARN"
                    }
                }

                & $addLine "Detecting LAN address for display purposes..."
                $lanIp = Get-LanIpAddress
                if ($lanIp) {
                    $State.Settings.DetectedLanIp = $lanIp
                    & $addLine "Detected LAN address: $lanIp"
                } else {
                    & $addLine "Could not detect a LAN address automatically -- local access still works; re-run Configuration later if needed."
                    Write-SetupLog "Get-LanIpAddress returned no candidate." "WARN"
                }

                & $addLine "Writing configuration..."
                Initialize-DataDirectories
                Write-PlatformEnvFile -Settings $State.Settings -Path $envFilePath
                Write-SetupLog "Wrote .env to $envFilePath"
                & $addLine "Configuration written to $envFilePath"

                # Real bug this prevents: a fresh install (no existing .env to
                # recover a real password from) always generates a BRAND-NEW
                # random database password -- if a Postgres volume from an
                # earlier, abandoned install attempt is still on this machine,
                # that new password will never match what's already baked
                # into it, and the backend crash-loops on a Postgres auth
                # error the instant it starts. See Common.ps1's
                # Remove-StaleDatabaseVolumeIfFreshInstall for the full
                # rationale. Only runs on a genuinely fresh install --
                # $State.IsUpgrade already correctly reused the real existing
                # password above, so this must never touch that case.
                if (-not $State.IsUpgrade) {
                    Remove-StaleDatabaseVolumeIfFreshInstall -IsFreshInstall $true
                }

                & $addLine "Configuring Windows Firewall (Private networks only)..."
                try {
                    New-AppFirewallRule -FrontendPort $State.Settings.PortFrontend -BackendPort $State.Settings.PortBackend
                    & $addLine "Firewall rule created for ports $($State.Settings.PortFrontend), $($State.Settings.PortBackend)."
                } catch {
                    & $addLine "WARNING: Could not create the firewall rule automatically -- LAN access may need manual firewall configuration. $($_.Exception.Message)"
                    Write-SetupLog "New-AppFirewallRule failed: $_" "WARN"
                }

                & $addLine "Starting Docker containers (this can take several minutes on first run while images build)..."
                $exitCode = Invoke-DockerCompose "up" "-d" "--build"
                if ($exitCode -ne 0) {
                    & $addLine "ERROR: docker compose exited with code $exitCode -- see $logsDir for details."
                    Write-SetupLog "docker compose up failed with exit code $exitCode" "ERROR"
                    $btnInstall.Enabled = $true
                    $BackButton.Enabled = $true
                    return
                }
                & $addLine "Containers started."

                & $addLine "Waiting for the backend to become healthy..."
                $healthy = $false
                for ($i = 0; $i -lt 60; $i++) {
                    if (Test-BackendHealth -BaseUrl "http://localhost:$($State.Settings.PortBackend)") { $healthy = $true; break }
                    Start-Sleep -Seconds 3
                }
                if (-not $healthy) {
                    & $addLine "ERROR: Backend did not become healthy within 3 minutes. Check Docker Desktop and try again, or view logs from the Start Menu."
                    Write-SetupLog "Backend health check timed out" "ERROR"
                    $btnInstall.Enabled = $true
                    $BackButton.Enabled = $true
                    return
                }
                & $addLine "Backend is healthy."

                & $addLine "Registering automatic startup and health-watchdog tasks..."
                try {
                    Register-BootAndWatchdogTasks -ScriptsDir $ScriptsDir
                    & $addLine "The platform will now start automatically after a reboot, and self-restart if it becomes unhealthy."
                } catch {
                    & $addLine "WARNING: Could not register the startup/watchdog Scheduled Tasks -- the platform will need to be started manually (Start Menu -> Start Platform) after a reboot. $($_.Exception.Message)"
                    Write-SetupLog "Register-BootAndWatchdogTasks failed: $_" "WARN"
                }

                if ($State.AdminEmail -and $State.AdminPassword) {
                    & $addLine "Creating administrator account..."
                    try {
                        $regBody = @{ email = $State.AdminEmail; password = $State.AdminPassword; full_name = $State.AdminFullName } | ConvertTo-Json
                        $null = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/auth/register" `
                            -Method Post -Body $regBody -ContentType "application/json" -TimeoutSec 15
                        & $addLine "Administrator account created: $($State.AdminEmail)"

                        $loginBody = @{ email = $State.AdminEmail; password = $State.AdminPassword } | ConvertTo-Json
                        $loginResp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/auth/login" `
                            -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 15
                        $State.AccessToken = $loginResp.access_token
                        & $addLine "Signed in."
                    } catch {
                        $errBody = $_.ErrorDetails.Message
                        if ($errBody -match "already registered") {
                            & $addLine "That email is already registered -- signing in instead."
                            try {
                                $loginBody = @{ email = $State.AdminEmail; password = $State.AdminPassword } | ConvertTo-Json
                                $loginResp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/auth/login" `
                                    -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 15
                                $State.AccessToken = $loginResp.access_token
                                & $addLine "Signed in."
                            } catch {
                                & $addLine "Could not sign in with those credentials -- you can sign in manually once the platform opens."
                            }
                        } else {
                            # $errBody here is the raw FastAPI/Pydantic error JSON, e.g.
                            # {"detail":[{"type":"value_error",...,"msg":"value is not a
                            # valid email address: ..."}]} -- confirmed live that dumping
                            # this straight to the progress log is unreadable to an
                            # administrator. Pull out the human-readable "msg" field(s)
                            # when present and fall back to the raw body otherwise.
                            $friendlyMsg = $errBody
                            try {
                                $parsed = $errBody | ConvertFrom-Json
                                if ($parsed.detail -is [array]) {
                                    $friendlyMsg = ($parsed.detail | ForEach-Object { $_.msg }) -join "; "
                                } elseif ($parsed.detail) {
                                    $friendlyMsg = $parsed.detail
                                }
                            } catch {
                                # Not JSON (e.g. connection-level failure) -- use $errBody as-is.
                            }
                            & $addLine "Account creation failed: $friendlyMsg"
                            & $addLine "Setup finished, but no administrator account exists yet -- fix the email/password above (Back) and click Start Installation again, or register one manually once the platform opens."
                            Write-SetupLog "Account creation failed: $_" "ERROR"
                            $BackButton.Enabled = $true
                        }
                    }
                } else {
                    & $addLine "Setup complete."
                }

                # Real gap fixed: this wizard could reach "Setup complete"
                # with an AI backend configuration that was never actually
                # validated against the now-running backend -- on a FRESH
                # install, the AI Configuration page's own Test Connection
                # button cannot work yet (no backend to test against at that
                # point), so a bad base_url/API key/model id previously went
                # straight into .env with zero validation of any kind,
                # directly contradicting "must not save obviously invalid
                # config as valid." Now that the backend is confirmed
                # healthy and (if requested) an admin session exists, run
                # the exact same real connectivity test the AI Configuration
                # page's own button runs, and report the honest result --
                # never silently assume success, but also never block
                # "Setup complete" on it (a downed/not-yet-started local
                # Ollama at install time is common and recoverable; the
                # platform's own AI-resilience design already tolerates a
                # missing AI backend at investigation time).
                if ($State.AccessToken) {
                    & $addLine "Validating the configured AI backend ($($State.Settings.AiBackend))..."
                    try {
                        $aiGetters = $script:AiGetters[$State.Settings.AiBackend]
                        $aiCreds = if ($aiGetters) { & $aiGetters.Creds } else { @{} }
                        $aiModel = if ($aiGetters) { & $aiGetters.Model } else { $null }
                        $aiTestBody = @{ backend = $State.Settings.AiBackend; credentials = $aiCreds; model = $aiModel } | ConvertTo-Json -Compress
                        $aiTestResp = Invoke-RestMethod -Uri "http://localhost:$($State.Settings.PortBackend)/api/v1/ai/test" `
                            -Method Post -Body $aiTestBody -ContentType "application/json" `
                            -Headers @{ Authorization = "Bearer $($State.AccessToken)" } -TimeoutSec 30
                        if ($aiTestResp.ok) {
                            & $addLine "AI backend OK: $($aiTestResp.message) (model: $($aiTestResp.model), $($aiTestResp.latency_ms) ms)"
                        } else {
                            & $addLine "WARNING: the configured AI backend ('$($State.Settings.AiBackend)') failed a connectivity test: $($aiTestResp.message). Investigations will still run, but AI-generated summaries/assessments will fail until this is fixed (Start Menu -> Configuration -> AI Configuration)."
                            Write-SetupLog "Post-install AI connectivity test failed: $($aiTestResp.message)" "WARN"
                        }
                    } catch {
                        & $addLine "WARNING: could not reach the AI backend to validate it ($(Get-FriendlyHttpError $_)). Investigations will still run, but AI-generated summaries/assessments will fail until this is fixed (Start Menu -> Configuration -> AI Configuration)."
                        Write-SetupLog "Post-install AI connectivity test errored: $_" "WARN"
                    }
                } else {
                    & $addLine "Skipped AI backend validation (not signed in) -- verify it from Start Menu -> Configuration -> AI Configuration once you have signed in."
                }

                New-Item -ItemType File -Path $setupCompleteMarker -Force | Out-Null
                $State.SetupSucceeded = $true
                $NextButton.Enabled = $true
            } catch {
                & $addLine "ERROR: Setup failed unexpectedly -- $($_.Exception.Message)"
                Write-SetupLog "Unhandled exception in install handler: $_" "ERROR"
                $btnInstall.Enabled = $true
                $BackButton.Enabled = $true
            }
        }.GetNewClosure())

        $script:SummaryPagePanel = $p
        return $p
    }
    Validate = {
        if (-not $State.SetupSucceeded) {
            [System.Windows.Forms.MessageBox]::Show("Click 'Start Installation' first.", "Setup", "OK", "Warning") | Out-Null
            return $false
        }
        return $true
    }
}

# ---------------------------------------------------------------------------
# Page: Finish
# ---------------------------------------------------------------------------
$Pages += @{
    AllowBack = $false
    Build = {
        $p = New-Object System.Windows.Forms.Panel
        $p.Size = $ContentPanel.Size
        $p.Controls.Add((New-StyledLabel -Text "Setup Complete" -X 0 -Y 0 -W 640 -Font $FontHeading -Color $SuccessColor))
        $p.Controls.Add((New-StyledLabel -Text "HORIZON GRID is running at:" -X 0 -Y 50 -W 640))
        $lnkOpen = New-Object System.Windows.Forms.LinkLabel
        $lnkOpen.Text = "http://localhost:$($State.Settings.PortFrontend)"
        $lnkOpen.Location = New-Object System.Drawing.Point(0, 80)
        $lnkOpen.Size = New-Object System.Drawing.Size(400, 26)
        $lnkOpen.Font = New-Object System.Drawing.Font("Segoe UI", 12)
        $lnkOpen.LinkColor = $AccentColor
        $lnkOpen.Add_LinkClicked({ Start-Process "http://localhost:$($State.Settings.PortFrontend)" })
        $p.Controls.Add($lnkOpen)

        if ($State.Settings.DetectedLanIp) {
            $p.Controls.Add((New-StyledLabel -Text "From another device on this network (detected during setup):" -X 0 -Y 120 -W 640 -Color $MutedColor))
            $lnkLan = New-Object System.Windows.Forms.LinkLabel
            $lnkLan.Text = "http://$($State.Settings.DetectedLanIp):$($State.Settings.PortFrontend)"
            $lnkLan.Location = New-Object System.Drawing.Point(0, 145)
            $lnkLan.Size = New-Object System.Drawing.Size(400, 26)
            $lnkLan.Font = New-Object System.Drawing.Font("Segoe UI", 12)
            $lnkLan.LinkColor = $AccentColor
            $lnkLan.Add_LinkClicked({ Start-Process "http://$($State.Settings.DetectedLanIp):$($State.Settings.PortFrontend)" }.GetNewClosure())
            $p.Controls.Add($lnkLan)
            $chkY = 190
        } else {
            $p.Controls.Add((New-StyledLabel -Text "Could not detect a LAN address for another device to use -- re-run Configuration if your network changes." -X 0 -Y 120 -W 640 -Height 40 -Color $MutedColor))
            $chkY = 170
        }

        $chk = New-Object System.Windows.Forms.CheckBox
        $chk.Text = "Open the platform now"
        $chk.Location = New-Object System.Drawing.Point(0, $chkY)
        $chk.Size = New-Object System.Drawing.Size(300, 26)
        $chk.ForeColor = $TextColor
        $chk.Checked = $true
        $p.Controls.Add($chk)
        $script:OpenOnFinishCheckbox = $chk

        return $p
    }
}

Show-Page -Index 0

[void]$Form.ShowDialog()

if ($script:OpenOnFinishCheckbox -and $script:OpenOnFinishCheckbox.Checked) {
    Start-Process "http://localhost:$($State.Settings.PortFrontend)"
}
