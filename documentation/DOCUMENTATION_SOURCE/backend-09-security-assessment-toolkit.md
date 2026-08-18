# Security Assessment Toolkit Architecture

This chapter documents the Security Assessment Toolkit (`backend/app/security_assessment/`,
`backend/app/core/security_assessment.py`, `backend/app/api/routes/security_assessment.py`) — the
platform's one and only subsystem that sends **active** traffic to a target, as opposed to every
provider under `backend/app/providers/`, which only ever queries a third party's already-collected
data. It was built under an explicit, non-negotiable constraint: this must never become an
exploitation framework. Every architectural decision below is traceable to that constraint.

For the user-facing tool/profile/severity reference, see
[SECURITY_ASSESSMENT_TOOLKIT.md](../../docs/SECURITY_ASSESSMENT_TOOLKIT.md) in the repo root
`docs/` folder — this chapter covers the *implementation*, that one covers *behavior*.

## 1. Why Tools Are Not Providers

`app/providers/base.py`'s `BaseProvider`/`ProviderResult`/`ProviderCategory`/`ProviderStatus`
contract was confirmed, by direct research before any of this was written, to be fully reusable:
`app/ai/service.py`'s `_provider_result_to_prompt()`/`_prune_for_prompt()`/
`generate_final_assessment()` are field-name-generic and need zero changes to consume a new
category of data, provided it arrives as a genuine `ProviderResult`. So every tool in this package
*produces* one. But tools are **not** `BaseProvider` subclasses, and are **not** registered in
`app/providers/registry.py`'s `_ALL_PROVIDERS`:

- `BaseProvider.run()` is built around the automatic, always-on orchestrator fan-out
  (`app/providers/orchestrator.py`) — every registered provider runs on every investigation whose
  IOC type it supports, with no per-call authorization. A tool that sends real traffic to a target
  must never run that way.
- Tools are often materially slower than an API call (a real port scan, not a single HTTP request)
  and need their own timeout/subprocess-lifecycle handling (`nmap_tool.py`'s
  `asyncio.wait_for`/`proc.kill()`), which doesn't fit `BaseProvider`'s existing wrapper.

Instead, `app/security_assessment/base.py`'s `SecurityAssessmentTool` is a separate, minimal base
class: `tool_id`, `tool_name`, `supported_types`, a `profiles: dict[str, ScanProfile]`, and one
abstract `async def run(self, target, ioc_type, profile_id) -> ToolRunResult`. `ToolRunResult`
bundles the genuine `ProviderResult` (for the AI/correlation pipeline) alongside a `list[Finding]`
(for persistence and UI drill-down) — the two representations a tool's work needs to feed.

## 2. The Authorization Gate

`app/core/security_assessment.py::_validate_scope()` is the single choke point every request
passes through before a `SecurityAssessmentRun` row is even created:

```python
def _validate_scope(lookup, target_confirmation, authorization_confirmed) -> IOCType:
    if not authorization_confirmed:
        raise AuthorizationNotConfirmedError(...)
    if target_confirmation != lookup.ioc_value:
        raise TargetMismatchError(...)
    if lookup.ioc_type not in SCANNABLE_TYPES:
        raise UnscannableIOCTypeError(...)
    ioc_type = IOCType(lookup.ioc_type)
    if ioc_type == IOCType.CIDR:
        network = ipaddress.ip_network(lookup.ioc_value, strict=False)
        if network.num_addresses > _MAX_CIDR_ADDRESSES:  # 16, i.e. /28
            raise CIDRTooLargeError(...)
    return ioc_type
```

Order matters: authorization is checked *before* target matching, so an unconfirmed request gets
a clear "you must confirm authorization" error rather than a possibly-true-or-false target-mismatch
claim. Every branch here is a plain `ValueError`-style exception the route layer maps to `400` —
none of it reaches a tool, a subprocess, or a network call. This is deliberately the *only* place
scope is checked; there is no second, looser path into `app/security_assessment/registry.py`'s
tools from anywhere else in the codebase.

## 3. Structured Process Execution (Nmap)

`nmap_tool.py` is the one tool that shells out to an external binary, and is held to the strictest
standard: `PROFILES`/`_PROFILE_ARGS` are hardcoded Python dicts mapping a profile *id* (never
accepted from a caller as raw text beyond that id) to a fixed `list[str]` of arguments. The
subprocess is launched via:

```python
argv = ["nmap", "-oX", "-", *_PROFILE_ARGS[profile_id], target]
proc = await asyncio.create_subprocess_exec(*argv, stdout=..., stderr=...)
```

`create_subprocess_exec` (never `create_subprocess_shell`) takes the argument list directly — there
is no shell interpolation step where `target` (attacker- or accident-controlled string) could be
parsed as anything other than one literal argv element. This is what "structured process execution"
means concretely: the string `"; rm -rf /"` as a `target` value is passed to `nmap` as a single,
literal, meaningless hostname argument, never concatenated into a shell command line.

Output is parsed via `xml.etree.ElementTree` against Nmap's own `-oX -` XML format, never by
regex-scraping human-readable text output (which Nmap's own docs warn is unstable across versions).

## 4. Provenance Categories

`app/core/provenance.py` defines four category constants — `THREAT_INTEL`,
`SECURITY_ASSESSMENT`, `LOCAL_OBSERVATION`, `AI_INTERPRETATION` — and one mapping function,
`category_for_provider_category()`, used by both `app/correlation/engine.py` (tagging each
`GraphEdge.provenance_category` at creation time) and `app/evidence/builder.py` (tagging each
`EvidenceRecord.provenance_category`). Only the first two are populated by any code today;
`LOCAL_OBSERVATION`/`AI_INTERPRETATION` are modeled and reserved for future use (e.g. an analyst's
own manually-asserted annotation; an AI-inferred-but-unverified relationship), documented here
rather than silently omitted.

This is a genuinely different axis from the pre-existing `CorrelationEdgeRecord.provenance`/
`GraphEdge.provenance` string, which names *which* provider or tool asserted a fact (and, for
corroborated facts, is a comma-joined list of them — see `engine.py`'s merge logic). Adding a
second axis required two migrations (`5c8e1f3a9b2d`, `6d2f4b8e1a7c`), not an overload of the
existing field: `evidence/builder.py` and `ai/service.py` already parse `provenance` by splitting on
`,` and treating each token as a provider id, so smuggling a category tag into that same string
would have silently corrupted both call sites.

`engine.py`'s new `merge_correlation_results()` combines an already-persisted correlation (rebuilt
via `app/evidence/loaders.py::correlation_from_records()`) with a freshly computed one from a
security-assessment run's new results, for a single `generate_final_assessment()` call — a
deliberate, disclosed simplification: it does not re-run `correlate()`'s own cross-provider
dedup/corroboration-boost logic across the two sets, so an identical fact asserted by both an
original provider and a new tool run would appear as two edges rather than one boosted-confidence
edge. Judged unnecessary complexity for what is, in practice, a rare overlap.

## 5. Result Integration and the "Refresh" vs. "Reanalyze" Distinction

`app/api/routes/lookup.py::reanalyze_lookup()` (the existing "compare with a different AI backend"
feature) always writes its new `FinalAssessmentRecord` with `is_primary=False` — it's an alternate
*opinion* on the same evidence, never promoted. `app/core/security_assessment.py::
_refresh_lookup_assessment()`, called automatically after a run completes, does the opposite: it
demotes the previous primary record (`UPDATE ... SET is_primary=False WHERE is_primary=True`) and
inserts the new one as `is_primary=True`, updating `IOCLookup.final_verdict`/`risk_score`/
`final_assessment` in place. The distinction is deliberate: new active-scan findings are genuine new
evidence about the investigation, not merely a different model's take on unchanged evidence.

## 6. Background Execution and Task Lifetime

`start_run()` returns `{"run_id", "status": "pending"}` immediately and spawns `_execute_run()` via
`_spawn_background()`, which adds the `asyncio.Task` to a module-level `_background_tasks: set` with
a `done_callback` that discards it on completion — the standard workaround for `asyncio.create_task`'s
own documented gotcha that a task with no other strong reference can be garbage-collected mid-flight.
A test-only helper, `wait_for_background_runs()`, awaits every currently in-flight task; this was
added after a real test-isolation bug surfaced during development, where a test polled
`SecurityAssessmentRun.status` (which flips to `COMPLETED` *before* the post-completion AI-refresh
step runs) and returned while that refresh step was still executing in the background, corrupting
whichever test ran next by disposing the shared DB engine out from under it.

## 7. Installer / Deployment

`backend/Dockerfile` installs `nmap` via `apt-get` alongside the pre-existing `gcc libpq-dev curl`.
`GET /api/v1/security-assessment/tool-health` calls `shutil.which("nmap")` at request time rather
than assuming installation succeeded — a deployment that somehow lacks the binary degrades to
"unavailable" in the UI rather than a scan silently failing partway through. `backend/requirements.txt`
gained one new dependency, `dnspython`, for the DNS enumeration tool (stdlib alone does not expose
MX/TXT/NS/CAA record types). No `k8s/` manifest change was needed — the k8s backend Deployment
already builds from this same Dockerfile.
