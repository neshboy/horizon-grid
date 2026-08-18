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
import getpass
import json
import os
import re
import secrets
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


def new_random_secret(nbytes=48):
    return secrets.token_urlsafe(nbytes)


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
        token = self.get_or_create_session()
        if not token:
            print("  (Test Connection needs the backend already running with a valid admin login -- "
                  "same as on Windows, this only works on a reconfigure of an existing install. "
                  "It will be reachable from the app's own AI Providers page after install.)")
            return
        base = "http://%s:%s" % (BACKEND_HOST, self.settings["PortBackend"])
        payload = {"backend": backend, "credentials": credentials}
        if model:
            payload["model"] = model
        status, body = http_json("POST", base + "/api/v1/ai/test", payload, token=token, timeout=30)
        if status == 200:
            print("  OK: %s" % body.get("message", body))
        else:
            print("  FAILED: %s" % body.get("detail", body))

    def test_provider_connection(self, provider_id, credentials):
        token = self.get_or_create_session()
        if not token:
            print("  (Test Connection needs the backend already running with a valid admin login -- "
                  "reachable from the app's own IOC Providers page after install.)")
            return
        base = "http://%s:%s" % (BACKEND_HOST, self.settings["PortBackend"])
        status, body = http_json("POST", base + "/api/v1/providers/%s/test" % provider_id,
                                  {"credentials": credentials}, token=token, timeout=30)
        if status == 200:
            print("  OK: %s" % body.get("message", body))
        else:
            print("  FAILED: %s" % body.get("detail", body))

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

        if self.confirm("Test this connection now?", default=False):
            self.test_ai_connection(backend, creds)
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
                continue
            if value and self.confirm("  Test %s now?" % label, default=False):
                creds = {"api_key": value}
                if env_key == "CENSYS_ORGANIZATION_ID":
                    creds = {"personal_access_token": self.settings.get("CensysPersonalAccessToken", ""), "organization_id": value}
                self.test_provider_connection(provider_id, creds)
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
    def run_install(self):
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
        result = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
             "--env-file", ENV_FILE, "up", "-d", "--build"],
            cwd=APP_REPO_DIR,
        )
        if result.returncode != 0:
            fail("docker compose exited with code %d -- see %s for details." % (result.returncode, LOG_DIR))
        print("Containers started.")

        print("Waiting for the backend to become healthy...")
        base = "http://%s:%s" % (BACKEND_HOST, self.settings["PortBackend"])
        healthy = False
        for _ in range(60):
            status, _ = http_json("GET", base + "/health", timeout=5)
            if status == 200:
                healthy = True
                break
            time.sleep(3)
        if not healthy:
            fail("Backend did not become healthy in time. Run 'horizon-grid status' for detail.")
        print("Backend is healthy.")

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
            print("Administrator account created: %s" % self.admin_email)
            log("Administrator account created: %s" % self.admin_email)

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
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "backups"), exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    for d in (CONFIG_DIR, DATA_DIR, LOG_DIR):
        os.chmod(d, 0o700)

    Wizard(args).run()


if __name__ == "__main__":
    main()
