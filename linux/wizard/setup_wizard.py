#!/usr/bin/env python3
"""HORIZON GRID -- Linux setup wizard.

Mirrors windows/wizard/Setup-Wizard.ps1's real flow, translated from a
WinForms GUI to a terminal wizard (this is what "the CLI wizard replacing the
WinForms wizard" means concretely): the same steps, in the same order, doing
the same real HTTP calls against the same real backend endpoints, writing the
same .env layout Write-EnvFile.ps1 writes -- so an install produced by this
wizard is configuration-for-configuration identical to one produced by the
Windows wizard, modulo OS-specific paths.

    Welcome -> Admin Account -> AI Configuration -> Provider Configuration
        -> Port Review -> Summary -> Install/Start -> Health Check -> Finish

Every "Test Connection" prompt makes a real HTTP call to the platform's own
POST /api/v1/providers/{id}/test or POST /api/v1/ai/test endpoint. Exactly
like the Windows wizard, this only works once the backend is actually
running with a session to test with -- on a FRESH install there is no
backend running yet at this point in the flow (ports/secrets are collected
and written, THEN docker compose starts, THEN provider testing and admin-
account creation happen against the real running backend); on a
reconfigure of an EXISTING install, the backend is already up, so entering
the current admin email/password enables live testing immediately. This is
not a Linux limitation -- it is how the application itself works, identical
on Windows.

Usage:
    sudo ./setup_wizard.py                        # interactive
    sudo ./setup_wizard.py --non-interactive \\
        --answers-file answers.json               # scripted (CI/test use)
    sudo ./setup_wizard.py --dry-run ...           # collect + write .env,
                                                    # skip docker compose up
"""
import argparse
import base64
import getpass
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "scripts"))

# Defaults to "localhost", which is correct for a real install -- this
# wizard always runs on the same host as the containers it configures. Only
# the automated Docker-sibling-container test harness overrides this (to
# host.docker.internal), since in that rig `docker compose up` talks to the
# OUTER Docker host's daemon, so the containers it starts are published on
# that outer host, not inside this wizard's own container network namespace.
# See the Linux QA report's "Test Environment" section for the full story.
BACKEND_HOST = os.environ.get("HORIZON_GRID_BACKEND_HOST", "localhost")

INSTALL_DIR = os.environ.get("HORIZON_GRID_INSTALL_DIR", "/opt/horizon-grid")
APP_REPO_DIR = os.environ.get("HORIZON_GRID_APP_REPO_DIR", os.path.join(INSTALL_DIR, "app"))
CONFIG_DIR = os.environ.get("HORIZON_GRID_CONFIG_DIR", "/etc/horizon-grid")
DATA_DIR = os.environ.get("HORIZON_GRID_DATA_DIR", "/var/lib/horizon-grid")
LOG_DIR = os.environ.get("HORIZON_GRID_LOG_DIR", "/var/log/horizon-grid")
ENV_FILE = os.environ.get("HORIZON_GRID_ENV_FILE", os.path.join(CONFIG_DIR, ".env"))
SETUP_LOG = os.environ.get("HORIZON_GRID_SETUP_LOG", os.path.join(LOG_DIR, "setup.log"))

# --- Every AI/provider field the wizard collects, in the exact order
# Write-EnvFile.ps1 writes them, mapped ENV_KEY -> (SettingsKey, prompt label,
# secret?). This table IS the single source of truth for both the .env
# writer and the upgrade-load parser below, exactly like Write-EnvFile.ps1 +
# Setup-Wizard.ps1's own $map hashtable are two views of the same key list. ---
AI_FIELDS = [
    ("OLLAMA_BASE_URL", "OllamaBaseUrl", "Ollama base URL", False),
    ("OLLAMA_MODEL", "OllamaModel", "Ollama model", False),
    ("BEDROCK_API_KEY", "BedrockApiKey", "Bedrock API key", True),
    ("AWS_ACCESS_KEY_ID", "AwsAccessKeyId", "AWS access key ID", False),
    ("AWS_SECRET_ACCESS_KEY", "AwsSecretAccessKey", "AWS secret access key", True),
    ("AWS_REGION", "AwsRegion", "AWS region", False),
    ("BEDROCK_MODEL_ID", "BedrockModelId", "Bedrock model ID", False),
    ("GEMINI_API_KEY", "GeminiApiKey", "Gemini API key", True),
    ("GEMINI_MODEL_ID", "GeminiModelId", "Gemini model ID", False),
    ("ANTHROPIC_API_KEY", "AnthropicApiKey", "Anthropic API key", True),
    ("ANTHROPIC_MODEL_ID", "AnthropicModelId", "Anthropic model ID", False),
    ("GROQ_API_KEY", "GroqApiKey", "Groq API key", True),
    ("GROQ_MODEL_ID", "GroqModelId", "Groq model ID", False),
    ("OPENAI_API_KEY", "OpenAiApiKey", "OpenAI API key", True),
    ("OPENAI_MODEL_ID", "OpenAiModelId", "OpenAI model ID", False),
    ("KIMI_API_KEY", "KimiApiKey", "Kimi (Moonshot) API key", True),
    ("KIMI_MODEL_ID", "KimiModelId", "Kimi model ID", False),
    ("DEEPSEEK_API_KEY", "DeepSeekApiKey", "DeepSeek API key", True),
    ("DEEPSEEK_MODEL_ID", "DeepSeekModelId", "DeepSeek model ID", False),
    ("XAI_API_KEY", "XaiApiKey", "xAI (Grok) API key", True),
    ("XAI_MODEL_ID", "XaiModelId", "xAI model ID", False),
    ("MISTRAL_API_KEY", "MistralApiKey", "Mistral API key", True),
    ("MISTRAL_MODEL_ID", "MistralModelId", "Mistral model ID", False),
    ("OPENROUTER_API_KEY", "OpenRouterApiKey", "OpenRouter API key", True),
    ("OPENROUTER_MODEL_ID", "OpenRouterModelId", "OpenRouter model ID", False),
]

PROVIDER_FIELDS = [
    # (env_key, settings_key, provider_id used by POST /api/v1/providers/{id}/test, label)
    ("VIRUSTOTAL_API_KEY", "VirusTotalApiKey", "virustotal", "VirusTotal API key"),
    ("ABUSEIPDB_API_KEY", "AbuseIpdbApiKey", "abuseipdb", "AbuseIPDB API key"),
    ("OTX_API_KEY", "OtxApiKey", "alienvault_otx", "AlienVault OTX API key"),
    ("NVD_API_KEY", "NvdApiKey", "nist_nvd", "NIST NVD API key (optional -- raises rate limit)"),
    ("ABUSECH_AUTH_KEY", "AbuseChAuthKey", "urlhaus", "abuse.ch Auth-Key (activates URLhaus, ThreatFox, MalwareBazaar)"),
    ("HYBRID_ANALYSIS_API_KEY", "HybridAnalysisApiKey", "hybrid_analysis", "Hybrid Analysis API key"),
    ("CENSYS_PERSONAL_ACCESS_TOKEN", "CensysPersonalAccessToken", "censys", "Censys Personal Access Token"),
    ("CENSYS_ORGANIZATION_ID", "CensysOrganizationId", "censys", "Censys Organization ID"),
    ("PHISHTANK_API_KEY", "PhishTankApiKey", "phishtank", "PhishTank API key (optional -- raises rate limit)"),
]

# Note deliberately carried over into every run of this wizard, matching the
# real, current state of the application rather than glossing over it: the
# providers below have NO field in Write-EnvFile.ps1/.env on Windows either
# -- they are configured exclusively through the running application's own
# Manage Providers UI (runtime, database-backed, Fernet-encrypted config),
# not through this installer-level .env. That is true on both platforms;
# it is not something Linux packaging is missing.
RUNTIME_ONLY_NOTE = (
    "urlscan.io and Google Safe Browsing (and every provider that needs no "
    "credential -- crt.sh, CISA KEV, MITRE ATT&CK, WHOIS/RDAP, Spamhaus, the "
    "Internet Intelligence Collector) are not configured here. Set them up "
    "after install from the app's own Providers page (sign in -> Providers) "
    "-- exactly the same as on Windows."
)


def log(message, level="INFO"):
    try:
        os.makedirs(os.path.dirname(SETUP_LOG), exist_ok=True)
        with open(SETUP_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] [%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, message))
    except OSError:
        pass


def fail(message):
    print("ERROR: %s" % message, file=sys.stderr)
    log(message, "ERROR")
    sys.exit(1)


def require_root():
    if os.geteuid() != 0:
        fail("This wizard needs root privileges (it writes %s and manages containers). Re-run with sudo." % CONFIG_DIR)


def _detect_host_gateway_override():
    """Python equivalent of linux/scripts/common.sh's
    hg_detect_host_gateway_override -- see that function's own comment for
    the full root-cause story. Short version: docker-compose.yml's
    "host-gateway" extra_hosts value (Compose's own special
    host.docker.internal target) resolves to the wrong place under WSL2
    running its own native docker-ce (get.docker.com inside the WSL2
    distro, as opposed to Docker Desktop's WSL2 integration) -- "the host"
    from dockerd's point of view there is the WSL2 VM itself, one hop
    short of the real Windows machine where a host-run service (e.g.
    Ollama) actually listens. The WSL2 VM's own default-route gateway
    DOES reach the outer Windows host (the standard, documented way to do
    so from inside WSL2), so this returns that IP specifically when WSL2
    is detected, and "" (meaning: leave HOST_GATEWAY_TARGET unset, keep
    plain "host-gateway") in every other case -- real bare-metal Linux
    docker-ce (no WSL), Docker Desktop, or any failure along the way.

    Computed fresh on every call (never cached/written to .env): WSL2's
    NAT default-route gateway IP is not guaranteed stable across host
    reboots.
    """
    is_wsl2 = False
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as f:
            if "microsoft" in f.read().lower():
                is_wsl2 = True
    except OSError:
        pass
    if not is_wsl2:
        try:
            with open("/proc/sys/kernel/osrelease", "r", encoding="utf-8", errors="ignore") as f:
                osrelease = f.read().lower()
            if "microsoft" in osrelease or "wsl2" in osrelease:
                is_wsl2 = True
        except OSError:
            pass
    if not is_wsl2:
        return ""

    # Parsed in Python rather than shelling out to awk (portable/testable):
    # a real `ip route` default line looks like
    # "default via 172.30.192.1 dev eth0 proto kernel", so the gateway is
    # the token right after "via" on the "default" line.
    try:
        result = subprocess.run(
            ["ip", "route"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0 or not result.stdout:
        return ""
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
            return parts[2]
    return ""


def run_prerequisite_checks():
    """Real gap fixed: check-prerequisites.sh (Docker Engine installed and
    running, Compose v2, root, disk space -- every HARD check the postinst
    hook already runs) was previously wired up as informational-only: the
    .deb's postinst discards its exit code and output entirely
    (`>/dev/null 2>&1 || echo "...run 'horizon-grid check' for detail"`),
    and NOTHING ever called it before actually attempting
    'docker compose up' -- a missing Docker install, for example, surfaced
    only as a confusing "docker: command not found" mid-install instead of
    a clear, actionable message up front. This wizard is the one place both
    a fresh install AND a reconfigure always pass through, so it's the
    right choke point to make this a REAL gate rather than yet another
    caller that has to remember to check.

    The script itself already distinguishes hard vs. soft failures (its own
    `ok` field in the JSON it emits) -- soft ones (unsupported distro,
    <8GB RAM, a busy port the wizard's own Port Review page can remap) are
    only ever printed as warnings here, never block. Only a real hard
    failure (not root, Docker missing/not running, no Compose v2,
    insufficient disk) stops the wizard, with the exact failing checks'
    own detail printed -- never a bare "prerequisites failed."
    """
    script = os.path.join(SCRIPTS_DIR, "check-prerequisites.sh")
    if not os.path.isfile(script):
        log("check-prerequisites.sh not found at %s -- skipping the prerequisite gate." % script, "WARN")
        return

    print("Checking prerequisites...")
    try:
        # stderr is the script's own live human-readable [PASS]/[FAIL] lines
        # -- left to flow straight to the terminal instead of capturing it,
        # so the operator sees real-time progress exactly like running
        # 'horizon-grid check' directly. Only stdout (the one JSON summary
        # object) is parsed to decide whether to block.
        result = subprocess.run([script], stdout=subprocess.PIPE, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        log("Could not run check-prerequisites.sh: %s -- continuing without this gate." % exc, "WARN")
        print("WARNING: could not run the prerequisite check (%s) -- continuing anyway." % exc)
        return

    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        log("Could not parse check-prerequisites.sh output: %s -- continuing without this gate." % exc, "WARN")
        print("WARNING: could not parse the prerequisite check's output -- continuing anyway.")
        return

    if report.get("ok"):
        print("Prerequisites OK.")
        print("")
        return

    failing_hard = [c for c in report.get("checks", []) if c.get("hard") and not c.get("passed")]
    print("")
    print("ERROR: this machine does not meet HORIZON GRID's hard requirements:")
    for check in failing_hard:
        print("  - %s: %s" % (check.get("name"), check.get("detail")))
    print("")
    print("Fix the issue(s) above, then re-run 'sudo horizon-grid configure'. "
          "Run 'sudo horizon-grid check' any time to re-check without starting the wizard.")
    log("Blocked by failing hard prerequisite check(s): %s" % ", ".join(c.get("name", "") for c in failing_hard), "ERROR")
    sys.exit(1)


def new_random_secret(nbytes=48):
    return secrets.token_urlsafe(nbytes)


def new_encryption_master_key():
    """ENCRYPTION_MASTER_KEY is fed directly into cryptography.fernet.Fernet()
    by backend/app/core/crypto.py with no derivation step (unlike
    JWT_SECRET_KEY, which is just an opaque string), so it MUST be exactly 32
    raw random bytes, url-safe-base64-encoded WITH padding kept intact --
    i.e. exactly what Fernet.generate_key() itself produces. new_random_secret()
    would not work here: secrets.token_urlsafe()'s output length/padding
    does not reliably base64-decode back to exactly 32 bytes, which raises
    inside Fernet() the first time a credential is saved."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def convert_to_safe_env_value(value, field_name):
    """Mirrors Write-EnvFile.ps1's ConvertTo-SafeEnvValue exactly: strip
    CR/LF (never legitimately needed in a credential), and reject a value
    containing '#' outright rather than silently truncating it -- '#' starts
    a comment in .env format for both Docker Compose's env_file parser and
    the backend's pydantic-settings loader, so a key containing one would be
    silently corrupted into a different, broken string with no error
    anywhere downstream."""
    if not value:
        return value
    stripped = value.replace("\r", "").replace("\n", "")
    if "#" in stripped:
        fail(
            "The value entered for '%s' contains a '#' character, which cannot be "
            "safely stored in the configuration file (it would be silently "
            "truncated there). Check for a copy-paste error and remove it, then "
            "try again." % field_name
        )
    return stripped


def default_settings():
    """Mirrors Write-EnvFile.ps1's New-DefaultPlatformSettings."""
    settings = {
        "JwtSecretKey": new_random_secret(48),
        "EncryptionMasterKey": new_encryption_master_key(),
        "PostgresPassword": new_random_secret(24),
        "Neo4jPassword": new_random_secret(24),
        "PortFrontend": 3000,
        "PortBackend": 8000,
        "PortPostgres": 5433,
        "PortRedis": 6379,
        "PortNeo4jHttp": 7475,
        "PortNeo4jBolt": 7688,
        "PortOpenSearch": 9200,
        "PublicApiUrl": "",
        "DetectedLanIp": "",
        "AiBackend": "ollama",
        "OllamaBaseUrl": "http://host.docker.internal:11434",
        "OllamaModel": "llama3.2:3b",
        "AwsRegion": "us-east-1",
        "BedrockModelId": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        "GeminiModelId": "gemini-2.0-flash",
        "AnthropicModelId": "claude-sonnet-4-5-20250929",
        "GroqModelId": "llama-3.3-70b-versatile",
        "OpenAiModelId": "gpt-4o-mini",
        "KimiModelId": "kimi-k2.5",
        "DeepSeekModelId": "deepseek-v4-flash",
        "XaiModelId": "grok-4.6",
        "MistralModelId": "mistral-small-2506",
        "OpenRouterModelId": "openai/gpt-4o",
    }
    for _, settings_key, *_ in [f[:2] for f in AI_FIELDS] + [(f[0], f[1]) for f in PROVIDER_FIELDS]:
        settings.setdefault(settings_key, "")
    return settings


ENV_KEY_TO_SETTINGS_KEY = {
    "JWT_SECRET_KEY": "JwtSecretKey",
    "ENCRYPTION_MASTER_KEY": "EncryptionMasterKey",
    "POSTGRES_PASSWORD": "PostgresPassword",
    "NEO4J_PASSWORD": "Neo4jPassword",
    "HOST_PORT_FRONTEND": "PortFrontend",
    "HOST_PORT_BACKEND": "PortBackend",
    "HOST_PORT_POSTGRES": "PortPostgres",
    "HOST_PORT_REDIS": "PortRedis",
    "HOST_PORT_NEO4J_HTTP": "PortNeo4jHttp",
    "HOST_PORT_NEO4J_BOLT": "PortNeo4jBolt",
    "HOST_PORT_OPENSEARCH": "PortOpenSearch",
    "PUBLIC_API_URL": "PublicApiUrl",
    "DETECTED_LAN_IP": "DetectedLanIp",
    "AI_BACKEND": "AiBackend",
}
for env_key, settings_key, *_ in AI_FIELDS:
    ENV_KEY_TO_SETTINGS_KEY[env_key] = settings_key
for env_key, settings_key, *_ in PROVIDER_FIELDS:
    ENV_KEY_TO_SETTINGS_KEY[env_key] = settings_key
PORT_SETTINGS_KEYS = {v for k, v in ENV_KEY_TO_SETTINGS_KEY.items() if k.startswith("HOST_PORT_")}


def load_existing_env(path):
    """Mirrors Setup-Wizard.ps1's own upgrade-load block."""
    settings = {}
    if not os.path.isfile(path):
        return settings
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2)
                if key in ENV_KEY_TO_SETTINGS_KEY:
                    settings_key = ENV_KEY_TO_SETTINGS_KEY[key]
                    settings[settings_key] = int(val) if settings_key in PORT_SETTINGS_KEYS and val else val
        log("Loaded existing configuration from %s for re-run." % path)
    except OSError as exc:
        log("Could not parse existing .env, starting from defaults: %s" % exc, "WARN")
    return settings


def write_platform_env_file(settings, path):
    """Mirrors Write-EnvFile.ps1's Write-PlatformEnvFile exactly -- same
    keys, same order, same header comment intent, same safety pass on every
    value first."""
    safe = {k: convert_to_safe_env_value(str(v) if v is not None else "", k) for k, v in settings.items()}

    lines = [
        "# Generated by the HORIZON GRID Linux setup wizard.",
        "# Do not commit this file -- it contains real credentials.",
        "# Re-run the setup wizard (sudo horizon-grid configure) to change any of these values later.",
        "",
        "# --- Security ---",
        "JWT_SECRET_KEY=%s" % safe["JwtSecretKey"],
        "# Independent key used to encrypt provider/AI credentials at rest",
        "# (app/core/crypto.py) -- kept separate from JWT_SECRET_KEY so that",
        "# rotating one never orphans credentials encrypted under the other.",
        "ENCRYPTION_MASTER_KEY=%s" % safe.get("EncryptionMasterKey", ""),
        "",
        "# --- Host port mapping (changed here if the installer detected a conflict) ---",
        "HOST_PORT_FRONTEND=%s" % safe["PortFrontend"],
        "HOST_PORT_BACKEND=%s" % safe["PortBackend"],
        "HOST_PORT_POSTGRES=%s" % safe["PortPostgres"],
        "HOST_PORT_REDIS=%s" % safe["PortRedis"],
        "HOST_PORT_NEO4J_HTTP=%s" % safe["PortNeo4jHttp"],
        "HOST_PORT_NEO4J_BOLT=%s" % safe["PortNeo4jBolt"],
        "HOST_PORT_OPENSEARCH=%s" % safe["PortOpenSearch"],
        "# Left empty by default -- the frontend auto-detects its own origin",
        "# (frontend/lib/api.ts's getApiUrl()) so this only needs a value for a",
        "# reverse-proxy or other non-default setup.",
        "PUBLIC_API_URL=%s" % safe.get("PublicApiUrl", ""),
        "# Best-effort LAN IP detected by the wizard, for the Network Access panel's",
        "# display only -- re-run Configuration if your network changes.",
        "DETECTED_LAN_IP=%s" % safe.get("DetectedLanIp", ""),
        "",
        "# --- Datastore credentials (randomly generated at install time) ---",
        "POSTGRES_USER=ioc",
        "POSTGRES_PASSWORD=%s" % safe["PostgresPassword"],
        "POSTGRES_DB=ioc_intel",
        "NEO4J_PASSWORD=%s" % safe["Neo4jPassword"],
        "",
        "# --- AI backend ---",
        "AI_BACKEND=%s" % safe["AiBackend"],
    ]
    for env_key, settings_key, *_ in AI_FIELDS:
        lines.append("%s=%s" % (env_key, safe.get(settings_key, "")))
    lines += ["", "# --- Free-tier / paid intelligence providers ---"]
    for env_key, settings_key, *_ in PROVIDER_FIELDS:
        lines.append("%s=%s" % (env_key, safe.get(settings_key, "")))
    lines.append("")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    os.chmod(path, 0o600)
    try:
        os.chown(path, 0, 0)
    except (OSError, PermissionError):
        pass  # not root in a --dry-run/test context without CAP_CHOWN


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def find_free_port(preferred, max_attempts=50):
    for i in range(max_attempts):
        candidate = preferred + i
        if port_free(candidate):
            return candidate
    fail("Could not find a free port near %d after %d attempts." % (preferred, max_attempts))


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        return ""


def http_json(method, url, body=None, token=None, timeout=15):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except (ValueError, TypeError):
            return e.code, {"detail": raw.decode("utf-8", "replace")}
    except (urllib.error.URLError, OSError) as e:
        return None, {"detail": str(e)}


class Wizard:
    def __init__(self, args):
        self.args = args
        self.answers = {}
        if args.answers_file:
            with open(args.answers_file, "r", encoding="utf-8") as f:
                self.answers = json.load(f)
        self.is_upgrade = os.path.isfile(ENV_FILE)
        self.settings = default_settings()
        if self.is_upgrade:
            self.settings.update(load_existing_env(ENV_FILE))
        self.admin_email = ""
        self.admin_password = ""
        self.admin_full_name = ""
        self.access_token = None

    # --- input helpers (interactive prompt, or pull from --answers-file) ---
    def ask(self, key, prompt, default="", secret=False):
        if self.args.non_interactive:
            return str(self.answers.get(key, default))
        suffix = " [%s]" % default if default and not secret else ""
        value = (getpass.getpass if secret else input)("%s%s: " % (prompt, suffix))
        return value.strip() or default

    def confirm(self, prompt, default=True):
        if self.args.non_interactive:
            return bool(self.answers.get(prompt, default))
        resp = input("%s [%s]: " % (prompt, "Y/n" if default else "y/N")).strip().lower()
        if not resp:
            return default
        return resp.startswith("y")

    # --- session for live Test Connection calls -- mirrors
    # Get-OrCreateWizardSession EXACTLY, including the comment's own point:
    # this only ever LOGS IN, never registers/creates an account, and only
    # works once the admin_email/admin_password fields are populated. ---
    def get_or_create_session(self):
        if self.access_token:
            return self.access_token
        if not self.admin_email or not self.admin_password:
            return None
        base = "http://%s:%s" % (BACKEND_HOST, self.settings["PortBackend"])
        status, body = http_json("POST", base + "/api/v1/auth/login",
                                  {"email": self.admin_email, "password": self.admin_password})
        if status == 200 and "access_token" in body:
            self.access_token = body["access_token"]
            log("Signed in to obtain a test session for %s." % self.admin_email)
            return self.access_token
        log("get_or_create_session: sign-in failed: %s" % body.get("detail", status), "WARN")
        return None

    def test_ai_connection(self, backend, credentials, model=None):
        """Returns True (test passed), False (test ran and failed), or None
        (no session available -- couldn't test at all, e.g. fresh install
        with no backend running yet). Callers use this three-way result
        (not just print output) to decide whether it's safe to move on --
        see page_ai_configuration's retry loop and run_install's
        post-health-check validation, both added to fix a real gap: nothing
        previously stopped an operator from proceeding past a config value
        that had just failed a live connectivity test."""
        token = self.get_or_create_session()
        if not token:
            print("  (Test Connection needs the backend already running with a valid admin login -- "
                  "same as on Windows, this only works on a reconfigure of an existing install. "
                  "It will be reachable from the app's own AI Providers page after install.)")
            return None
        base = "http://%s:%s" % (BACKEND_HOST, self.settings["PortBackend"])
        payload = {"backend": backend, "credentials": credentials}
        if model:
            payload["model"] = model
        status, body = http_json("POST", base + "/api/v1/ai/test", payload, token=token, timeout=30)
        if status == 200 and body.get("ok"):
            print("  OK: %s" % body.get("message", body))
            return True
        print("  FAILED: %s" % body.get("detail", body.get("message", body)))
        return False

    def test_provider_connection(self, provider_id, credentials):
        """Same three-way True/False/None contract as test_ai_connection --
        see its docstring."""
        token = self.get_or_create_session()
        if not token:
            print("  (Test Connection needs the backend already running with a valid admin login -- "
                  "reachable from the app's own IOC Providers page after install.)")
            return None
        base = "http://%s:%s" % (BACKEND_HOST, self.settings["PortBackend"])
        status, body = http_json("POST", base + "/api/v1/providers/%s/test" % provider_id,
                                  {"credentials": credentials}, token=token, timeout=30)
        if status == 200 and body.get("ok"):
            print("  OK: %s" % body.get("message", body))
            return True
        print("  FAILED: %s" % body.get("detail", body.get("message", body)))
        return False

    # --- pages ---
    def page_welcome(self):
        print("=" * 70)
        print("HORIZON GRID -- %s" % ("Reconfigure" if self.is_upgrade else "Setup"))
        print("=" * 70)
        if self.is_upgrade:
            print("An existing installation was found at %s. Leave fields blank to keep" % ENV_FILE)
            print("their current value.")
        else:
            print("This wizard will configure HORIZON GRID: an administrator account, your")
            print("AI backend, and the threat-intelligence providers you want enabled.")
            print("Docker Engine (with the compose plugin) must already be installed and")
            print("running. Provider API keys are optional -- add them now, later, or never.")
        print("")

    def page_admin_account(self):
        print("-- Administrator Account " + "-" * 44)
        if self.is_upgrade:
            print("An administrator account already exists. Leave email/password blank to")
            print("keep it unchanged, or re-enter it to sign in for this session (enables")
            print("live Test Connection checks below, without changing the account).")
        else:
            print("This creates the first user account, which becomes the platform's")
            print("Administrator automatically (the backend's own rule: the first")
            print("registered user gets the Admin role).")
        self.admin_email = self.ask("admin_email", "Email", default="")
        if not self.is_upgrade or self.admin_email:
            self.admin_full_name = self.ask("admin_full_name", "Full name (optional)", default="")
            while True:
                self.admin_password = self.ask("admin_password", "Password (min. 8 characters)", secret=True)
                if self.is_upgrade and not self.admin_password:
                    break
                if len(self.admin_password) < 8:
                    print("  Password must be at least 8 characters.")
                    if self.args.non_interactive:
                        break
                    continue
                confirm_pw = self.ask("admin_password_confirm", "Confirm password", secret=True)
                if confirm_pw != self.admin_password:
                    print("  Passwords do not match.")
                    if self.args.non_interactive:
                        break
                    continue
                break
        print("")

    def page_ai_configuration(self):
        print("-- AI Configuration " + "-" * 49)
        backends = ["ollama", "anthropic", "bedrock", "gemini", "groq", "openai", "kimi", "deepseek", "xai", "mistral", "openrouter"]
        current = self.settings.get("AiBackend", "ollama")
        print("AI backends: %s" % ", ".join(backends))

        # Real gap fixed: this page previously let an operator answer "no"
        # (the default) to "Test this connection now?", or test it, see
        # FAILED, and just proceed anyway -- nothing enforced this
        # platform's own "must not save obviously invalid config as valid"
        # requirement. Wrapped in a loop so a failed test re-prompts for the
        # same backend's fields (pre-filled with what was just typed, easy
        # to fix or re-confirm) instead of silently moving on. Deliberately
        # does NOT loop forever with no escape: a fresh install has no
        # backend running yet to test against at all (get_or_create_session
        # returns None, test_*_connection returns None, not False) -- that
        # case can never be gated here, see run_install()'s own
        # post-health-check validation for how it's still honestly reported
        # once the backend exists. An interactive operator who deliberately
        # wants to proceed past a REAL failure (e.g. Ollama isn't started
        # yet but will be before first use) can still choose to.
        while True:
            backend = self.ask("ai_backend", "AI backend", default=current)
            if backend not in backends:
                print("  Unrecognized backend '%s' -- keeping '%s'." % (backend, current))
                backend = current
            self.settings["AiBackend"] = backend

            creds = {}
            if backend == "ollama":
                self.settings["OllamaBaseUrl"] = self.ask("ollama_base_url", "Ollama base URL",
                                                            default=self.settings.get("OllamaBaseUrl", "http://host.docker.internal:11434"))
                self.settings["OllamaModel"] = self.ask("ollama_model", "Ollama model",
                                                          default=self.settings.get("OllamaModel", "llama3.2:3b"))
                creds = {"base_url": self.settings["OllamaBaseUrl"], "model": self.settings["OllamaModel"]}
            elif backend == "anthropic":
                self.settings["AnthropicApiKey"] = self.ask("anthropic_api_key", "Anthropic API key", secret=True) or self.settings.get("AnthropicApiKey", "")
                self.settings["AnthropicModelId"] = self.ask("anthropic_model_id", "Anthropic model ID", default=self.settings.get("AnthropicModelId", "claude-sonnet-4-5-20250929"))
                creds = {"api_key": self.settings["AnthropicApiKey"]}
            elif backend == "bedrock":
                self.settings["BedrockApiKey"] = self.ask("bedrock_api_key", "Bedrock API key (bearer token, preferred)", secret=True) or self.settings.get("BedrockApiKey", "")
                self.settings["AwsAccessKeyId"] = self.ask("aws_access_key_id", "AWS access key ID (fallback, if no Bedrock API key)", default=self.settings.get("AwsAccessKeyId", ""))
                self.settings["AwsSecretAccessKey"] = self.ask("aws_secret_access_key", "AWS secret access key", secret=True) or self.settings.get("AwsSecretAccessKey", "")
                self.settings["AwsRegion"] = self.ask("aws_region", "AWS region", default=self.settings.get("AwsRegion", "us-east-1"))
                self.settings["BedrockModelId"] = self.ask("bedrock_model_id", "Bedrock model ID", default=self.settings.get("BedrockModelId"))
                creds = {"api_key": self.settings["BedrockApiKey"], "access_key_id": self.settings["AwsAccessKeyId"],
                         "secret_access_key": self.settings["AwsSecretAccessKey"], "region": self.settings["AwsRegion"]}
            elif backend == "gemini":
                self.settings["GeminiApiKey"] = self.ask("gemini_api_key", "Gemini API key", secret=True) or self.settings.get("GeminiApiKey", "")
                self.settings["GeminiModelId"] = self.ask("gemini_model_id", "Gemini model ID", default=self.settings.get("GeminiModelId", "gemini-2.0-flash"))
                creds = {"api_key": self.settings["GeminiApiKey"]}
            elif backend == "groq":
                self.settings["GroqApiKey"] = self.ask("groq_api_key", "Groq API key", secret=True) or self.settings.get("GroqApiKey", "")
                self.settings["GroqModelId"] = self.ask("groq_model_id", "Groq model ID", default=self.settings.get("GroqModelId", "llama-3.3-70b-versatile"))
                creds = {"api_key": self.settings["GroqApiKey"]}
            elif backend == "openai":
                self.settings["OpenAiApiKey"] = self.ask("openai_api_key", "OpenAI API key", secret=True) or self.settings.get("OpenAiApiKey", "")
                self.settings["OpenAiModelId"] = self.ask("openai_model_id", "OpenAI model ID", default=self.settings.get("OpenAiModelId", "gpt-4o-mini"))
                creds = {"api_key": self.settings["OpenAiApiKey"]}
            elif backend == "kimi":
                self.settings["KimiApiKey"] = self.ask("kimi_api_key", "Kimi (Moonshot) API key", secret=True) or self.settings.get("KimiApiKey", "")
                self.settings["KimiModelId"] = self.ask("kimi_model_id", "Kimi model ID", default=self.settings.get("KimiModelId", "kimi-k2.5"))
                creds = {"api_key": self.settings["KimiApiKey"]}
            elif backend == "deepseek":
                self.settings["DeepSeekApiKey"] = self.ask("deepseek_api_key", "DeepSeek API key", secret=True) or self.settings.get("DeepSeekApiKey", "")
                self.settings["DeepSeekModelId"] = self.ask("deepseek_model_id", "DeepSeek model ID", default=self.settings.get("DeepSeekModelId", "deepseek-v4-flash"))
                creds = {"api_key": self.settings["DeepSeekApiKey"]}
            elif backend == "xai":
                self.settings["XaiApiKey"] = self.ask("xai_api_key", "xAI (Grok) API key", secret=True) or self.settings.get("XaiApiKey", "")
                self.settings["XaiModelId"] = self.ask("xai_model_id", "xAI model ID", default=self.settings.get("XaiModelId", "grok-4.6"))
                creds = {"api_key": self.settings["XaiApiKey"]}
            elif backend == "mistral":
                self.settings["MistralApiKey"] = self.ask("mistral_api_key", "Mistral API key", secret=True) or self.settings.get("MistralApiKey", "")
                self.settings["MistralModelId"] = self.ask("mistral_model_id", "Mistral model ID", default=self.settings.get("MistralModelId", "mistral-small-2506"))
                creds = {"api_key": self.settings["MistralApiKey"]}
            elif backend == "openrouter":
                self.settings["OpenRouterApiKey"] = self.ask("openrouter_api_key", "OpenRouter API key", secret=True) or self.settings.get("OpenRouterApiKey", "")
                self.settings["OpenRouterModelId"] = self.ask("openrouter_model_id", "OpenRouter model ID", default=self.settings.get("OpenRouterModelId", "openai/gpt-4o"))
                creds = {"api_key": self.settings["OpenRouterApiKey"]}

            tested_ok = None
            if self.confirm("Test this connection now?", default=False):
                tested_ok = self.test_ai_connection(backend, creds)
            if tested_ok is False:
                if self.args.non_interactive:
                    log("AI backend '%s' failed its connectivity test in non-interactive mode -- "
                        "continuing anyway. Fix it later with 'horizon-grid configure'." % backend, "WARN")
                    print("  WARNING: continuing with a failing AI backend configuration (non-interactive mode).")
                    break
                retry = input("  This test FAILED. Re-enter these settings? [Y/n]: ").strip().lower()
                if retry in ("", "y", "yes"):
                    continue
                print("  Continuing with these settings despite the failed test -- fix later with "
                      "'horizon-grid configure' if needed.")
            break
        print("")

    def page_providers(self):
        print("-- Threat Intelligence Providers " + "-" * 36)
        print("All optional. Leave a key blank to skip that provider -- the platform")
        print("works fine with any subset configured, including none.")
        print(RUNTIME_ONLY_NOTE)
        print("")
        seen_settings_keys = set()
        for env_key, settings_key, provider_id, label in PROVIDER_FIELDS:
            if settings_key in seen_settings_keys:
                continue
            seen_settings_keys.add(settings_key)
            # Same "don't silently move on from a known-failed test" gate as
            # page_ai_configuration -- see its comment for the full
            # rationale. Every provider here is optional, so a blank value
            # is never gated (nothing to test); only a non-blank value that
            # was actively tested and failed re-prompts.
            while True:
                current = self.settings.get(settings_key, "")
                value = self.ask(settings_key.lower(), label, secret=True) or current
                self.settings[settings_key] = value
                # Censys needs BOTH the Personal Access Token and Organization ID
                # together -- deferred to right after the second field is
                # collected (matches the app's own Manage Providers UI, where
                # Censys's row only has one Test Connection button for both
                # fields, not one each) rather than testing the token alone with
                # an organization ID that hasn't been typed yet.
                if env_key == "CENSYS_PERSONAL_ACCESS_TOKEN":
                    break
                tested_ok = None
                if value and self.confirm("  Test %s now?" % label, default=False):
                    creds = {"api_key": value}
                    if env_key == "CENSYS_ORGANIZATION_ID":
                        creds = {"personal_access_token": self.settings.get("CensysPersonalAccessToken", ""), "organization_id": value}
                    tested_ok = self.test_provider_connection(provider_id, creds)
                if tested_ok is False:
                    if self.args.non_interactive:
                        log("Provider '%s' failed its connectivity test in non-interactive mode -- "
                            "continuing anyway. Fix it later with 'horizon-grid configure'." % provider_id, "WARN")
                        print("  WARNING: continuing with a failing %s configuration (non-interactive mode)." % label)
                        break
                    retry = input("  This test FAILED. Re-enter this value? [Y/n]: ").strip().lower()
                    if retry in ("", "y", "yes"):
                        continue
                    print("  Continuing with this value despite the failed test -- clear it to skip this "
                          "provider, or fix it later with 'horizon-grid configure'.")
                break
        print("")

    def page_ports(self):
        print("-- Network Ports " + "-" * 52)
        print("Each service needs its own port on this machine. Conflicts with something")
        print("already running are shown below -- pick a different port or accept the")
        print("suggested free one.")
        port_labels = [
            ("PortFrontend", "Web interface"),
            ("PortBackend", "Backend API"),
            ("PortPostgres", "PostgreSQL (internal)"),
            ("PortRedis", "Redis (internal)"),
            ("PortNeo4jHttp", "Neo4j HTTP (internal)"),
            ("PortNeo4jBolt", "Neo4j Bolt (internal)"),
            ("PortOpenSearch", "OpenSearch (internal)"),
        ]
        for settings_key, label in port_labels:
            current = int(self.settings.get(settings_key))
            if not port_free(current):
                suggested = find_free_port(current + 1)
                print("  %s: port %d is in use -- suggesting %d" % (label, current, suggested))
                current = suggested
            value = self.ask(settings_key.lower(), label, default=str(current))
            self.settings[settings_key] = int(value)
        self.settings["DetectedLanIp"] = get_lan_ip()
        print("")

    def page_summary(self):
        print("-- Ready to Install " + "-" * 49)
        print("Administrator: %s" % (self.admin_email or "(unchanged)"))
        print("AI Backend:    %s" % self.settings["AiBackend"])
        configured = sum(1 for _, sk, *_ in PROVIDER_FIELDS if self.settings.get(sk))
        distinct_providers = len({sk for _, sk, *_ in PROVIDER_FIELDS if self.settings.get(sk)})
        print("Providers configured: %d of %d fields" % (configured, len({sk for _, sk, *_ in PROVIDER_FIELDS})))
        print("Web interface: http://localhost:%s" % self.settings["PortFrontend"])
        print("Backend API:   http://localhost:%s" % self.settings["PortBackend"])
        print("")
        if not self.confirm("Start installation now?", default=True):
            print("Cancelled -- no changes were made.")
            sys.exit(0)

    # --- install/start ---
    def _backup_before_upgrade(self):
        """Real gap fixed: Setup-Wizard.ps1's Windows equivalent already
        calls Backup-Database.ps1 before an upgrade re-runs docker compose
        up --build against an existing install (real gap fixed: if the new
        configuration or a container-image change breaks something, there
        was no fresh snapshot taken right before the risky operation) --
        this wizard had no equivalent call at all. Runs BEFORE the new
        .env is written, same ordering as Windows, so it snapshots the
        database exactly as it stood under the OLD configuration.
        backup-database.sh already no-ops quietly if Postgres isn't
        currently running (e.g. a first attempt that failed before ever
        starting containers) -- same as Windows's script, and same
        "reflect what actually happened, don't just print success"
        discipline: this checks the real exit code."""
        script = os.path.join(SCRIPTS_DIR, "backup-database.sh")
        if not os.path.isfile(script):
            log("backup-database.sh not found at %s -- skipping pre-upgrade backup." % script, "WARN")
            return
        print("Backing up the database before upgrading...")
        result = subprocess.run([script, "--quiet"])
        if result.returncode == 0:
            print("Backup step finished (see %s if you need to confirm a snapshot was actually taken)." % os.path.join(DATA_DIR, "backups"))
        else:
            print("WARNING: database backup failed (exit code %d) -- continuing with the upgrade anyway. "
                  "See %s for details." % (result.returncode, LOG_DIR))
            log("Pre-upgrade backup failed with exit code %d" % result.returncode, "WARN")

    def run_install(self):
        if self.is_upgrade:
            self._backup_before_upgrade()

        write_platform_env_file(self.settings, ENV_FILE)
        log("Configuration written to %s" % ENV_FILE)
        print("Configuration written to %s" % ENV_FILE)

        # Same root-only re-lock on the compose-project-directory copy that
        # hg_sync_compose_env_file performs -- done here too so a wizard run
        # in isolation (before any service script ever runs) still leaves a
        # working, correctly-permissioned copy for `docker compose` to read
        # via its env_file: .env directive.
        try:
            os.makedirs(APP_REPO_DIR, exist_ok=True)
            dest = os.path.join(APP_REPO_DIR, ".env")
            with open(ENV_FILE, "rb") as src, open(dest, "wb") as dst:
                dst.write(src.read())
            os.chmod(dest, 0o600)
        except OSError as exc:
            log("Could not sync .env into %s: %s" % (APP_REPO_DIR, exc), "WARN")

        if self.args.dry_run:
            print("--dry-run: skipping docker compose up and admin registration.")
            return

        if not self.is_upgrade:
            self._remove_stale_volume()

        print("Starting Docker containers (this can take several minutes on first run "
              "while images build)...")
        # Local dict, not a mutation of the real os.environ -- only this one
        # subprocess call needs HOST_GATEWAY_TARGET, and only when
        # _detect_host_gateway_override() actually found a WSL2 override
        # (see its own comment for the full story). Every other caller/run
        # of this wizard is unaffected.
        compose_env = os.environ.copy()
        host_gateway_override = _detect_host_gateway_override()
        if host_gateway_override:
            compose_env["HOST_GATEWAY_TARGET"] = host_gateway_override
        result = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
             "--env-file", ENV_FILE, "up", "-d", "--build"],
            cwd=APP_REPO_DIR,
            env=compose_env,
        )
        if result.returncode != 0:
            fail("docker compose exited with code %d -- see %s for details." % (result.returncode, LOG_DIR))
        print("Containers started.")

        print("Waiting for the backend to become healthy...")
        base = "http://%s:%s" % (BACKEND_HOST, self.settings["PortBackend"])
        healthy = False
        for _ in range(60):
            # /health/detailed, not plain /health: the very next step below
            # creates the administrator account, a real database write, so
            # this must confirm Postgres is actually reachable -- not just
            # that the backend process has started -- before proceeding.
            status, _ = http_json("GET", base + "/health/detailed", timeout=5)
            if status == 200:
                healthy = True
                break
            time.sleep(3)
        if not healthy:
            fail("Backend did not become healthy in time. Run 'horizon-grid status' for detail.")
        print("Backend is healthy.")

        # Real gap found and fixed during a mission-critical-readiness
        # review: horizon-grid.service's own [Install] section declares
        # WantedBy=multi-user.target, but a systemd unit file merely
        # existing (even after `systemctl daemon-reload`, which postinst
        # already runs) does nothing at boot -- WantedBy= only takes effect
        # once `systemctl enable` has actually created the symlink under
        # /etc/systemd/system/multi-user.target.wants/. Confirmed live: this
        # call never existed anywhere in the codebase before, meaning a
        # configured, running platform would NOT come back after a host
        # reboot despite the unit file itself being entirely correct -- the
        # exact Linux equivalent of the "no boot-time auto-start at all" gap
        # this same review found and fixed on Windows (Setup-Wizard.ps1's
        # Register-BootAndWatchdogTasks).
        if shutil.which("systemctl"):
            try:
                subprocess.run(["systemctl", "enable", "horizon-grid.service"], check=True)
                print("Enabled horizon-grid.service -- the platform will now start automatically on boot.")
            except subprocess.CalledProcessError as exc:
                print("WARNING: could not enable horizon-grid.service (%s) -- the platform will need to be "
                      "started manually after a reboot ('sudo horizon-grid start')." % exc)
                log("systemctl enable horizon-grid.service failed: %s" % exc, "WARN")
            try:
                # --now also starts the timer immediately, matching
                # Register-BootAndWatchdogTasks's Windows equivalent (the
                # watchdog task is registered to already be running, not
                # merely armed for the next boot).
                subprocess.run(["systemctl", "enable", "--now", "horizon-grid-watchdog.timer"], check=True)
                print("Enabled horizon-grid-watchdog.timer -- the platform will now self-restart if it becomes unhealthy.")
            except subprocess.CalledProcessError as exc:
                print("WARNING: could not enable horizon-grid-watchdog.timer (%s) -- no automatic recovery "
                      "watchdog will run." % exc)
                log("systemctl enable horizon-grid-watchdog.timer failed: %s" % exc, "WARN")
            try:
                # Real gap fixed: before this, the ONLY backup mechanisms on
                # Linux were the manual 'horizon-grid backup' command and
                # this wizard's own pre-upgrade call (see _backup_before_upgrade)
                # -- a remote, unattended site where nobody ever runs that
                # command manually had zero recurring backups of its own
                # investigation data. Mirrors Windows's equivalent daily
                # Scheduled Task (Common.ps1's Register-BootAndWatchdogTasks).
                subprocess.run(["systemctl", "enable", "--now", "horizon-grid-backup.timer"], check=True)
                print("Enabled horizon-grid-backup.timer -- the database will now be backed up automatically every day.")
            except subprocess.CalledProcessError as exc:
                print("WARNING: could not enable horizon-grid-backup.timer (%s) -- no automatic recurring "
                      "backup will run ('sudo horizon-grid backup' still works manually)." % exc)
                log("systemctl enable horizon-grid-backup.timer failed: %s" % exc, "WARN")

        if not self.is_upgrade:
            print("Creating administrator account...")
            status, body = http_json("POST", base + "/api/v1/auth/register", {
                "email": self.admin_email, "password": self.admin_password,
                "full_name": self.admin_full_name,
            })
            if status not in (200, 201):
                fail("Administrator account creation failed: %s" % body.get("detail", body))
            status, body = http_json("POST", base + "/api/v1/auth/login",
                                      {"email": self.admin_email, "password": self.admin_password})
            if status != 200:
                fail("Administrator account was created but sign-in verification failed: %s" % body.get("detail", body))
            # Needed below for the post-install AI validation call -- this
            # login response was previously discarded once its status code
            # was checked, so no session existed yet for a fresh install
            # even though one was just legitimately obtained right here.
            self.access_token = body.get("access_token")
            print("Administrator account created: %s" % self.admin_email)
            log("Administrator account created: %s" % self.admin_email)
        elif self.admin_email and self.admin_password:
            # Reconfigure run where the operator re-entered credentials --
            # get_or_create_session() is a no-op if a session already exists
            # (e.g. from testing a connection earlier on this same run).
            self.get_or_create_session()

        # Real gap fixed: this wizard could reach "Setup complete" with an
        # AI backend configuration that was never actually validated against
        # the now-running backend -- on a FRESH install, page_ai_configuration's
        # own Test Connection prompt cannot work yet (no backend to test
        # against at that point), so a bad base_url/API key/model id
        # previously went straight into .env with zero validation of any
        # kind, directly contradicting "must not save obviously invalid
        # config as valid." Now that the backend is confirmed healthy and
        # (if available) a session exists, run the exact same real
        # connectivity test page_ai_configuration's own prompt runs, and
        # report the honest result -- never silently assume success, but
        # also never block "Setup complete" on it (a downed/not-yet-started
        # local Ollama at install time is common and recoverable; the
        # platform's own AI-resilience design already tolerates a missing AI
        # backend at investigation time).
        if self.access_token:
            print("Validating the configured AI backend (%s)..." % self.settings["AiBackend"])
            creds = self._current_ai_credentials()
            ok = self.test_ai_connection(self.settings["AiBackend"], creds)
            if ok is False:
                print("WARNING: the configured AI backend ('%s') failed a connectivity test. Investigations "
                      "will still run, but AI-generated summaries/assessments will fail until this is fixed "
                      "('sudo horizon-grid configure')." % self.settings["AiBackend"])
                log("Post-install AI connectivity test failed for backend '%s'." % self.settings["AiBackend"], "WARN")
        else:
            print("Skipped AI backend validation (no session available) -- verify it with "
                  "'sudo horizon-grid configure' once you can sign in.")

    def _current_ai_credentials(self):
        """Rebuilds the credentials dict for the currently-configured AI
        backend from self.settings -- the same shape page_ai_configuration's
        own per-backend branches build, reused here so run_install's
        post-health-check validation tests the real, just-written values
        rather than needing page_ai_configuration to have kept its local
        `creds` variable around."""
        backend = self.settings["AiBackend"]
        if backend == "ollama":
            return {"base_url": self.settings.get("OllamaBaseUrl", ""), "model": self.settings.get("OllamaModel", "")}
        if backend == "anthropic":
            return {"api_key": self.settings.get("AnthropicApiKey", "")}
        if backend == "bedrock":
            return {"api_key": self.settings.get("BedrockApiKey", ""), "access_key_id": self.settings.get("AwsAccessKeyId", ""),
                    "secret_access_key": self.settings.get("AwsSecretAccessKey", ""), "region": self.settings.get("AwsRegion", "")}
        if backend == "gemini":
            return {"api_key": self.settings.get("GeminiApiKey", "")}
        if backend == "groq":
            return {"api_key": self.settings.get("GroqApiKey", "")}
        if backend == "openai":
            return {"api_key": self.settings.get("OpenAiApiKey", "")}
        if backend == "kimi":
            return {"api_key": self.settings.get("KimiApiKey", "")}
        if backend == "deepseek":
            return {"api_key": self.settings.get("DeepSeekApiKey", "")}
        if backend == "xai":
            return {"api_key": self.settings.get("XaiApiKey", "")}
        if backend == "mistral":
            return {"api_key": self.settings.get("MistralApiKey", "")}
        if backend == "openrouter":
            return {"api_key": self.settings.get("OpenRouterApiKey", "")}
        return {}

    def _remove_stale_volume(self):
        result = subprocess.run(
            ["docker", "volume", "ls", "-q",
             "--filter", "label=com.docker.compose.project=app",
             "--filter", "label=com.docker.compose.volume=postgres_data"],
            capture_output=True, text=True,
        )
        volume_id = result.stdout.strip()
        if volume_id:
            log("Fresh install: found a leftover Postgres volume (%s) from an earlier "
                "install attempt with no matching .env -- removing it so the new "
                "password can initialize cleanly." % volume_id)
            subprocess.run(["docker", "volume", "rm", volume_id], capture_output=True)

    def run(self):
        self.page_welcome()
        self.page_admin_account()
        self.page_ai_configuration()
        self.page_providers()
        self.page_ports()
        self.page_summary()
        self.run_install()
        print("")
        print("=" * 70)
        print("Setup complete.")
        print("  Web interface: http://localhost:%s" % self.settings["PortFrontend"])
        if self.settings.get("DetectedLanIp"):
            print("  From another device on this network: http://%s:%s" % (self.settings["DetectedLanIp"], self.settings["PortFrontend"]))
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="HORIZON GRID Linux setup wizard")
    parser.add_argument("--non-interactive", action="store_true",
                         help="Read all answers from --answers-file instead of prompting (used by the automated test suite / unattended installs).")
    parser.add_argument("--answers-file", help="JSON file of answers for --non-interactive mode.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Write configuration but skip 'docker compose up' and admin registration (for testing the wizard's own logic).")
    args = parser.parse_args()

    if args.non_interactive and not args.answers_file:
        parser.error("--non-interactive requires --answers-file")

    require_root()
    run_prerequisite_checks()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "backups"), exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    for d in (CONFIG_DIR, DATA_DIR, LOG_DIR):
        os.chmod(d, 0o700)

    Wizard(args).run()


if __name__ == "__main__":
    main()
