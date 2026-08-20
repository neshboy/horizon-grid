"""Runtime-mutable provider/AI configuration service -- the DB-backed
replacement for "change a value in .env and restart the process."

See app/models/runtime_config.py for the schema, app/core/crypto.py for how
credentials are encrypted at rest, and app/core/runtime_context.py for how
IOC-provider overrides reach individual connectors without a shared-state
race. Every function here opens its own short-lived DB session (via
app.core.db.new_session()) rather than requiring a request-scoped session
threaded through every AI/provider call site -- this keeps the blast radius
of "existing code needs live config" to the few call sites that actually
ask for it (app/ai/service.py's _get_ai_client, app/providers/orchestrator.py's
run_all_providers), not every function transitively above them.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.audit import list_audit_log, record_audit  # noqa: F401 -- re-exported for app/api/routes/runtime.py
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.core.db import new_session
from app.models.runtime_config import ProviderKind, ProviderRuntimeConfig

logger = logging.getLogger(__name__)

AI_BACKENDS = ["ollama", "anthropic", "bedrock", "gemini", "groq", "openai", "kimi", "deepseek", "xai", "mistral", "openrouter"]

# Single source of truth for which credential fields each built-in IOC
# provider needs, and which Settings field currently seeds each one from
# .env on first startup. Also drives the "+ Add Provider" wizard's dynamic
# field list (Phase 18 of the runtime-provider architecture: "the exact
# fields must depend on the selected provider").
IOC_PROVIDER_CREDENTIAL_FIELDS: dict[str, list[str]] = {
    "virustotal": ["api_key"],
    "abuseipdb": ["api_key"],
    "otx": ["api_key"],
    "urlhaus": ["auth_key"],
    "threatfox": ["auth_key"],
    "malwarebazaar": ["auth_key"],
    "nvd": ["api_key"],
    "hybrid_analysis": ["api_key"],
    "censys": ["personal_access_token", "organization_id"],
    "phishtank": ["api_key"],
    "urlscan": ["api_key"],
    "google_safe_browsing": ["api_key"],
    # No credential fields: crtsh, cisa_kev, mitre_attack, whois_rdap,
    # spamhaus, internet_intelligence -- these need no key at all.
}

_ENV_SEED_MAP: dict[str, dict[str, str]] = {
    "virustotal": {"api_key": "virustotal_api_key"},
    "abuseipdb": {"api_key": "abuseipdb_api_key"},
    "otx": {"api_key": "otx_api_key"},
    "urlhaus": {"auth_key": "abusech_auth_key"},
    "threatfox": {"auth_key": "abusech_auth_key"},
    "malwarebazaar": {"auth_key": "abusech_auth_key"},
    "nvd": {"api_key": "nvd_api_key"},
    "hybrid_analysis": {"api_key": "hybrid_analysis_api_key"},
    "censys": {"personal_access_token": "censys_personal_access_token", "organization_id": "censys_organization_id"},
    "phishtank": {"api_key": "phishtank_api_key"},
    "urlscan": {"api_key": "urlscan_api_key"},
    "google_safe_browsing": {"api_key": "google_safe_browsing_api_key"},
}

_AI_ENV_SEED_MAP: dict[str, dict] = {
    "ollama": {"credentials": {"base_url": "ollama_base_url"}, "model": "ollama_model"},
    "anthropic": {"credentials": {"api_key": "anthropic_api_key"}, "model": "anthropic_model_id"},
    "bedrock": {
        "credentials": {
            "bedrock_api_key": "bedrock_api_key",
            "aws_access_key_id": "aws_access_key_id",
            "aws_secret_access_key": "aws_secret_access_key",
            "aws_region": "aws_region",
        },
        "model": "bedrock_model_id",
    },
    "gemini": {"credentials": {"api_key": "gemini_api_key"}, "model": "gemini_model_id"},
    "groq": {"credentials": {"api_key": "groq_api_key"}, "model": "groq_model_id"},
    "openai": {"credentials": {"api_key": "openai_api_key"}, "model": "openai_model_id"},
    "kimi": {"credentials": {"api_key": "kimi_api_key"}, "model": "kimi_model_id"},
    "deepseek": {"credentials": {"api_key": "deepseek_api_key"}, "model": "deepseek_model_id"},
    "xai": {"credentials": {"api_key": "xai_api_key"}, "model": "xai_model_id"},
    "mistral": {"credentials": {"api_key": "mistral_api_key"}, "model": "mistral_model_id"},
    "openrouter": {"credentials": {"api_key": "openrouter_api_key"}, "model": "openrouter_model_id"},
}


def _decrypt_credentials(row: ProviderRuntimeConfig) -> dict:
    raw = decrypt_secret(row.encrypted_credentials or "")
    return json.loads(raw) if raw else {}


def _merge_credentials(row: ProviderRuntimeConfig, incoming: dict) -> dict:
    """Merges `incoming` onto the row's already-stored credentials rather
    than replacing the whole set -- confirmed live as a real bug (not
    hypothetical): the settings UI's per-field inputs start blank and only
    populate `values` for a field the operator actually retypes this
    session (masked existing values are shown only as a placeholder hint,
    never as the real input value -- see ProviderConfigRow.tsx). Saving
    without retyping every field therefore used to send `{}` or a partial
    dict, which a plain overwrite silently turned into "credential cleared"
    -- reproduced end-to-end: Save with no changes flipped a fully working,
    already-tested provider to `configured: false`, and the next real
    investigation failed with "not configured" despite the UI still
    showing a stale "Last test: OK." Only fields actually present in
    `incoming` are changed; anything not sent keeps its stored value.
    There is no "clear a credential" affordance in the UI today, so this
    doesn't remove any reachable capability."""
    if not incoming:
        return _decrypt_credentials(row)
    merged = _decrypt_credentials(row)
    merged.update(incoming)
    return merged


def _is_fully_configured(provider_id: str, creds: dict) -> bool:
    """A provider is only "configured" once EVERY field it declares is
    present -- most providers need exactly one field (any-of would already
    be correct there), but Censys needs both a token AND an organization ID,
    where "any field truthy" would wrongly report configured with only one
    of the two set. Falls back to "any truthy value" for providers not in
    IOC_PROVIDER_CREDENTIAL_FIELDS (e.g. user-added generic providers).

    Bedrock is a special case handled explicitly: aws_region is ALWAYS
    present (it defaults to "us-east-1", not a credential), so "any field
    truthy" would wrongly report Bedrock as configured with region set but
    no actual key/secret -- it needs a bearer token, OR both an access key
    AND a secret, never region alone."""
    if provider_id == "bedrock":
        return bool(creds.get("bedrock_api_key")) or bool(
            creds.get("aws_access_key_id") and creds.get("aws_secret_access_key")
        )
    required_fields = IOC_PROVIDER_CREDENTIAL_FIELDS.get(provider_id)
    if required_fields:
        return all(bool(creds.get(f)) for f in required_fields)
    return bool(creds and any(creds.values()))


def _row_to_public_dict(row: ProviderRuntimeConfig) -> dict:
    """Never returns a real credential value -- only masked previews, for
    API responses and the audit-adjacent "what's configured" UI."""
    creds = _decrypt_credentials(row)
    masked = {k: mask_secret(v) for k, v in creds.items()}
    return {
        "provider_id": row.provider_id,
        "provider_name": row.provider_name,
        "kind": row.kind.value,
        "enabled": row.enabled,
        "is_active": row.is_active,
        "configured": _is_fully_configured(row.provider_id, creds),
        "model_id": row.model_id,
        "extra_config": row.extra_config or {},
        "masked_credentials": masked,
        "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
        "last_test_ok": row.last_test_ok,
        "last_test_message": row.last_test_message,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# --- AI providers -----------------------------------------------------------


async def list_ai_providers() -> list[dict]:
    async with new_session() as db:
        rows = (
            await db.execute(select(ProviderRuntimeConfig).where(ProviderRuntimeConfig.kind == ProviderKind.AI))
        ).scalars().all()
        return [_row_to_public_dict(r) for r in rows]


async def get_active_ai_config() -> Optional[dict]:
    """Returns {"backend", "credentials", "model_id"} for the currently
    active AI provider, or None if no runtime config has been seeded yet
    (caller should fall back to legacy Settings-based behavior)."""
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == ProviderKind.AI,
                    ProviderRuntimeConfig.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"backend": row.provider_id, "credentials": _decrypt_credentials(row), "model_id": row.model_id}


async def get_ai_config(backend: str) -> Optional[dict]:
    """Same shape as get_active_ai_config, for an explicit backend
    regardless of which one is active -- used by the AI-comparison feature
    to run a non-active backend for one investigation without switching the
    platform-wide default."""
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == ProviderKind.AI,
                    ProviderRuntimeConfig.provider_id == backend,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"backend": row.provider_id, "credentials": _decrypt_credentials(row), "model_id": row.model_id}


async def upsert_ai_provider(
    backend: str,
    credentials: dict,
    model_id: Optional[str],
    *,
    actor_user_id=None,
    actor_email: Optional[str] = None,
) -> dict:
    # with_for_update() (below) closes the concurrent-save race for an
    # EXISTING row -- two concurrent saves to the SAME already-configured
    # provider each doing their own read-modify-write, without a lock, used
    # to silently drop whichever change committed first. It does nothing
    # for two concurrent FIRST-EVER saves to the same brand-new provider,
    # though: both find row=None and both try to INSERT, and the table's
    # (kind, provider_id) unique constraint lets exactly one of those
    # commits through -- the other raised IntegrityError to the caller
    # rather than silently losing data, but "visible 500 on an ordinary
    # save" is still a real bug, not an acceptable tradeoff. Retrying the
    # whole read-modify-write once turns that loser into a normal
    # existing-row update instead: by the time it retries, the winner's
    # INSERT has committed, so the retry's SELECT finds a real row (and
    # takes the with_for_update() path) instead of racing another INSERT.
    for attempt in range(2):
        try:
            async with new_session() as db:
                row = (
                    await db.execute(
                        select(ProviderRuntimeConfig)
                        .where(
                            ProviderRuntimeConfig.kind == ProviderKind.AI,
                            ProviderRuntimeConfig.provider_id == backend,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = ProviderRuntimeConfig(kind=ProviderKind.AI, provider_id=backend, provider_name=backend, enabled=True)
                    db.add(row)
                merged = _merge_credentials(row, credentials)
                if backend == "ollama" and merged.get("base_url"):
                    # Real gap fixed: this save path persisted an operator-
                    # supplied Ollama base_url with no validation at all --
                    # assert_safe_outbound_url() was previously only called
                    # from the separate Test-Connection convenience path
                    # (app/api/routes/ai_config.py), which nothing stops an
                    # operator from skipping entirely before hitting Save.
                    # Checked post-merge (not against the raw `credentials`
                    # argument) since a partial save that omits base_url
                    # still ends up persisting whatever value is already
                    # merged in from the stored row.
                    from app.core.url_safety import assert_safe_outbound_url

                    assert_safe_outbound_url(merged["base_url"])
                row.encrypted_credentials = encrypt_secret(json.dumps(merged)) if merged else ""
                if model_id is not None:
                    row.model_id = model_id
                row.updated_by = actor_user_id
                await db.commit()
                await db.refresh(row)
                result = _row_to_public_dict(row)
            break
        except IntegrityError:
            if attempt == 1:
                raise
    await record_audit("ai_provider.configure", f"Configured AI provider '{backend}'.", actor_user_id, actor_email)
    return result


async def set_active_ai_backend(backend: str, *, actor_user_id=None, actor_email: Optional[str] = None) -> None:
    if backend not in AI_BACKENDS:
        raise ValueError(f"Unknown AI backend {backend!r}")
    async with new_session() as db:
        rows = (
            await db.execute(select(ProviderRuntimeConfig).where(ProviderRuntimeConfig.kind == ProviderKind.AI))
        ).scalars().all()
        previous = next((r.provider_id for r in rows if r.is_active), None)
        found = False
        for r in rows:
            r.is_active = r.provider_id == backend
            found = found or r.is_active
        if not found:
            db.add(ProviderRuntimeConfig(kind=ProviderKind.AI, provider_id=backend, provider_name=backend, enabled=True, is_active=True))
        await db.commit()
    await record_audit(
        "ai_provider.activate", f"Changed active AI provider: {previous or '(none)'} -> {backend}.", actor_user_id, actor_email
    )


async def record_ai_test_result(backend: str, ok: bool, message: str) -> None:
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == ProviderKind.AI, ProviderRuntimeConfig.provider_id == backend
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProviderRuntimeConfig(kind=ProviderKind.AI, provider_id=backend, provider_name=backend, enabled=True)
            db.add(row)
        row.last_test_at = datetime.now(timezone.utc)
        row.last_test_ok = ok
        row.last_test_message = message[:500]
        await db.commit()
    await record_audit(
        "ai_provider.test", f"Test connection for '{backend}': {'succeeded' if ok else 'failed'}."
    )


# --- IOC providers -----------------------------------------------------------


async def list_ioc_providers() -> list[dict]:
    async with new_session() as db:
        rows = (
            await db.execute(select(ProviderRuntimeConfig).where(ProviderRuntimeConfig.kind == ProviderKind.IOC))
        ).scalars().all()
        return [_row_to_public_dict(r) for r in rows]


async def get_ioc_provider_snapshot() -> dict[str, dict]:
    """One query, returns {provider_id: {"enabled", "configured", "credentials"}}
    for every IOC provider -- called ONCE per investigation by
    app/providers/orchestrator.py's run_all_providers() and fed into
    app/core/runtime_context.set_provider_overrides() so every concurrent
    provider task in that investigation sees a single consistent snapshot."""
    async with new_session() as db:
        rows = (
            await db.execute(select(ProviderRuntimeConfig).where(ProviderRuntimeConfig.kind == ProviderKind.IOC))
        ).scalars().all()
        snapshot = {}
        for r in rows:
            creds = _decrypt_credentials(r)
            snapshot[r.provider_id] = {
                "enabled": r.enabled,
                "configured": _is_fully_configured(r.provider_id, creds),
                "credentials": creds,
            }
        return snapshot


async def upsert_ioc_provider(
    provider_id: str,
    provider_name: str,
    credentials: dict,
    extra_config: Optional[dict] = None,
    *,
    actor_user_id=None,
    actor_email: Optional[str] = None,
) -> dict:
    # with_for_update() closes the concurrent-save race for an EXISTING row
    # (see upsert_ai_provider's identical comment); the IntegrityError
    # retry below closes the remaining gap for two concurrent FIRST-EVER
    # saves to the same brand-new provider, which would otherwise both try
    # to INSERT and one would surface a visible 500 instead of just
    # completing as a normal save.
    for attempt in range(2):
        try:
            async with new_session() as db:
                row = (
                    await db.execute(
                        select(ProviderRuntimeConfig)
                        .where(
                            ProviderRuntimeConfig.kind == ProviderKind.IOC,
                            ProviderRuntimeConfig.provider_id == provider_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = ProviderRuntimeConfig(kind=ProviderKind.IOC, provider_id=provider_id, provider_name=provider_name, enabled=True)
                    db.add(row)
                row.provider_name = provider_name or row.provider_name
                merged = _merge_credentials(row, credentials)
                row.encrypted_credentials = encrypt_secret(json.dumps(merged)) if merged else ""
                if extra_config is not None:
                    row.extra_config = extra_config
                row.updated_by = actor_user_id
                await db.commit()
                await db.refresh(row)
                result = _row_to_public_dict(row)
            break
        except IntegrityError:
            if attempt == 1:
                raise
    await record_audit("ioc_provider.configure", f"Configured IOC provider '{provider_id}'.", actor_user_id, actor_email)
    return result


async def set_ioc_provider_enabled(
    provider_id: str, enabled: bool, *, actor_user_id=None, actor_email: Optional[str] = None
) -> None:
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == ProviderKind.IOC, ProviderRuntimeConfig.provider_id == provider_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProviderRuntimeConfig(kind=ProviderKind.IOC, provider_id=provider_id, provider_name=provider_id, enabled=enabled)
            db.add(row)
        else:
            row.enabled = enabled
        await db.commit()
    await record_audit(
        "ioc_provider.enable" if enabled else "ioc_provider.disable",
        f"{'Enabled' if enabled else 'Disabled'} IOC provider '{provider_id}'.",
        actor_user_id,
        actor_email,
    )


async def record_ioc_test_result(provider_id: str, ok: bool, message: str) -> None:
    async with new_session() as db:
        row = (
            await db.execute(
                select(ProviderRuntimeConfig).where(
                    ProviderRuntimeConfig.kind == ProviderKind.IOC, ProviderRuntimeConfig.provider_id == provider_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProviderRuntimeConfig(kind=ProviderKind.IOC, provider_id=provider_id, provider_name=provider_id, enabled=True)
            db.add(row)
        row.last_test_at = datetime.now(timezone.utc)
        row.last_test_ok = ok
        row.last_test_message = message[:500]
        await db.commit()
    await record_audit(
        "ioc_provider.test", f"Test connection for '{provider_id}': {'succeeded' if ok else 'failed'}."
    )


# --- Seed from .env (backward compatibility for existing installs) --------


async def seed_from_env_if_empty() -> bool:
    """Runs once at backend startup (see app/main.py). If provider_runtime_configs
    is completely empty (a first boot of this feature on an existing or new
    install), populates it from whatever is currently in Settings/.env, so
    upgrading to this feature never silently drops an administrator's
    already-configured keys. Idempotent and safe to call on every startup --
    it only acts when the table is empty. Returns True if it seeded anything."""
    from app.core.config import get_settings

    async with new_session() as db:
        existing = (await db.execute(select(ProviderRuntimeConfig.id).limit(1))).first()
        if existing is not None:
            return False

        settings = get_settings()
        for backend, spec in _AI_ENV_SEED_MAP.items():
            creds = {k: getattr(settings, field, None) for k, field in spec["credentials"].items()}
            creds = {k: v for k, v in creds.items() if v}
            model_id = getattr(settings, spec["model"], None)
            db.add(
                ProviderRuntimeConfig(
                    kind=ProviderKind.AI,
                    provider_id=backend,
                    provider_name=backend,
                    enabled=True,
                    is_active=(backend == settings.ai_backend),
                    encrypted_credentials=encrypt_secret(json.dumps(creds)) if creds else "",
                    model_id=model_id,
                )
            )

        from app.providers.registry import get_all_providers

        for provider in get_all_providers():
            field_map = _ENV_SEED_MAP.get(provider.provider_id, {})
            creds = {k: getattr(settings, field, None) for k, field in field_map.items()}
            creds = {k: v for k, v in creds.items() if v}
            db.add(
                ProviderRuntimeConfig(
                    kind=ProviderKind.IOC,
                    provider_id=provider.provider_id,
                    provider_name=provider.provider_name,
                    enabled=True,
                    encrypted_credentials=encrypt_secret(json.dumps(creds)) if creds else "",
                )
            )
        await db.commit()

    logger.info("Seeded provider_runtime_configs from .env (first boot of runtime-provider feature).")
    await record_audit("system.seed", "Seeded runtime provider configuration from existing .env values.")
    return True
