# Performance

An **IOC** (Indicator of Compromise) is the value a user submits for lookup — an IP address, domain, file hash, URL, CVE ID, etc. A **provider** is a connector to an external threat-intelligence source (VirusTotal, AbuseIPDB, and so on) queried for a given IOC. A lookup runs over **SSE** (Server-Sent Events) — a single streamed HTTP response that pushes result events to the client as they become available, rather than one request/response per step.

This section reports two different kinds of number, and is explicit about which is which: (1) values actually observed during the one documented end-to-end QA pass (`FINAL_END_TO_END_TEST_REPORT.md`, run 2026-08-11 on a single Windows 11 workstation), and (2) hard-configured limits read directly from the backend code, which bound worst-case behavior even though no live measurement of hitting those limits exists. With one exception — the Executive Dashboard / Provider Health endpoint load test described later in this section — no dedicated load-testing, benchmarking, or repeated-trial statistical harness exists for this platform as of this writing; the rest of the QA pass was a single functional/regression walkthrough (clean install through uninstall/reinstall), not a performance study.

## 🔬 Scope and Methodology

- The only performance data available comes from **one** test pass on **one** machine, observed manually, not from an automated benchmark suite or multiple repeated trials.
- The bulk-load exercise referenced below was **eight** sequential IOC lookups, not a stress test — it was designed to check for resource leaks during a routine batch, not to find a breaking point or measure throughput.
- Where the two source documents do not contain a number for something a reader would reasonably want to know (e.g., percentile latencies, throughput, total install duration), the table below says "Not measured" rather than supplying an estimate.

## 📊 Measured and Configured Values

Every row below is either a number actually observed during the single documented test pass or a hard-configured limit found in the code; rows for commonly-expected performance metrics that neither source actually measured (percentile latency, throughput, install duration) are marked "Not measured" rather than estimated.

| Metric | Value | Basis | Source |
|---|---|---|---|
| Single-IOC investigation duration, end-to-end (SSE stream open to `done` event) | 5–15 seconds, varying by which providers make real network calls | Measured (one test pass) | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| OSINT crawler (`internet_intelligence` provider) fan-out time | ~6 seconds — consistently the slowest single component observed | Measured (one test pass) | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| p50 / p95 / p99 lookup latency | Not measured | — | — |
| Throughput (concurrent lookups per second/minute) | Not measured | — | — |
| `backend` container idle memory (RSS) | ~96 MB | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| `frontend` container idle memory | ~39 MB | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| `celery_worker` container idle memory | ~695 MB | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| `postgres` container idle memory | ~38 MB | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| `redis` container idle memory | ~5 MB | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| `neo4j` container idle memory | ~553 MB (provisioned container with no consuming backend code — see architecture-facts.md §2/§5/§9) | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| `opensearch` container idle memory | ~1.07 GB (provisioned container with no consuming backend code — see architecture-facts.md §2/§5/§9) | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| CPU utilization across all eight containers at idle | <1% | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| `backend` memory after an 8-IOC sequential bulk run | ~104 MB (~9% increase over idle baseline; the tester attributed this to normal request handling, not a leak) | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12 |
| Leak/stability check across the bulk run | No memory-leak pattern, no CPU pegged at 100%, no zombie processes observed (qualitative, one run) | Measured | `FINAL_END_TO_END_TEST_REPORT.md` §12/§11 |
| Installer/wizard total wall-clock duration | Not measured | — | — |
| Setup-wizard health-check poll ceiling after `docker compose up -d --build` (before admin registration) | Up to 3 minutes (a ceiling the wizard will wait, not an observed typical duration) | Configured limit | architecture-facts.md §6 |
| "Open Platform" launcher: Docker Desktop cold-start wait ceiling | Up to 3 minutes (a ceiling the launcher will wait, not an observed typical duration) | Configured limit | `FINAL_END_TO_END_TEST_REPORT.md` §5 |
| Post-reboot interactive Windows logon delay observed during the one real-reboot test | ~18 minutes after boot completed (an OS-level startup-throttling effect on the test workstation, not a product behavior — noted because the launcher has to tolerate it) | Measured (single observation, environmental) | `FINAL_END_TO_END_TEST_REPORT.md` §10 |
| Per-provider call timeout (`provider_timeout_seconds`) | 20 seconds | Configured limit | architecture-facts.md §9 |
| Per-provider retry policy (`provider_max_retries`) | 2 retries, exponential backoff (`wait_exponential(multiplier=0.5, max=4)`, via tenacity) | Configured limit | architecture-facts.md §9 |
| Provider-result cache TTL (`provider_cache_ttl_seconds`), Redis-backed | 3600 seconds (1 hour) | Configured limit | architecture-facts.md §2/§9 |
| AI-backend client timeout, Ollama (`_TIMEOUT_SECONDS`) — applies only when `ai_backend=ollama` (the default) | 120 seconds, hardcoded | Configured limit | architecture-facts.md §9 |
| AI-backend client timeout, the other ten backends — nine (Anthropic, Gemini, Groq, OpenAI, Kimi, DeepSeek, xAI, Mistral, OpenRouter) hardcode their own client-side timeout; Bedrock's client has none of its own and relies on the AWS SDK's default | 60 seconds, hardcoded, for the nine non-Bedrock cloud backends | Configured limit | direct inspection of `backend/app/ai/*_client.py` |
| Lookup-creation rate limit, Redis fixed-window, per user | 10 calls / 60 seconds | Configured limit | architecture-facts.md §2/§9 |

## ⚙️ Where These Limits Apply in the Lookup Pipeline

[FIGURE: tech-09-performance-diagram-1.png | Diagram: Where These Limits Apply in the Lookup Pipeline]

## 📈 Dashboard and Provider Health Endpoint Load Testing

Unlike the rest of this section, the Executive Dashboard (`GET /api/v1/dashboard/kpis`, `GET /api/v1/dashboard/executive-summary`) and Provider Health (`GET /api/v1/providers/health`) endpoints received a dedicated, real concurrent-load test — a repeated-trial exercise, not a single-pass manual walkthrough.

The first such test found a genuine complete-failure mode: 25 concurrent requests to the Provider Health endpoint timed out 100% of the time. Two real bugs were found and fixed as a direct result:

1. **Excessive sequential database round-trips.** The endpoint's aggregation code was issuing on the order of 300 sequential, awaited database round-trips in a single request (multiple metrics across multiple time windows, for every registered provider). This was consolidated into a small number of aggregate queries per request, using SQL conditional aggregation grouped by provider so the database computes every window's numbers for every provider in one round-trip instead of one round-trip per provider per window per metric.
2. **Database connection-pool sizing that didn't account for real per-request connection usage.** The pool had been sized around the ORM's un-tuned defaults, which didn't account for a single authenticated request actually holding two simultaneous connections at once (one for the authentication dependency, one opened separately by the endpoint's own service logic). The pool was resized to account for that.

After both fixes, the same 25-concurrent-request test against the Provider Health endpoint was re-run live: it went from 100% timeout to 100% success, completing in under 2 seconds — a complete reversal of the earlier failure, not just an incremental improvement.

> [!NOTE]
> **A separate, honestly disclosed characteristic, not a bug:** the AI-generated executive summary can become significantly slower under heavy *concurrent* load specifically when the platform is configured to use a local AI backend (e.g. Ollama) — a single local model processes generation requests one at a time, so concurrent requests for the executive summary queue up behind one another. This does not affect data correctness: the underlying KPI numbers behind the summary are always the current, real, deterministic values, regardless of how long the AI narrative itself takes to generate. It also does not affect the Dashboard's core KPI tiles or the Provider Health page, both of which are pure database reads, unaffected by AI backend choice or load. An administrator expecting many concurrent users should consider one of the platform's ten cloud-hosted AI backends (Anthropic, AWS Bedrock, Google Gemini, Groq, OpenAI, Kimi, DeepSeek, Grok, Mistral AI, or OpenRouter) rather than a local model, for a consistently fast executive summary under concurrent load.

## ⚠️ Caveats

- **No formal performance-testing infrastructure exists, with one exception.** Every measured value above comes from a single manual QA pass on a single workstation, not from a repeatable benchmark harness, and the "bulk" exercise it drew from was eight sequential lookups — enough to sanity-check for leaks, not to establish throughput or latency distributions. Treat the measured rows as one anecdotal data point each, not as guaranteed or typical performance. The one exception is the dedicated concurrent-load test against the Dashboard/Provider Health endpoints described above, which was a genuine repeated-trial (25 concurrent requests) exercise rather than a single manual pass.
- **A meaningful share of idle memory is currently unused infrastructure, not active workload.** Neo4j (~553 MB idle) and OpenSearch (~1.07 GB idle) are provisioned containers with no consuming backend code (see architecture-facts.md §2/§5/§9) — together they account for roughly 1.6 GB of the platform's idle memory footprint while doing no work for the running system today.
- **The two "3-minute" figures are ceilings, not typical waits.** Neither source document reports how long the setup wizard's post-install health poll or the "Open Platform" launcher's Docker-Desktop-startup wait actually took in the tested runs — only the configured maximum each will tolerate before giving up or erroring.
- **The 120-second timeout is Ollama-specific.** It applies when the platform is configured to use the default local `ollama` AI backend (model `llama3.2:3b`). Nine of the ten other backend clients (`anthropic`, `gemini`, `groq`, `openai`, `kimi`, `deepseek`, `xai`, `mistral`, `openrouter`) each hardcode their own, shorter 60-second client timeout; only `bedrock`'s client has no hardcoded timeout of its own, relying on the AWS SDK's own default instead.
