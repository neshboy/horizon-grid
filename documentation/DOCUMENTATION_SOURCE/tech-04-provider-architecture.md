# Provider Architecture

A **provider** is a self-contained connector class in the platform's backend that queries one external data source — a threat-intelligence feed, a vulnerability database, a DNS blocklist, a certificate-transparency log, a sandbox scanner, or an OSINT (open-source intelligence) crawler — for information about a single IOC (indicator of compromise) submitted to a lookup. All 18 providers shipped with the platform are registered in `backend/app/providers/registry.py` (`_ALL_PROVIDERS`) and share one common interface, described below.

## 📋 Table of contents

- [Common Provider Interface](#-common-provider-interface)
- [Concurrent Fan-Out Execution Model](#-concurrent-fan-out-execution-model)
- [Redis Caching Layer](#-redis-caching-layer)
- [The 18 Registered Providers](#-the-18-registered-providers)
- [Wizard Coverage and the "6 Providers with No UI" Discrepancy](#-wizard-coverage-and-the-6-providers-with-no-ui-discrepancy)
- [Runtime IOC Provider Configuration (No Restart)](#-runtime-ioc-provider-configuration-no-restart)
- [The Same Live-Test Pattern, Extended to AI Backends](#-the-same-live-test-pattern-extended-to-ai-backends)

---

## 🔌 Common Provider Interface

Every provider implements the same three-part contract, so the orchestrator (the component that fans a lookup out to providers — see below) never needs provider-specific logic:

- **`supports(ioc_type)`** — a boolean check for whether this provider is eligible to run against the specific kind of indicator submitted. `ioc_type` is one of 33 values in the platform's `IOCType` enum (`app/ioc/types.py`), assigned to the raw input by the IOC-type detector before any provider runs. A provider is only invoked if `supports()` returns true for the lookup's detected type (e.g. `hybrid_analysis` only supports `sha256`; `whois_rdap` supports `domain`, `ipv4`, `ipv6`, and `asn`).
- **`configured`** — a boolean property reporting whether the provider currently has what it needs to run (typically a credential). Some providers are unconditionally configured because they require no credential at all — for example `nvd` has `requires_key = False` and `configured = True` unconditionally. Others require specific fields to be present — for example `censys` is only `configured` when **both** a Personal Access Token and an Organization ID are set; either alone leaves it not configured.
- **`run()`** (via the shared `BaseProvider.run()`) — executes the actual outbound call (HTTP request, DNS query, etc.) and returns a normalized `ProviderResult`. This call is wrapped with a timeout and retry policy applied uniformly across all providers: `provider_timeout_seconds` (default 20 seconds) and `provider_max_retries` (default 2), with exponential backoff implemented via the `tenacity` library (`wait_exponential(multiplier=0.5, max=4)`).

Before `run()` is invoked, each provider call first checks the Redis cache layer (described below); a cache hit skips the outbound call entirely.

## ⚡ Concurrent Fan-Out Execution Model

For a given lookup, `run_all_providers()` (`backend/app/providers/orchestrator.py`) does **not** call providers one after another. It fans out **concurrently** to every registered provider whose `supports(ioc_type)` is true, using `asyncio.create_task` to launch all eligible provider calls at once and `asyncio.as_completed` to consume each result as soon as it finishes, in whatever order calls actually complete. Each provider call independently goes through: Redis cache check → `BaseProvider.run()` (timeout/retry as above) → normalized `ProviderResult`. As each result arrives, it is persisted to Postgres and streamed to the client immediately (rather than the pipeline waiting for every provider to finish before persisting or streaming anything).

The platform's integration test suite exercises this concurrency directly against fake provider stubs (never the real network-hitting connectors), verifying parallel — not sequential — fan-out, isolation of one provider's failure from the others, cache hit/miss behavior, and correct short-circuiting of unsupported or not-configured providers.

[FIGURE: tech-04-provider-architecture-diagram-1.png | Diagram: Concurrent Fan-Out Execution Model]

*"Provider A" and "Provider B" above are illustrative stand-ins for any two of the up to 18 registered providers eligible for a given IOC type — the fan-out is not limited to two.*

## 💾 Redis Caching Layer

Provider results are cached in Redis to avoid repeating identical outbound lookups. The cache key format is `provider_cache:{provider_id}:{ioc_type}:{sha256(value)}` (`app/core/cache.py`), and the time-to-live is `provider_cache_ttl_seconds`, which defaults to 3600 seconds (1 hour). This provider-result cache lives on Redis logical DB index `/0`, kept separate from the Celery broker (`/1`) and Celery result backend (`/2`) that run on the same Redis instance.

Two providers additionally maintain their own cache on top of this (visible in the Notes column of the table below): `cisa_kev` keeps an in-memory cached copy of its catalog with a 1-hour TTL, and `mitre_attack` caches its STIX bundle for 1 hour. These are provider-internal caches, distinct from the shared Redis provider-result cache described above.

## 📋 The 18 Registered Providers

| Provider | Category | Supported IOC types | Key requirement | Notes |
|---|---|---|---|---|
| `virustotal` | threat_intel | ipv4, ipv6, domain, url, hashes | API key | v3 free tier |
| `abuseipdb` | threat_intel | ipv4, ipv6 | API key | v2 |
| `otx` | threat_intel | ipv4, ipv6, domain, hostname, url, hashes | API key | AlienVault OTX |
| `urlhaus` | threat_intel | url, domain, ipv4 | abuse.ch Auth-Key | shares key w/ threatfox/malwarebazaar |
| `threatfox` | threat_intel | ipv4, ipv6, domain, url, md5, sha256 | abuse.ch Auth-Key | shares key |
| `malwarebazaar` | threat_intel | hash types (md5/sha1/sha256/sha512) | abuse.ch Auth-Key | shares key |
| `crtsh` | certificate_intel | domain, tls_certificate | none | Certificate Transparency |
| `nvd` | vulnerability | cve | none (optional key raises rate limit) | NIST NVD v2.0 |
| `cisa_kev` | vulnerability | cve | none | in-memory cached catalog, 1hr TTL |
| `mitre_attack` | threat_intel | mitre_technique | none | STIX bundle, cached 1hr |
| `whois_rdap` | whois | domain, ipv4, ipv6, asn | none | python-whois (domains) + RDAP (IP/ASN) |
| `urlscan` | sandbox | url, domain | API key | urlscan.io; submit-then-poll scan model (`POST /scan/`, then poll `GET /result/{uuid}/`, which returns HTTP 404 while still processing); the poll loop is wall-clock timeboxed and reports a timeout rather than fabricating a result from an incomplete scan |
| `google_safe_browsing` | threat_intel | url, domain | API key | Google Safe Browsing Lookup API v4 (`threatMatches:find`); a confirmed HTTP 200 with an empty/absent `matches` field is the *only* input that may ever produce a "clean" verdict |
| `hybrid_analysis` | sandbox | sha256 only | API key | v2 overview/summary endpoint; MD5/SHA1/URL explicitly unsupported per code comment (deprecated endpoints) |
| `spamhaus` | threat_intel | ipv4, domain | none | DNSBL lookup, no HTTP call (raw DNS) |
| `phishtank` | threat_intel | url | none (optional key raises rate limit) | |
| `censys` | passive_dns | ipv4, ipv6 | Personal Access Token **and** Organization ID both required | Platform API v3 |
| `internet_intelligence` | osint | domain, ipv4, malware_family, threat_actor, campaign, cve, file_name | none | OSINT crawler wrapping GitHub/Reddit/RSS/pastebin sources (`app/crawler/`) |

> [!IMPORTANT]
> **A deliberately tested safety guarantee, specific to these two newest providers:** both `urlscan` and `google_safe_browsing` are built so that a genuine failure — a rejected/invalid API key, an unreachable API, or a rate limit — is always reported as an error or unknown status, never as a false "clean"/"safe" result. `google_safe_browsing.py`'s own module docstring states the invariant directly: an empty or missing `matches` field on a genuine HTTP 200 response is the *only* input that may ever produce a "clean" verdict; every other outcome — a non-200 status, a network error or timeout, or a response body that doesn't parse the way the API contract promises — routes through the same error-handling path, which always sets a `{"verdict": "unknown", ...}` payload rather than anything that could be mistaken downstream for a real clean scan. This was confirmed with a real, live chaos test that supplied deliberately invalid credentials to both providers' real external APIs: the invalid key was rejected with `status=error`, Safe Browsing's own verdict field read `"unknown"` (never `"clean"`), and the investigation's overall verdict was reported as `UNKNOWN` rather than benign or clean.

## 🧙 Wizard Coverage and the "6 Providers with No UI" Discrepancy

The Windows setup **wizard** (`windows/wizard/Setup-Wizard.ps1`, `$ProviderDefs`) presents a Provider Configuration screen listing exactly 8 entries: `virustotal`, `abuseipdb`, `otx`, `abusech` (a single combined entry covering the shared abuse.ch key used by `urlhaus`, `threatfox`, and `malwarebazaar`), `nvd`, `hybrid_analysis`, `censys`, and `phishtank`. Counting the three abuse.ch-backed connectors individually, those 8 wizard entries map to 10 of the platform's 18 backend providers. A sample of the wizard's entries was independently checked against the corresponding provider's code and matched exactly — for example, the wizard's Censys note ("Requires both a Personal Access Token and an Organization ID") matches `censys.py`'s configured check precisely, and the wizard's abuse.ch note ("one free Auth-Key covers all three connectors") matches all three connectors reading the same `abusech_auth_key` setting.

The remaining 8 backend providers split into two different groups, for two different reasons:

- **6 need no credential at all** — `crtsh`, `cisa_kev`, `mitre_attack`, `whois_rdap`, `spamhaus`, and `internet_intelligence` have real, working backend implementations but **do not appear anywhere in the wizard's UI**. This is a documented discrepancy between the wizard and the backend provider registry, but it is flagged as **consistent behavior, not a bug**: all six of these providers have `requires_key = False` — there is no credential for a user to enter in the first place. Because the wizard's Provider Configuration screen exists specifically to collect and test credentials, a provider with nothing to configure has nothing to show there. This is corroborated on the backend side: `backend/app/providers/connection_test.py`'s handler dictionary (which powers the wizard's live "Test" button, `POST /api/v1/providers/{id}/test`) likewise defines no test handler for these six providers, falling back to a message that explicitly identifies them as requiring no credential.
- **2 do need a credential but are still absent from the wizard on both platforms** — `urlscan` and `google_safe_browsing` require an API key to function, yet neither the Windows wizard nor the Linux terminal wizard presents a field for them. Both are configured after install, from the app's own Providers page instead of the setup wizard.

In short: 8 wizard entries cover 10 providers that have a credential-related field to configure — 8 of those (`virustotal`, `abuseipdb`, `otx`, and the three abuse.ch-backed connectors, plus `hybrid_analysis`, `censys`) require a key to function at all, while 2 (`nvd`, `phishtank`) only accept an optional key to raise their rate limit rather than strictly needing one. Of the remaining 8 providers, 6 run unconditionally with no credential of any kind and correctly have no wizard entry and no connection-test handler, while the other 2 (`urlscan`, `google_safe_browsing`) do need a credential but are configured post-install instead of through the wizard.

## 🔄 Runtime IOC Provider Configuration (No Restart)

Everything described above — the `configured` property, the credential fields, and the enabled/disabled state of each of the platform's registered providers — was, prior to this session, entirely `.env`-driven and frozen for the lifetime of the running process: `app/core/config.py`'s `get_settings()` is a process-lifetime `@lru_cache` singleton, so changing a provider's key or toggling it off meant editing `.env` and restarting the Docker containers before the change had any effect.

That has been replaced with a database-backed runtime layer. A new `provider_runtime_configs` table (`backend/app/models/runtime_config.py`, kind `"ioc"`) holds one row per provider — `enabled`, `encrypted_credentials` (Fernet-encrypted, never plaintext), `extra_config`, and the timestamp/outcome of its last connection test. Two endpoints mutate this table: `POST /api/v1/runtime/ioc-providers/{id}` configures a provider's credentials, and `POST /api/v1/runtime/ioc-providers/{id}/enabled` flips it on or off. Neither requires touching `.env` or restarting anything — the very next investigation submitted after the call picks up the change.

Because each provider connector in `registry.py` is instantiated once and reused as a long-lived singleton for the life of the process, mutating a shared instance attribute on that singleton immediately before use would be unsafe: two investigations running concurrently — one started right after an administrator changes a provider's credentials or enabled state, while another is still mid-flight — could race and see each other's configuration. Instead, `run_all_providers()` (`backend/app/providers/orchestrator.py`) takes a single, immutable snapshot of runtime configuration — `{provider_id: {enabled, configured, credentials}}` — once per investigation, at the start of the fan-out, and holds it in a Python `ContextVar` rather than on the provider object itself. Because `asyncio.create_task()` copies the current context into every task it spawns, each concurrent per-provider task launched for that investigation reads from that same frozen snapshot, regardless of what an administrator does to the underlying table while those tasks are still running. Two investigations in flight at once, each with a different configuration for the same provider, therefore never see each other's values — verified with a dedicated concurrency test simulating exactly that scenario.

The provider-availability model also gained a new state to describe this. Previously a provider was either eligible (`supports()` true) and `configured`, or not; `ProviderStatus` now also has a `DISABLED` value, distinct from `NOT_CONFIGURED` — a provider an administrator has deliberately turned off via the enabled/disabled endpoint reports `DISABLED`, while a provider with no credential entered at all still reports `NOT_CONFIGURED`. Both are, in turn, distinguished from "not applicable to this IOC type," so the final-assessment AI prompt never conflates "unavailable" with "checked and found nothing."

Finally, `POST /api/v1/lookup/stream` gained an optional `provider_ids` field: passing a list of provider IDs restricts that one investigation to exactly those providers, regardless of how many are otherwise enabled and configured platform-wide, without affecting any other investigation.

## 🧪 The Same Live-Test Pattern, Extended to AI Backends

The `POST /api/v1/providers/{id}/test` mechanism described above — the one behind each provider's live wizard "Test" button — has a direct counterpart for the AI layer. None of the platform's AI backends had any live connection test until a `POST /api/v1/ai/test` endpoint (`backend/app/api/routes/ai_config.py`, `backend/app/ai/connection_test.py`) was added; it now gives every one of the platform's eleven AI backends (Ollama, Anthropic, AWS Bedrock, Google Gemini, Groq, OpenAI, Kimi, DeepSeek, xAI/Grok, Mistral, and OpenRouter — see the *AI Architecture* chapter for the backends themselves) a real "Test Connection" button in the wizard's AI Configuration screen, mirroring the provider-side pattern rather than introducing a new one.

The same design rule that governs the provider-side tester carries over deliberately: the endpoint always tests the *candidate* credentials currently entered in the form, never the application's stored/active configuration. Because the test path never reads from or writes to the saved config, trying out a not-yet-saved key can never race with — or accidentally disturb — whatever backend and key the running platform is actually using for real investigations.

It is also, deliberately, not a generic pass/fail. The endpoint sends a minimal real request to the backend under test and reports one of several specific, genuine outcomes: authenticated success (with real round-trip latency and the exact model name that replied), invalid/rejected key, rate-limited, model-not-found, network error, or timeout — the same level of specificity the provider-side test handlers already establish, applied to the AI layer for the first time.
