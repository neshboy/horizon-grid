# Provider and AI Backend Integration Reference

This chapter is the exhaustive technical reference for every external integration the backend calls: the 18 registered IOC (Indicator of Compromise) providers in `backend/app/providers/` and the 11 interchangeable AI backends in `backend/app/ai/`. Where the *Provider Architecture* and *AI Architecture* chapters explain how the fan-out, caching, credential-override, and grounding mechanisms work, this chapter documents **what each individual integration actually calls** — real endpoint URLs, auth schemes, credential fields, supported IOC types, rate-limit/error detection, and the shape of the normalized data each one returns. All facts are drawn directly from the connector source files cited inline; nothing below is inferred from documentation or docstrings alone.

## 1. Shared Provider Contract

Every provider subclasses `BaseProvider` (`app/providers/base.py:80-184`), which wraps `fetch()` with three short-circuits before any outbound call is made — disabled, unsupported IOC type, and not-configured (`base.py:97-146`) — and normalizes every outbound-call exception into one of a fixed set of `ProviderStatus` values. Two mappings are uniform across **all** real HTTP-based providers unless a connector explicitly overrides them:

- `httpx.HTTPStatusError` with status **429, 403, or 509** → `ProviderStatus.RATE_LIMITED` (`base.py:149-155`; 509 is called out at `base.py:152` as PhishTank's documented over-limit code, since it is not a widely-recognized rate-limit status elsewhere).
- Any other non-2xx status raised via `response.raise_for_status()` → `ProviderStatus.ERROR`.

Retries and timeouts are applied one layer above, in the orchestrator (`app/providers/orchestrator.py:26,47-61`): `asyncio.wait_for` per call, with `tenacity`-based retry limited to `httpx.ConnectError`, `httpx.ReadTimeout`, and `httpx.PoolTimeout` — a bad-status response is never retried, only a genuinely failed connection. Sixteen providers are registered in `app/providers/registry.py:29-46`, including the OSINT crawler described in §3.

## 2. IOC Providers, One by One

### 2.1 VirusTotal — `virustotal`
- **File**: `app/providers/virustotal.py`. Category `THREAT_INTEL`. IOC types: `ipv4`, `ipv6`, `domain`, `url`, and every hash type (`md5`/`sha1`/`sha256`/`sha512`) (`:17-20`).
- **Credential**: `requires_key=True`; field `api_key` → `settings.virustotal_api_key`, sent as header `x-apikey` (`:21,24-26,44-45`).
- **Endpoint**: base `https://www.virustotal.com/api/v3` (`:22`); per-type path — `/files/{hash}`, `/ip_addresses/{ip}`, `/domains/{domain}`, `/urls/{base64url(ioc)}` (`:28-40`).
- **Normalized data**: `verdict` (derived from `last_analysis_stats`), `detection_ratio`, `malicious_count`, `suspicious_count`, `total_engines`, `reputation_score`, `last_analysis_date`, `tags`, plus type-specific fields — hashes get `file_type`/`file_names`/`md5`/`sha1`/`sha256`/`first_seen`/`last_seen`/`malware_families`; IPs get `asn`/`as_owner`/`country`/`network`; domains get `resolved_ips`/`registrar`/`creation_date`; URLs get `final_url`/`title` (`:63-133`).
- **Errors**: HTTP 404 → `NO_DATA` (`:49-58`); everything else falls through to the shared 429/403/509 mapping.

### 2.2 AbuseIPDB — `abuseipdb`
- **File**: `app/providers/abuseipdb.py`. Category `THREAT_INTEL`. IOC types: `ipv4`, `ipv6` (`:16-19`).
- **Credential**: `requires_key=True`; field `api_key` → `settings.abuseipdb_api_key`, header `Key` (`:20,25,29-30`).
- **Endpoint**: base `https://api.abuseipdb.com/api/v2`, `GET /check` (`:21,33`).
- **Normalized data**: `verdict` (malicious if abuse-confidence score > 25, else derived from report count), `reputation_score`/`abuse_confidence_score`, `total_reports`, `num_distinct_users`, `is_whitelisted`, `usage_type`, `country_code`, `isp`, `domain`, `hostnames`, `is_tor`, `last_seen`, `reports` (`:60-85`).
- **Errors**: HTTP 404 → `NO_DATA` (`:34-43`); an empty result entry is also mapped to `NO_DATA` (`:48-58`).

### 2.3 AlienVault OTX — `otx`
- **File**: `app/providers/otx.py`. Category `THREAT_INTEL`. IOC types: `ipv4`, `ipv6`, `domain`, `hostname`, `url`, plus all hash types (`:27-30`).
- **Credential**: `requires_key=True`; field `api_key` → `settings.otx_api_key`, header `X-OTX-API-KEY` (`:31,36,46-47`).
- **Endpoint**: base `https://otx.alienvault.com/api/v1`; `GET /indicators/{section}/{indicator}/general`, where `section` is mapped per IOC type (`:17-23,32,38-50`).
- **Normalized data**: `verdict` (malicious if `pulse_count > 0`, else unknown), `pulse_count`, `malware_families`, `threat_actors`, `campaigns`, `tags`, `references`, `reputation`, `first_seen`/`last_seen`, plus type-specific fields (IP: `asn`/`country`; domain/hostname: `alexa`/`whois`; URL: `resolved_domains`/`hostname`; hash: `file_type`) (`:104-164`).
- **Errors**: 404 → `NO_DATA` (`:53-62`); zero pulses is *also* forced to `NO_DATA` rather than a "clean" verdict (`:70-80`).

### 2.4 URLhaus (abuse.ch) — `urlhaus`
- **File**: `app/providers/urlhaus.py`. Category `THREAT_INTEL`. IOC types: `url`, `domain`, `ipv4` (`:18-21`).
- **Credential**: `requires_key=True`; field `auth_key` → `settings.abusech_auth_key`, header `Auth-Key` (`:22,27,31`) — this key is shared with ThreatFox and MalwareBazaar below (one abuse.ch key covers all three).
- **Endpoint**: base `https://urlhaus-api.abuse.ch/v1`; `POST /url/` (form field `url`) for URL lookups, `POST /host/` (form field `host`) for domain/IPv4 lookups (`:23,33-38`).
- **Normalized data**: URL lookup returns `verdict:"malicious"`, `query_status`, `url_status`, `threat`, `tags`, `host`, `first_seen`/`last_seen`, `related_hashes`, `payloads`, `blacklists` (`:84-99`); host lookup returns `verdict` (malicious if any URLs found, else unknown), `query_status`, `url_count`, `first_seen`, `related_urls`, `threat`, `tags`, `blacklists` (`:101-116`).
- **Errors**: 404 → `NO_DATA`; abuse.ch's own `query_status` field is interpreted by the shared `map_query_status()` helper (`app/providers/abusech.py:15,18-29`): `"ok"` → OK, `{"no_api_key","invalid_api_key","unauthorized"}` → `ERROR` (key rejected), anything else → `NO_DATA` (`urlhaus.py:55-67`).

### 2.5 ThreatFox (abuse.ch) — `threatfox`
- **File**: `app/providers/threatfox.py`. Category `THREAT_INTEL`. IOC types: `ipv4`, `ipv6`, `domain`, `url`, `md5`, `sha256` (`:18-28`).
- **Credential**: same shared abuse.ch key (`auth_key`, header `Auth-Key`) (`:29,34,38`).
- **Endpoint**: base `https://threatfox-api.abuse.ch/api/v1/`; `POST` JSON body `{"query":"search_ioc","search_term":...}` (`:30,39-41`).
- **Normalized data**: `verdict:"malicious"`, `ioc_type`, `threat_type` (single value or list), `malware_families`, `confidence_level` (max across matches), `first_seen`/`last_seen`, `tags`, `reference`, `matches` (raw matched entries) (`:88-111`).
- **Errors**: 404 → `NO_DATA`; `query_status` handled via the same shared `map_query_status()` (`:42-72`).

### 2.6 MalwareBazaar (abuse.ch) — `malwarebazaar`
- **File**: `app/providers/malwarebazaar.py`. Category `THREAT_INTEL`. IOC types: all hash types — `md5`/`sha1`/`sha256`/`sha512` (`:18-21`).
- **Credential**: same shared abuse.ch key (`auth_key`, header `Auth-Key`) (`:22,27,31`).
- **Endpoint**: base `https://mb-api.abuse.ch/api/v1/`; `POST` form `{"query":"get_info","hash":...}` (`:23,32-34`).
- **Normalized data**: `verdict:"malicious"`, `file_type`/`file_type_mime`/`file_size`/`file_name`, `malware_families` (from the `signature` field), `tags`, `delivery_method`, `first_seen`/`last_seen`, `md5`/`sha1`/`sha256`, `downloads`/`uploads` (from `intelligence`), `vendor_intel` (`:82-105`).
- **Errors**: 404 → `NO_DATA`; `query_status` via `map_query_status()`, with an additional rule that "ok" plus zero returned entries is forced to `NO_DATA` (`:48-65`).

### 2.7 crt.sh — `crtsh`
- **File**: `app/providers/crtsh.py`. Category `CERTIFICATE_INTEL`. IOC types: `domain`, `tls_certificate` (`:27-30`).
- **Credential**: `requires_key=False`, always configured (`:31,34-36`).
- **Endpoint**: base `https://crt.sh`; `GET /?q={domain}&output=json` (`:32,43-45`).
- **Normalized data**: `certificates` (up to the 25 most recent, each with `issuer_name`, `common_name`, `name_value` — sorted, lowercased names — `not_before`/`not_after`, `serial_number`, `id`, `entry_timestamp`), `certificate_count` (total entries returned), `related_domains` (subdomains extracted from SAN names) (`:100-138`).
- **Errors**: 404 → `NO_DATA` (`:46-55`). Notably, malformed or non-list JSON is caught and degraded to `NO_DATA` rather than raised — the code comment explains crt.sh is known to be slow/flaky and to occasionally emit malformed JSON (`:58-84`).

### 2.8 NIST NVD — `nvd`
- **File**: `app/providers/nvd.py`. Category `VULNERABILITY`. IOC type: `cve` (`:18-21`).
- **Credential**: `requires_key=False` — works unauthenticated at roughly 5 requests/30s; an optional `api_key` → `settings.nvd_api_key`, sent as header `apiKey`, raises the ceiling to roughly 50 requests/30s (`:22,27-28,32-35`).
- **Endpoint**: base `https://services.nvd.nist.gov/rest/json/cves/2.0`; `GET` with `params={"cveId":...}` (`:23,37`).
- **Normalized data**: `verdict` (derived from CVSS severity), `cve_id`, `cvss_score`/`cvss_severity`/`cvss_vector` (CVSS v3.1 preferred, then v3.0, then v2; "Primary" scoring source preferred when multiple exist, `:80-93`), `description`, `vuln_status`, `cwes`, `references`, `configurations`, `first_seen` (published)/`last_seen` (lastModified) (`:106-137`).
- **Errors**: 404 → `NO_DATA`; an empty `vulnerabilities` list → `NO_DATA`; other statuses fall through to the shared mapping (`:38-62`).

### 2.9 CISA Known Exploited Vulnerabilities — `cisa_kev`
- **File**: `app/providers/cisa_kev.py`. Category `VULNERABILITY`. IOC type: `cve` (`:26-29`).
- **Credential**: `requires_key=False`, always configured (`:30,33-35`).
- **Endpoint**: fetches the full catalog JSON once from `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json` and caches it **in-memory** for up to 3600 seconds, guarded by an `asyncio.Lock` so concurrent lookups don't trigger duplicate fetches (`:17-22,37-55`).
- **Normalized data**: `verdict:"malicious"` (a CVE only appears here if it is confirmed actively exploited), `vulnerability_name`, `vendor_project`, `product`, `date_added`, `short_description`, `required_action`, `due_date`, `known_ransomware_campaign_use`, `notes`, `first_seen` (`:72-84`).
- **Errors**: catalog-fetch failures propagate via `raise_for_status()`; a CVE absent from the catalog → `NO_DATA` (`:61-70`).

### 2.10 MITRE ATT&CK — `mitre_attack`
- **File**: `app/providers/mitre_attack.py`. Category `THREAT_INTEL`. IOC type: `mitre_technique` (`:71-74`).
- **Credential**: `requires_key=False`, `configured=True` always (`:75-76`).
- **Endpoint**: downloads the full ~30MB STIX 2.1 enterprise-attack bundle from `https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json`, cached for 3600 seconds behind an `asyncio.Lock` (`:26-31,46-67`).
- **Normalized data**: `technique_id`, `name`, `description`, `tactics` (sorted kill-chain phase names), `mitre_techniques`, `x_mitre_platforms`, `x_mitre_data_sources`, `is_subtechnique`, `revoked`, `deprecated` (`:101-112`).
- **Errors**: a technique ID absent from the bundle's index → `NO_DATA` (`:86-95`); bundle-fetch errors fall through to `raise_for_status()` (`:62`).

### 2.11 WHOIS / RDAP — `whois_rdap`
- **File**: `app/providers/whois_rdap.py`. Category `WHOIS`. IOC types: `domain` (via WHOIS), `ipv4`/`ipv6`/`asn` (via RDAP) (`:43-46`).
- **Credential**: `requires_key=False` (`:47,50-51`).
- **Mechanism**: domain lookups run the blocking `python-whois` library (`pywhois.whois`) inside `asyncio.to_thread`, with a 10-second socket timeout (`:36,60-67`). IP/ASN lookups use RDAP against `https://rdap.org/ip/{ip}` or `.../autnum/{asn}`, which bootstraps to whichever Regional Internet Registry actually holds the record (`:38,141-153`).
- **Normalized data**: domain — `registrar`, `creation_date`/`expiration_date`/`updated_date` (ISO strings), `name_servers`, `registrant`, `registrant_country`, `status`, `emails`, `first_seen`/`last_seen` (`:113-125`). RDAP — `handle`, `name`, `country`, `start_address`/`end_address`, `start_autnum`/`end_autnum`, `ip_version`, `type`, `status`, `entities` (mapped vCard roles), `registrant`, `asn` (`:176-193`).
- **Errors**: a socket-level failure maps to `TIMEOUT` for `socket.timeout` or `ERROR` for anything else (connection refused/reset, `gaierror`) (`:69-81`); an unparseable TLD WHOIS response (`PywhoisError`) → `NO_DATA` (`:82-94`); a parsed record with no `domain_name` field → `NO_DATA` (`:96-105`); RDAP 404 → `NO_DATA` (`:154-163`).

### 2.12 Hybrid Analysis (Falcon Sandbox) — `hybrid_analysis`
- **File**: `app/providers/stubs/hybrid_analysis.py`. Category `SANDBOX`. IOC type: **`sha256` only** — per the module docstring, MD5/SHA1 are unsupported because the replacement endpoint accepts only SHA256, and URL support was removed because the correct request shape for it could not be confirmed (`:1-17,28-31`).
- **Credential**: `requires_key=True`; field `api_key` → `settings.hybrid_analysis_api_key`, header `api-key`; also always sends `user-agent: "Falcon Sandbox"` because Hybrid Analysis rejects generic user agents (`:32,40,44-49`).
- **Endpoint**: base `https://hybrid-analysis.com/api/v2` (bare domain, confirmed live — `www.` 301-redirects) (`:33-36`); `GET /overview/{sha256}/summary` (`:52`).
- **Normalized data**: `verdict`, `threat_score`, `av_detect_pct` (from `multiscan_result`), `sha256`, `submitted_at`, `first_seen` (= submitted_at) / `last_seen` (= last_multi_scan) (`:80-90`).
- **Errors**: 400 or 404 → `NO_DATA` (`:53-62`); other statuses fall through to the shared mapping.

### 2.13 Spamhaus DBL/ZEN — `spamhaus`
- **File**: `app/providers/stubs/spamhaus.py`. Category `THREAT_INTEL`. IOC types: `ipv4`, `domain` (`:54-57`).
- **Credential**: `requires_key=False`, `configured=True` (`:58-59`).
- **Mechanism**: this connector makes **no HTTP call at all** — it performs plain DNS A-record lookups via `loop.getaddrinfo()` against `*.zen.spamhaus.org` (IP, octet-reversed) or `*.dbl.spamhaus.org` (domain) (`:61-76`).
- **Normalized data**: `verdict` ("clean" if NXDOMAIN/no answer, "malicious" if any A-record hit that isn't a query-error code, "unknown" if every returned code is a query-error code), `listed` (bool), `list` (`"ZEN"` or `"DBL"`), `query`, and on a real listing, `return_codes` plus `listing_reason` (decoded from the published Spamhaus ZEN/DBL return-code tables) (`:81-131`).
- **"Errors"**: `socket.gaierror` (NXDOMAIN) is caught and treated as "not listed" — a normal clean result, not an error. Because there is no HTTP call, the 429/403/509 rate-limit mapping described in §1 does not apply to this connector.
- **Real bug fixed (v0.2.2)**: Spamhaus's two shared query-error codes (`127.255.255.254` "public/open resolver not permitted", `127.255.255.255` "excessive queries, temporarily blocked") were only documented in `_ZEN_CODES`, and — more importantly — were never actually distinguished from a real listing in the classification logic itself: ANY non-empty DNS answer, including these, was reported as `verdict: "malicious"`. Confirmed live against a real Docker container (a common deployment shape, not unique to any one environment): every domain lookup got `127.255.255.254` back (Spamhaus rejecting the container's default DNS resolver as public/shared), so every domain — including `example.org`, IANA's reserved, universally-benign example domain — was reported malicious with zero real finding behind it. Fixed with a `_QUERY_ERROR_CODES` set checked before classification: a response containing ONLY error codes now reports `status=ERROR`, `verdict="unknown"`, `listed=False`, with a clear `error_message` explaining the query was rejected; a real listing found alongside an error code still correctly reports `malicious` (the real evidence isn't discarded just because an unrelated error code was also present). `_DBL_CODES` also gained the two error codes for documentation completeness, confirmed live to appear on DBL (domain) lookups too, not only ZEN (IP) lookups as previously assumed.

### 2.14 PhishTank — `phishtank`
- **File**: `app/providers/stubs/phishtank.py`. Category `THREAT_INTEL`. IOC type: `url` (`:19-22`).
- **Credential**: `requires_key=False` — the key is optional and only raises the rate limit; field `api_key` → `settings.phishtank_api_key`, sent as form field `app_key` when present (`:23-24,28-32`).
- **Endpoint**: base `https://checkurl.phishtank.com/checkurl/`; `POST` form `{"url":..., "format":"json"}` (`:25,34`).
- **Normalized data**: `verdict` (malicious if `valid`, else suspicious), `in_database`, `valid`, `verified`, `verified_at`, `submission_time`, `phish_id`, `phish_detail_page` (`:64-73`).
- **Errors**: 404 → `NO_DATA`; `results.in_database == False` → `NO_DATA`; other non-2xx statuses fall through to the shared mapping — this is the connector that motivated including HTTP **509** in the shared rate-limit set, since it is PhishTank's documented over-limit status code (`:35-59`, `base.py:152`).

### 2.15 Censys — `censys`
- **File**: `app/providers/stubs/censys.py`. Category `PASSIVE_DNS`. IOC types: `ipv4`, `ipv6` (`:24-27`).
- **Credential**: `requires_key=True`; **both** a Personal Access Token (Bearer auth) and an Organization ID (header `X-Organization-ID`) are required for `configured=True` — either alone is not sufficient (`:28,33-36,40-46`).
- **Endpoint**: base `https://platform.censys.io`; `GET /v3/global/asset/host/{ip}` (`:29,49-51`).
- **Normalized data**: `verdict:"unknown"` (Censys is a passive-DNS/asset-inventory source, not a verdict provider), `services` (list of `port`/`protocol`/`service_name`), `location` (`city`/`province`/`country`/`country_code`), `autonomous_system`, `asn`, `as_owner`, `last_seen` (`:78-91`).
- **Errors**: 404 → `NO_DATA`; other statuses fall through to the shared mapping.

### 2.16 urlscan.io — `urlscan`
- **File**: `app/providers/urlscan_io.py`. Category `SANDBOX`. IOC types: `url`, `domain` (`:39-41`).
- **Credential**: `requires_key=True`; field `api_key`, header `API-Key` (`:41,45`). Not offered on either installer's setup wizard (§ below) — configured after install from the app's own Providers page.
- **Endpoint**: `POST https://urlscan.io/api/v1/scan/` to submit, then `GET https://urlscan.io/api/v1/result/{uuid}/` polled every 3 seconds until ready or a 60-second wall-clock timeout (`_TIMEOUT_SECONDS`/`_POLL_INTERVAL_SECONDS`) elapses — a real, live sandbox run per lookup, not a cached-database check like most other providers in this chapter.
- **Errors**: the poll endpoint returns HTTP 404 while the scan is still processing (expected, not an error) and HTTP 200 with the full result once ready; 401/403 on either the submit or poll request are treated as "bad API key," not rate limiting — deliberately not routed through `BaseProvider.run()`'s generic mapping (which treats 403 as `RATE_LIMITED` for every other connector, matching PhishTank's documented behavior) because urlscan.io's own 403 semantics are different. A scan not ready by the timeout → `ProviderStatus.TIMEOUT`, never a fabricated result from an incomplete scan.

### 2.17 Google Safe Browsing — `google_safe_browsing`
- **File**: `app/providers/google_safe_browsing.py`. Category `THREAT_INTEL`. IOC types: `url`, `domain` (`:31-33`).
- **Credential**: `requires_key=True`; field `api_key`, sent as the `key` query parameter on the Lookup API v4 call (`:33`). Not offered on either installer's setup wizard (§ below) — configured after install from the app's own Providers page.
- **Endpoint**: `POST https://safebrowsing.googleapis.com/v4/threatMatches:find?key=<API_KEY>`, checking against `MALWARE`, `SOCIAL_ENGINEERING`, `UNWANTED_SOFTWARE`, and `POTENTIALLY_HARMFUL_APPLICATION` threat types (`_THREAT_TYPES`).
- **Normalized data**: a "clean" verdict only when the response is a genuine HTTP 200 with an empty/missing `matches` field — this is the *only* input path that can produce a safe result. Every other outcome (non-200 status, network error/timeout, or a response that doesn't parse the way the API contract promises) returns early via the module's own `_error()` helper, which always sets `data={"verdict": "unknown", ...}` — there is no code path from "the request failed" to a result that looks clean, a deliberately pinned invariant (module docstring; covered by `test_google_safe_browsing.py`'s `test_*_never_looks_like_safe` tests).

## 3. Internet Intelligence Collector (OSINT Crawler-as-Provider) — `internet_intelligence`

- **File**: `app/crawler/collector.py`. Category `OSINT`. IOC types: `domain`, `ipv4`, `malware_family`, `threat_actor`, `campaign`, `cve`, `file_name` — deliberately limited to free-text-searchable types; the module docstring notes that "raw network atoms like ja3 hashes or mutexes are excluded" (`:36-44,50-52`).
- **Credential**: `requires_key=False` — every underlying source is unauthenticated (`:54,58-59`).
- **Mechanism**: registered as an ordinary `BaseProvider`, but instead of one `base_url` it fans out **concurrently** to four independent sub-source modules under `app/crawler/sources/` (`:28,46,65-66`):

| Sub-source | Endpoint | Auth | Rate-limit detection |
|---|---|---|---|
| `github.py` | `GET api.github.com/search/repositories` and `/search/code` | none (optional unwired `GITHUB_TOKEN` env var would raise the ceiling 10→30 req/min, but is not read by `app/core/config.py`) | HTTP 403 or 429 → `SourceRateLimitedError` (GitHub's Search API uses 403 for rate limiting, not only auth); throttled client-side via `AsyncMinIntervalLimiter` (6s) |
| `reddit.py` | `GET www.reddit.com/search.json` | none, but requires a real `User-Agent` (`settings.crawler_user_agent`) or Reddit blocks the request | HTTP 429 → `SourceRateLimitedError`; throttled client-side (1.1s min interval) |
| `rss_news.py` | 8 hardcoded public security-news RSS feeds (BleepingComputer, The Hacker News, Krebs on Security, Talos, GCP TI blog, Microsoft Security blog, CrowdStrike blog, Unit42), fetched concurrently, parsed with `feedparser`, keyword-filtered | none | none — any per-feed exception is swallowed to `[]`, never raised |
| `pastebin_search.py` | `GET psbdmp.ws/api/v3/search/{query}` (unofficial, unauthenticated) | none | none — non-200 or any exception → `[]`, never raised |

- **Normalized data**: `osint_findings` (a deduplicated-by-URL merged list of `{title, url, snippet, published_at, source}`, capped at `crawler_max_results_per_source * 4`), `source_count` (per-source hit counts), `total_findings`, `rate_limited_sources` (`collector.py:68-110`).
- **Status resolution**: the collector maps "all four sources came back empty and at least one was rate-limited" → `ProviderStatus.RATE_LIMITED`; "all empty, none rate-limited" → `NO_DATA`; any findings at all → `OK` (`:112-133`).

## 4. AI Backends

All eleven backend clients expose an identical async method, `call_claude_json(system_prompt, user_prompt, json_schema, tool_name="emit_result", max_tokens=None) -> dict`, which is what lets `app/ai/service.py` swap backends with zero branching logic (`service.py:43-53,56-99`). Defaults for every credential/model/URL below live in `app/core/config.py:44-80`; at call time, `_build_client()` (`service.py:56-99`) constructs a **fresh** client per call using whichever credentials the active runtime-config row (or an explicit override) supplies — proving these constructor parameters are live override points a caller genuinely exercises, not dead code.

### 4.1 Ollama — `ollama_client.py`
- **Endpoint**: `POST {base_url}/api/chat`; default `base_url` = `http://host.docker.internal:11434` (`:15-17`, `config.py:76`, used at `:91`).
- **Auth**: none — local server.
- **Default model**: `settings.ollama_model = "llama3.2:3b"` (`config.py:77`).
- **Structured output**: the request's `format` field is set to the JSON Schema itself (grammar-constrained decoding, not tool-calling), after flattening `$ref`/`$defs` via `inline_refs()` since Ollama's grammar compiler doesn't reliably resolve refs (`:6-10,30,76`).
- **Constructor overrides**: `OllamaClient(base_url=None, model=None, max_tokens=None)` — all three fall back to `get_settings()` values when omitted (`:39-52`).
- **Errors**: `httpx.ConnectError` → `RuntimeError("Could not reach Ollama...")`; `httpx.TimeoutException` after 120s → `RuntimeError`; HTTP status ≥400 → `RuntimeError` with status and body; a non-JSON or non-dict response body → `RuntimeError` (`:89-126`).

### 4.2 Anthropic — `anthropic_client.py`
- **Endpoint**: `POST https://api.anthropic.com/v1/messages` (`_API_BASE`, `:21`).
- **Auth**: header `x-api-key`, plus `anthropic-version: 2023-06-01` (`:22,54-57`).
- **Default model**: `settings.anthropic_model_id = "claude-sonnet-4-5-20250929"` (`config.py:62`).
- **Structured output**: a forced single tool call — `tools:[{name, description, input_schema: json_schema}]` with `tool_choice:{"type":"tool","name":tool_name}`; the response is parsed from the `tool_use` content block's `input` field. No schema flattening is needed — Anthropic resolves `$ref`/`$defs` natively (`:49-53,65-86`).
- **Constructor overrides**: `AnthropicClient(api_key=None, model_id=None, max_tokens=None)` (`:26-35`).
- **Errors**: HTTP status ≥400 → `RuntimeError`; a missing `tool_use` block in the response → `RuntimeError` (`:78-87`).

### 4.3 AWS Bedrock — `bedrock_client.py`
- **Endpoint**: boto3's `bedrock-runtime` client `.converse()` API — an SDK call, not raw HTTP (`:62-66,109-115`); the synchronous boto3 call is run via `asyncio.to_thread` (`:84-86`).
- **Auth**: two schemes — a bearer token via the `AWS_BEARER_TOKEN_BEDROCK` environment variable (set from `bedrock_api_key`/`settings.bedrock_api_key`, `:46,53-58`), or classic SigV4 IAM access-key/secret (`settings.aws_access_key_id`/`aws_secret_access_key`, `:47-48,59-61`). `is_configured` requires the bearer token **or** both IAM values (`:50,68-70`).
- **Default model / region**: `settings.bedrock_model_id = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"` (`config.py:52`); default region `settings.aws_region = "us-east-1"` (`config.py:48`).
- **Structured output**: forced tool call via the Converse API's `toolConfig` (`toolSpec.inputSchema.json = json_schema`, `toolChoice:{"tool":{"name":tool_name}}`); the response is parsed from `output.message.content[].toolUse.input` (`:96-124`).
- **Constructor overrides**: `BedrockClaudeClient(bedrock_api_key=None, aws_access_key_id=None, aws_secret_access_key=None, aws_region=None, model_id=None, max_tokens=None)` (`:34-42`).
- **Errors**: `ClientError`/`BotoCoreError` → `RuntimeError`; no matching `toolUse` block in the response → `RuntimeError` (`:116-124`).

### 4.4 Google Gemini — `gemini_client.py`
- **Endpoint**: `POST {_API_BASE}/models/{model_id}:generateContent`, `_API_BASE = "https://generativelanguage.googleapis.com/v1beta"` (`:29,77`).
- **Auth**: the API key is passed via the `x-goog-api-key` **header** (`:80`), deliberately not the `?key=...` query-string form Google's docs also support — httpx logs the full request URL at INFO level, which would otherwise put the real key in plain text in every application log line (`:72-76`).
- **Default model**: `settings.gemini_model_id = "gemini-2.0-flash"` (`config.py:57`).
- **Structured output**: `generationConfig.responseMimeType = "application/json"` plus an OpenAPI-3.0-style `responseSchema`, ref-flattened via `inline_refs()` because Gemini's schema dialect does not resolve JSON-Schema `$ref`/`$defs` (`:10-15,60-69`); the response text is parsed with `json.loads()` (`:91-94`).
- **Constructor overrides**: `GeminiClient(api_key=None, model_id=None, max_tokens=None)` (`:33-42`).
- **Errors**: HTTP status ≥400 → `RuntimeError`; no `candidates` or no text in the response → `RuntimeError`; invalid JSON text → `RuntimeError` (`:77-94`).

### 4.5 Groq — `groq_client.py`
- **Endpoint**: `POST {_API_BASE}/chat/completions`, `_API_BASE = "https://api.groq.com/openai/v1"` — an OpenAI-compatible chat-completions API (`:44,112`); model discovery via `GET {_API_BASE}/models` (`:152-156`).
- **Auth**: header `Authorization: Bearer <GROQ_API_KEY>` (`:108`).
- **Default model**: `settings.groq_model_id = "llama-3.3-70b-versatile"` (`config.py:69`; also the module-level `DEFAULT_MODEL` at `:60`). A separate `FALLBACK_MODELS` list (`:55-59`) exists **only** to populate the setup wizard's model dropdown when live discovery fails — it is never used to validate a real inference call.
- **Structured output**: forced tool-calling (`tools:[{"type":"function","function":{name, description, parameters: flat_schema}}]`, `tool_choice:{"type":"function","function":{"name":tool_name}}`) rather than the OpenAI `response_format` JSON mode — the module docstring's stated rationale is that `response_format` isn't guaranteed to be honored by every hosted model (`:20-31,96-107`). The schema is ref-flattened defensively via `inline_refs()` (`:39,87`); the response is parsed from `choices[0].message.tool_calls[].function.arguments` (a JSON string) (`:128-137`).
- **Constructor overrides**: `GroqClient(api_key=None, model_id=None, max_tokens=None)` (`:64-73`).
- **Errors**: `httpx.TimeoutException` after 60s → `RuntimeError`; HTTP status ≥400 → `RuntimeError`; no `choices` in the response → `RuntimeError`; no matching tool call → `RuntimeError`; invalid JSON in `arguments` → `RuntimeError` (`:110-137`).

### 4.6 OpenAI — `openai_client.py`
- **Endpoint**: `POST https://api.openai.com/v1/chat/completions`; model discovery `GET https://api.openai.com/v1/models` (`_API_BASE`).
- **Auth**: header `Authorization: Bearer <OPENAI_API_KEY>`.
- **Default model**: `settings.openai_model_id`, `DEFAULT_MODEL = "gpt-4o-mini"` — the smaller/cheaper model, matching this codebase's convention of defaulting to the fast tier rather than the largest available model.
- **Structured output**: forced tool-calling (`tool_choice` naming a specific function) rather than `response_format` JSON mode — the same "name/shape exactly one tool call" approach `groq_client.py` uses, chosen for the same precision reason. `inline_refs()` flattens `$ref`/`$defs` defensively, same as every other client in this module.
- **Model discovery filtering**: OpenAI's `/models` endpoint lists every model visible to the account, including embedding/moderation/image/audio models that can't do chat completions at all — `list_models()` filters to ids starting with `gpt-`/`o1`/`o3`/`o4`/`chatgpt-` and excluding audio/realtime/transcribe/tts/embedding matches, so the wizard's dropdown isn't cluttered with entries that would fail immediately if selected.
- **Errors**: `httpx.TimeoutException` after 60s → `RuntimeError`; HTTP status ≥400 → `RuntimeError`; no `choices` in the response → `RuntimeError`; no matching tool call → `RuntimeError`; invalid JSON in `arguments` → `RuntimeError`.

### 4.7 Kimi (Moonshot AI) — `kimi_client.py`
- **Endpoint**: `POST https://api.moonshot.ai/v1/chat/completions`, an OpenAI-compatible surface; model discovery `GET https://api.moonshot.ai/v1/models`.
- **Auth**: header `Authorization: Bearer <KIMI_API_KEY>`.
- **Default model**: `settings.kimi_model_id`, `DEFAULT_MODEL = "kimi-k2.5"` — deliberately not Moonshot's newest model. Several current Moonshot models (`kimi-k3`, `kimi-k2.7-code`) always run in "thinking" mode with no way to disable it, and a forced `tool_choice` call is documented as incompatible with thinking mode on those models (would `400`). `kimi-k2.5` and the `moonshot-v1-*` family have no thinking parameter and work with forced tool-calling with no special handling, so the default is pinned there.
- **Structured output**: OpenAI-style forced tool-calling, same approach as `openai_client.py`/`groq_client.py`.
- **Errors**: same shape as OpenAI — timeout after 60s, HTTP ≥400, missing choices, missing matching tool call, or invalid JSON in `arguments` all raise `RuntimeError`.

### 4.8 DeepSeek — `deepseek_client.py`
- **Endpoint**: `POST https://api.deepseek.com/chat/completions` — note the base URL has **no** `/v1` path segment, unlike most other OpenAI-compatible clients in this module; model discovery `GET https://api.deepseek.com/models`.
- **Auth**: header `Authorization: Bearer <DEEPSEEK_API_KEY>`.
- **Default model**: `settings.deepseek_model_id`, `DEFAULT_MODEL = "deepseek-v4-flash"`.
- **Structured output**: OpenAI-style forced tool-calling, same approach as every other OpenAI-compatible client in this module.
- **Errors**: same RuntimeError shape as OpenAI/Kimi. DeepSeek's API also returns a provider-specific HTTP 402 ("Insufficient Balance") in addition to the standard 400/401/429/500/503 codes — that per-status distinction is handled in `app/ai/connection_test.py`, not in the client itself.

### 4.9 xAI (Grok) — `xai_client.py`
- **Endpoint**: `POST https://api.x.ai/v1/chat/completions`, an OpenAI-compatible surface; model discovery `GET https://api.x.ai/v1/models`.
- **Auth**: header `Authorization: Bearer <XAI_API_KEY>`.
- **Default model**: `settings.xai_model_id`, `DEFAULT_MODEL = "grok-4.6"`. The module's own docstring flags that `"grok-3"` is retired (as of 2026-05-15) and deliberately excluded from `FALLBACK_MODELS`.
- **Structured output**: forced tool-calling via the standard OpenAI-shaped `tool_choice` object. Caveat noted in the module docstring: xAI's own documentation states `tools[].function.parameters` "should" be followed by the model but is "not enforced at the moment" — there is no guaranteed strict schema adherence on xAI's end, so the JSON-decode error handling is left exactly as defensive as every other client's, not loosened or tightened for this one.
- **Errors**: same RuntimeError shape as the other OpenAI-compatible clients. xAI's error body is flat (`{"code", "error"}` as a bare string), not nested like OpenAI's — this client doesn't parse error bodies itself (it surfaces `response.text` verbatim), so the shape difference doesn't affect anything here.

### 4.10 Mistral AI — `mistral_client.py`
- **Endpoint**: `POST https://api.mistral.ai/v1/chat/completions`; model discovery `GET https://api.mistral.ai/v1/models`.
- **Auth**: header `Authorization: Bearer <MISTRAL_API_KEY>` (standard OpenAI-compatible bearer scheme, not Anthropic's `x-api-key` or Gemini's query-param key).
- **Default model**: `settings.mistral_model_id`, `DEFAULT_MODEL = "mistral-small-2506"` — the smaller/faster/cheaper model, matching this codebase's default-to-fast-tier convention. Mistral versions its models with dated suffixes rather than a single rolling name, though rolling aliases (e.g. `mistral-large-latest`) also exist.
- **Structured output**: forced tool-calling via the standard OpenAI-shaped `tool_choice` object, per Mistral's own live API reference.
- **Errors**: same RuntimeError shape as the other OpenAI-compatible clients. Mistral's error-response body shape is unconfirmed (no dedicated error-schema documentation was found), so this client deliberately doesn't attempt to parse it — same as `openai_client.py`'s own template, which only ever surfaces `response.text` on a non-2xx status.

### 4.11 OpenRouter — `openrouter_client.py`
- **Endpoint**: `POST https://openrouter.ai/api/v1/chat/completions`; model discovery `GET https://openrouter.ai/api/v1/models`. OpenRouter is a meta-router, not a model provider of its own — it gives access to hundreds of underlying models from many companies (OpenAI, Anthropic, Google, Meta, DeepSeek, and others) through one OpenAI-compatible API surface.
- **Auth**: header `Authorization: Bearer <OPENROUTER_API_KEY>`.
- **Default model**: `settings.openrouter_model_id`, `DEFAULT_MODEL = "openai/gpt-4o"`.
- **Structured output**: forced tool-calling via the standard OpenAI-shaped `tool_choice` object, confirmed directly against OpenRouter's own OpenAPI spec (schema `ChatNamedToolChoice`).
- **Model discovery filtering, a real constraint specific to this backend**: because OpenRouter fans out to hundreds of underlying models, many of which do not support forced tool-calling at all, `list_models()` filters the live `/models` response down to ids whose `supported_parameters` array contains `tool_choice` (confirmed live: 342 of 413 models declared tool_choice support at the time this was written) — picking a model without it would `400` against this client's forced-tool-calling `call_claude_json()`. Falls back to returning every listed model id if the response doesn't include `supported_parameters` for any model.
- **Errors**: same RuntimeError shape as the other OpenAI-compatible clients. OpenRouter's error body is `{"error": {"code", "message", "metadata"?}}` — similar to OpenAI's nested shape but without an `error.type`/`error.param` field; doesn't change handling since only `response.text` is surfaced either way.

## 5. Cross-Cutting Mechanisms

- **Per-investigation credential overrides (IOC providers)**: `app/core/runtime_context.py:38-47` — `get_credential(provider_id, field, fallback)` returns a per-investigation `ContextVar` override when one has been set (via `set_provider_overrides()` at `orchestrator.py:113`), else falls back to the `.env`-derived `Settings` value. Every real provider's `fetch()` calls this — e.g. `abuseipdb.py:29`, `virustotal.py:44`, `otx.py:46`, `nvd.py:32`, `censys.py:40-41`, `hybrid_analysis.py:45`, `phishtank.py:29`, `urlhaus.py:31`, `threatfox.py:38`, `malwarebazaar.py:31`.
- **AI backend resolution order**: `app/ai/service.py:_get_ai_client` (`:102-145`) resolves the active backend in this order on **every call**: an explicit `backend_override` (used by the reanalyze/comparison feature) → the DB-backed active runtime config (`app/core/runtime_config.py`) → the legacy `settings.ai_backend` default of `"ollama"` (`config.py:80`).
- **Live connection tests** (candidate credentials only, never `get_settings()`): IOC providers are tested in `app/providers/connection_test.py:51-208` (VirusTotal, AbuseIPDB, OTX, the abuse.ch family via ThreatFox's `query_status`, NVD, Hybrid Analysis, Censys, PhishTank); urlscan.io and Google Safe Browsing are tested the same way despite having no wizard entry. AI backends are tested in `app/ai/connection_test.py` — a dedicated `_check_*` function exists for all eleven (Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral, OpenRouter, Anthropic, Gemini, Ollama, Bedrock), not just the original five; the module's own docstring records the investigation finding that motivated dedicated per-backend checks in the first place: none of the original five backends' generic error handling reliably distinguished "bad key" from "bad request" from "service down" without one. Both endpoints — `POST /api/v1/providers/{id}/test` and `POST /api/v1/ai/test` — make one real, minimal outbound call with the credentials from the request body and never persist them; see the *Runtime Configuration and Credential Lifecycle* chapter for how this relates to the separate, saved runtime-config path.

## 6. Quick-Reference Table

| Provider ID | Category | Auth mechanism | IOC types | Rate-limit signal |
|---|---|---|---|---|
| `virustotal` | threat_intel | header `x-apikey` | ipv4/ipv6/domain/url/hashes | 429/403/509 |
| `abuseipdb` | threat_intel | header `Key` | ipv4/ipv6 | 429/403/509 |
| `otx` | threat_intel | header `X-OTX-API-KEY` | ipv4/ipv6/domain/hostname/url/hashes | 429/403/509 |
| `urlhaus` | threat_intel | header `Auth-Key` (shared) | url/domain/ipv4 | `query_status` mapping |
| `threatfox` | threat_intel | header `Auth-Key` (shared) | ipv4/ipv6/domain/url/md5/sha256 | `query_status` mapping |
| `malwarebazaar` | threat_intel | header `Auth-Key` (shared) | md5/sha1/sha256/sha512 | `query_status` mapping |
| `crtsh` | certificate_intel | none | domain/tls_certificate | 429/403/509 |
| `nvd` | vulnerability | optional header `apiKey` | cve | 429/403/509 |
| `cisa_kev` | vulnerability | none | cve | 429/403/509 |
| `mitre_attack` | threat_intel | none | mitre_technique | 429/403/509 |
| `whois_rdap` | whois | none | domain/ipv4/ipv6/asn | socket timeout/error |
| `hybrid_analysis` | sandbox | header `api-key` | sha256 only | 429/403/509 |
| `spamhaus` | threat_intel | none (DNS only) | ipv4/domain | none (no HTTP call) |
| `phishtank` | threat_intel | optional form `app_key` | url | 429/403/**509** |
| `censys` | passive_dns | Bearer token + `X-Organization-ID` | ipv4/ipv6 | 429/403/509 |
| `internet_intelligence` | osint | none | domain/ipv4/malware_family/threat_actor/campaign/cve/file_name | per-sub-source (see §3) |
| `urlscan` | sandbox | header `API-Key` | url/domain | 401/403 = bad key, not rate limit; else `TIMEOUT` at 60s |
| `google_safe_browsing` | threat_intel | query param `key` | url/domain | any non-200/error → `unknown`, never `RATE_LIMITED`-mapped as "safe" |

| AI backend | Endpoint style | Auth | Structured-output technique |
|---|---|---|---|
| Ollama | Local REST (`/api/chat`) | none | `format` = flattened JSON Schema (grammar-constrained) |
| Anthropic | Messages API | header `x-api-key` | forced tool call |
| Bedrock | boto3 `.converse()` SDK call | bearer token or IAM SigV4 | forced tool call via `toolConfig` |
| Gemini | `generateContent` REST | header `x-goog-api-key` (deliberately not the `?key=` query-string form, to keep the key out of httpx's INFO-level URL logging) | `responseSchema` JSON mode (flattened) |
| Groq | OpenAI-compatible chat-completions | header `Authorization: Bearer` | forced tool call (not `response_format`) |
| OpenAI | OpenAI chat-completions | header `Authorization: Bearer` | forced tool call |
| Kimi (Moonshot AI) | OpenAI-compatible chat-completions | header `Authorization: Bearer` | forced tool call |
| DeepSeek | OpenAI-compatible chat-completions (no `/v1` in base URL) | header `Authorization: Bearer` | forced tool call |
| xAI (Grok) | OpenAI-compatible chat-completions | header `Authorization: Bearer` | forced tool call (best-effort — xAI docs note `parameters` isn't strictly enforced) |
| Mistral AI | OpenAI-compatible chat-completions | header `Authorization: Bearer` | forced tool call |
| OpenRouter | OpenAI-compatible chat-completions (meta-router over many providers) | header `Authorization: Bearer` | forced tool call (model list filtered to `tool_choice`-capable ids) |
