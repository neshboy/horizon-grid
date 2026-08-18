# HORIZON GRID — AI Provider Expansion QA Report (v0.2.0)

## Provider matrix

| Backend | Status | Base URL verified live | Forced tool_choice confirmed | Live model discovery | Unit tests | Live network round trip (fake key) |
|---|---|---|---|---|---|---|
| Ollama | Pre-existing, unaffected | — | — | Yes (local) | Pre-existing | — |
| Anthropic | Pre-existing, unaffected | — | — | Static list | Pre-existing | — |
| Bedrock | Pre-existing, unaffected | — | — | Static list | Pre-existing | — |
| Gemini | Pre-existing, unaffected | — | — | Static list | Pre-existing | — |
| Groq | Pre-existing, unaffected | — | — | Yes | Pre-existing | — |
| OpenAI | Pre-existing, unaffected (added earlier this cycle) | — | — | Yes | Pre-existing | — |
| **Kimi** | **New** | Yes | Yes (with documented thinking-mode caveat) | Yes | 7 (incl. thinking-conflict case) | Yes — 106ms, real HTTP 401 |
| **DeepSeek** | **New** | Yes (no `/v1` confirmed) | Yes | Yes | 6 (incl. 402 balance case) | Yes — 161ms, real HTTP 401 |
| **xAI (Grok)** | **New** | Yes | Yes | Yes | 6 (incl. flat-error-body 400 case) | Yes — 244ms, real HTTP 400 |
| **Mistral** | **New** | Yes | Yes | Yes | 6 | Yes — 248ms, real HTTP 401 |
| **OpenRouter** | **New** | Yes (via raw OpenAPI spec + live curl) | Yes (with capability filter) | Yes (filtered to `tool_choice`-capable models) | 6 (incl. 402 credits case) | Yes — 39ms, real HTTP 401 |

## Kimi results

Real endpoint `https://api.moonshot.ai/v1/chat/completions` confirmed reachable. Default model `kimi-k2.5` chosen specifically to avoid the documented conflict between forced `tool_choice` and Moonshot's newer "thinking" models (`kimi-k3`, `kimi-k2.7-code`), which return HTTP 400 with the message `tool_choice 'specified' is incompatible with thinking enabled`. A dedicated unit test (`test_kimi_400_thinking_conflict_is_reported_clearly`) confirms the connection-test surfaces this as an actionable message rather than a generic failure. Live fake-key test: 106ms round trip, correct `Authentication failed` response.

## DeepSeek results

Real endpoint confirmed at `https://api.deepseek.com/chat/completions` — no `/v1` segment, verified against live documentation and matched in the actual client implementation. Two real model IDs confirmed (`deepseek-v4-flash`, `deepseek-v4-pro`); older `deepseek-chat`/`deepseek-reasoner` names no longer appear in current docs and were not used. Live fake-key test: 161ms round trip, correct `Authentication failed` response. DeepSeek's distinctive HTTP 402 ("insufficient balance") is handled with its own message, not folded into a generic error.

## xAI (Grok) results

Real endpoint confirmed at `https://api.x.ai/v1/chat/completions`. Confirmed via live probing that `grok-3` is retired (redirected as of 2026-05-15) — the default model is `grok-4.6`, not a stale cached name. xAI's error body is flat (`{"code","error"}`, not nested like most other backends) — this was specifically identified and unit-tested (`test_xai_400_bad_key_is_reported_as_auth_failure`, since xAI returns 400 rather than 401 for a bad key). Live fake-key test: 244ms round trip, correctly reported as an authentication failure despite the non-standard status/body shape.

## Mistral results

Real endpoint confirmed at `https://api.mistral.ai/v1/chat/completions`. Forced `tool_choice` confirmed directly against Mistral's live API reference schema (an earlier, narrower fetch of a guide page had incorrectly suggested named-tool forcing wasn't supported — the authoritative API reference contradicts that, and the implementation follows the authoritative source). Live fake-key test: 248ms round trip, correct `Authentication failed` response.

## OpenRouter results

Real endpoint confirmed at `https://openrouter.ai/api/v1/chat/completions`, cross-checked against OpenRouter's actual OpenAPI spec (not just documentation prose) and a live, unauthenticated `curl` against `/models` (413 real models returned). Model discovery filters to models whose `supported_parameters` list includes `tool_choice`, since roughly a fifth of OpenRouter's catalog does not support forced tool calling and would otherwise 400 if selected. Live fake-key test: 39ms round trip, correct `Authentication failed` response.

## Model discovery (no key) results

All 5 new backends' `POST /api/v1/ai/{backend}/models` endpoints were hit against a real running instance with no credentials supplied, confirming each returns its documented fallback list with `"source": "fallback"` rather than erroring:

- kimi → `kimi-k2.5, moonshot-v1-128k, moonshot-v1-32k, moonshot-v1-8k, kimi-k2.6`
- deepseek → `deepseek-v4-flash, deepseek-v4-pro`
- xai → `grok-4.6, grok-4.5, grok-4.3, grok-code-fast-1`
- mistral → `mistral-small-2506, mistral-large-2411, mistral-medium-2508, codestral-2501`
- openrouter → `openai/gpt-4o, anthropic/claude-sonnet-4.5, google/gemini-2.5-pro, deepseek/deepseek-chat, meta-llama/llama-3.3-70b-instruct`

## Provider switching / runtime configuration results

`GET /api/v1/runtime/ai-providers` against a real running instance confirmed all 11 backends appear with correct default model IDs and `configured: false` for the 5 new ones (no key ever provided in this session). Existing runtime-switching mechanism (`app/ai/service.py`'s per-call credential resolution, no restart required) was not modified by this change — the new backends slot into the exact same dispatch table as the existing 6.

## Local AI results

Ollama is unaffected by this change — no code path shared between the new cloud backends and the local Ollama client was touched. Confirmed via the full real IOC investigation below, which ran with `AI_BACKEND=ollama` and produced a real, successful AI assessment (`ai_outcome: "success"`).

## Backend regression results

Full unit suite: **313 passed** (282 pre-existing + 31 new), run 5 consecutive times with zero flakiness during the preceding backend-test-stability investigation, and once more after this change with the same result. Frontend: `npm run lint` clean (one pre-existing, unrelated warning), `npm run build` succeeds, all 13 routes compile.

## Full pipeline regression (real IOC investigation)

A real investigation of `8.8.4.4` was run end to end against a live, isolated instance with the expanded 11-backend architecture in place: real provider fan-out (VirusTotal, OTX, AbuseIPDB, Internet Intelligence Collector), real correlation graph construction, real deterministic scoring engine output (`scoring_engine_version: "1.0"`, severity `high`, score 62.9 with a visible corroboration-multiplier breakdown), and a real, successful AI assessment (`ai_backend: "ollama"`, `ai_outcome: "success"`) — confirming the existing 6-backend pipeline continues to function correctly with 5 more backends registered alongside it.

## Installer results

**Windows**: Rebuilt via Inno Setup after the version bump. A real, previously-undiscovered packaging defect was found during this rebuild: `installer.iss` never excluded `backend/.venv`/`.venv_test` from the bundled files. The prior installer (~69 MB) was silently bundling ~190 MB of local dev virtualenv content that the running application never uses. Fixed by adding the exclusion; the corrected installer is **8,182,003 bytes** (SHA256 `217dd98b9d72b6c1071d091a0898c098f47059f011927c8e98832a466d50da46`), verified by a full recompile showing 0 venv files among 293 packaged files (down from 7,604 of 7,897 before the fix).

**Linux**: Rebuilt via `linux/build-deb.sh` inside a real Debian 12 container. `linux/build-deb.sh` already excluded `.venv`/`.venv_test` correctly (its own comments had already flagged the Windows-side gap this pass just fixed). Resulting package: **6,077,300 bytes** (SHA256 `57d0db31d4e67dfd8ccad9f0c9dfbbf6e501382e3972f0a538f8cc4b7b912812`). Extracted and confirmed the packaged `setup_wizard.py` contains 19 references to the new backend names.

## GitHub results

Commit `e6539ad` pushed to `main`. Both CI workflows (`Backend Tests` — unit + real docker-compose-based integration; `Frontend Build` — lint + build) passed on this exact commit. Tag `v0.2.0` created and pushed. GitHub Release `v0.2.0` published (not a draft, not a prerelease) with 4 assets — both installers plus both checksum files — whose uploaded SHA256 digests were independently confirmed via the GitHub API to exactly match the locally-computed hashes, proving no corruption in transit.

## Documentation results

README.md, SECURITY.md, `.env.example`, the AI configuration guide (`standalone-ai-guide.md` — which, during this pass, was also found to have never documented OpenAI at all despite it being added as the 6th backend in an earlier cycle; now corrected to document all 11), the changelog, release notes, and the Linux installation/QA/technical docs were all updated with real, verified content (not placeholder text) and their corresponding 10 PDFs rebuilt.

## Known limitations

- Fireworks AI and Cerebras were researched but deliberately not added: Fireworks' model-discovery endpoint requires a non-key account ID (a real deviation from every other backend's "just needs an API key" pattern), and Cerebras' public catalog currently lists only 2 models with no documented error-body schema. Both are reasonable candidates for a future, dedicated pass.
- OpenRouter's and Mistral's exact error-body JSON shapes for statuses beyond what was live-tested (401/402/404/429) are not fully documented upstream; the connection-test implementation degrades gracefully (surfaces the raw response text) for anything not explicitly special-cased, matching the same defensive pattern already used for every pre-existing backend.
- The pre-existing, already-disclosed dependency findings in `SECURITY.md` (starlette/lxml/pytest/ecdsa on the backend; next.js's transitive chain on the frontend) are unchanged by this release.
- Two documentation figure placeholders (`standalone-start-menu.png`, `standalone-uninstall-confirm.png`, and the new `standalone-ai-openrouter-model-dropdown.png`) reference screenshots that don't yet exist on disk — pre-existing gap for the first two, and an honestly-flagged new one for the third; the doc build pipeline reports these as warnings, not failures.

## Failed tests

None. Zero test failures across the full regression pass (313/313 unit, frontend lint/build, live network verification, full pipeline investigation).

## Fixed tests / fixed defects

1. `python-jose 3.4.0` + `pyasn1 0.6.4` pip `ResolutionImpossible` (caught by CI, fixed by bumping `python-jose` to 3.5.0) — from the immediately preceding backend-test-stability cycle, carried forward and still verified holding in this release.
2. Windows installer bundling the local dev virtualenv (this report, above).
3. `standalone-ai-guide.md` never documenting the OpenAI backend at all (found and fixed during this pass's documentation update).

## Skipped tests

- A genuine live end-to-end test using a real (non-fake, non-fabricated) paid API key for each of the 5 new backends was not performed, per this project's standing security rule against using or requesting real credentials in this channel. The user was told to add real keys later via the running application's own Test Connection UI. Everything that *can* be verified without a real key (endpoint reachability, request/response shape, auth-failure handling, fallback model lists) was verified for real.
- Kimi's specific 400 thinking-mode-conflict response was verified via a mocked unit test (`respx`), not a live call against a real thinking-mode model with a real key, for the same reason.

## Final release verdict

# RELEASE READY

All CI checks green on the exact released commit, full regression suite passing (313/313 backend unit, integration suite green in its real docker-compose job, frontend lint/build clean), both installers rebuilt from that same commit and independently re-verified against their actual packaged contents (including a real, previously-undiscovered installer bug found and fixed, not swept under the rug), no secrets found in the repository or its history, GitHub tag/release/documentation/installers all reference the identical v0.2.0 version with no drift, and every new provider was verified against its real, current external API — not assumed from memorized knowledge.
