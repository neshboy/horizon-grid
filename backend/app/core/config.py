"""Centralized settings loaded from environment / .env via pydantic-settings.

Every provider connector and the AI service reads its credentials from here so
there is exactly one place that knows about environment variables.
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "HORIZON GRID"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # --- Network (for the LAN-access "Network Access" panel; see main.py's
    # /network-info) ---
    detected_lan_ip: Optional[str] = None   # DETECTED_LAN_IP, written by the Windows wizard's Get-LanIpAddress
    host_port_frontend: int = 3000          # HOST_PORT_FRONTEND -- already in .env via docker-compose's env_file:
    host_port_backend: int = 8000           # HOST_PORT_BACKEND -- ditto

    # --- Security / Auth ---
    jwt_secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    # Optional, separate key for encrypting runtime-configured provider/AI
    # credentials at rest (app/core/crypto.py). If unset, a key is derived
    # from jwt_secret_key instead -- see crypto.py for the tradeoff.
    encryption_master_key: Optional[str] = None

    # --- Datastores ---
    database_url: str = "postgresql+asyncpg://ioc:ioc@postgres:5432/ioc_intel"
    # Per-process-role pool sizing (DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW in docker-compose.yml)
    # -- app/core/db.py's engine is imported identically by app-backend, app-celery_worker,
    # AND app-celery_beat (three separate processes, three separate pools), but only
    # app-backend ever serves concurrent user-facing HTTP traffic (the celery processes run
    # a single lightweight periodic crawl task -- see app/workers/tasks.py -- and barely touch
    # the DB). These defaults (5+5=10, close to SQLAlchemy's own vanilla defaults) are sized
    # for the celery processes' minimal real need; docker-compose.yml gives app-backend a much
    # larger explicit override instead, sized for real concurrent dashboard traffic -- confirmed
    # via a real load test that a route handler's auth dependency (Depends(get_db)) AND the
    # service function it calls (which opens its own separate app/core/db.py::new_session())
    # each hold a DISTINCT connection for the request's full duration, i.e. every authenticated
    # request already costs 2 connections, not 1 -- pool sizing must account for that multiplier
    # rather than assuming 1 connection per concurrent request.
    db_pool_size: int = 5
    db_pool_max_overflow: int = 5
    redis_url: str = "redis://redis:6379/0"
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme-neo4j"
    opensearch_url: str = "http://opensearch:9200"

    # --- Celery ---
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # --- AWS Bedrock (Claude) ---
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    bedrock_api_key: Optional[str] = None  # bearer token from IAM "Generate API key", preferred over access key/secret
    aws_region: str = "us-east-1"
    # Claude Sonnet 4.5 has no in-region or Geo inference profile in
    # ap-southeast-1 -- only the Global cross-region profile reaches it from
    # that region, hence the "global." prefix (see AWS model card).
    bedrock_model_id: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_max_tokens: int = 4096

    # --- Google Gemini (alternative AI backend) ---
    gemini_api_key: Optional[str] = None
    gemini_model_id: str = "gemini-2.0-flash"
    gemini_max_tokens: int = 8192

    # --- Anthropic direct API (alternative AI backend) ---
    anthropic_api_key: Optional[str] = None
    anthropic_model_id: str = "claude-sonnet-4-5-20250929"
    anthropic_max_tokens: int = 8192

    # --- Groq (alternative AI backend -- OpenAI-compatible API, fast inference) ---
    # Not to be confused with "Grok" (xAI) -- this is Groq, api.groq.com.
    # See app/ai/groq_client.py for endpoint/model sourcing notes.
    groq_api_key: Optional[str] = None
    groq_model_id: str = "llama-3.3-70b-versatile"
    groq_max_tokens: int = 8192

    # --- OpenAI / ChatGPT (alternative AI backend -- api.openai.com) ---
    # See app/ai/openai_client.py for endpoint/model sourcing notes.
    openai_api_key: Optional[str] = None
    openai_model_id: str = "gpt-4o-mini"
    openai_max_tokens: int = 8192

    # --- Ollama (primary AI backend -- local, no API key/quota) ---
    # host.docker.internal resolves to the host machine from inside the
    # backend container (Docker Desktop on Windows/Mac); if Ollama runs on a
    # different host, point this at that host's address instead.
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_max_tokens: int = 8192

    ai_backend: str = "ollama"  # "ollama", "anthropic", "gemini", "bedrock", "groq", or "openai"

    # --- Provider API keys (free-tier / real connectors) ---
    virustotal_api_key: Optional[str] = None
    abuseipdb_api_key: Optional[str] = None
    otx_api_key: Optional[str] = None
    nvd_api_key: Optional[str] = None  # optional, raises NVD rate limit if set
    abusech_auth_key: Optional[str] = None  # single Auth-Key shared by URLhaus/ThreatFox/MalwareBazaar
    urlscan_api_key: Optional[str] = None
    google_safe_browsing_api_key: Optional[str] = None

    # --- Provider API keys (stub connectors -- add to enable) ---
    hybrid_analysis_api_key: Optional[str] = None
    censys_personal_access_token: Optional[str] = None  # Bearer token for platform.censys.io
    censys_organization_id: Optional[str] = None  # required alongside the PAT by the Platform API
    phishtank_api_key: Optional[str] = None  # optional app_key, raises PhishTank rate limits

    # --- Crawler / OSINT ---
    crawler_user_agent: str = "HorizonGrid/1.0"
    crawler_request_timeout_seconds: int = 15
    crawler_max_results_per_source: int = 5

    # --- Provider execution ---
    provider_timeout_seconds: int = 20
    provider_max_retries: int = 2
    provider_cache_ttl_seconds: int = 3600

    # --- Rate limiting (per user, on the lookup-creation endpoint) ---
    lookup_rate_limit_max_calls: int = 10
    lookup_rate_limit_window_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
