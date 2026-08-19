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

## 7. Cancellation

Cancellation was added after a forensic audit of the port-scanning pipeline found no way to stop a
run once started — the run tracking in §6 only prevented Python from garbage-collecting an
in-flight task; nothing let a caller reach in and stop one.

**Run-id-keyed task tracking.** `_spawn_background()` now takes the `run_id` as well as the
coroutine, and populates a second module-level map, `_run_tasks: dict[uuid.UUID, asyncio.Task]`,
alongside the existing GC-prevention set — the same `done_callback` clears both on completion:

```python
def _spawn_background(coro, run_id: uuid.UUID) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    _run_tasks[run_id] = task

    def _discard(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if _run_tasks.get(run_id) is t:
            del _run_tasks[run_id]

    task.add_done_callback(_discard)
    return task
```

**`cancel_run(run_id, actor_user_id, actor_email)`** is the new entry point (called from
`POST /api/v1/security-assessment/runs/{run_id}/cancel`, gated by the same
`security_assessment:create` permission as starting a run — this is a shared-team resource, per §5's
existing no-per-user-ownership model, so any analyst/admin can cancel any run, not only their own).
It loads the run, rejects with `RunNotCancellableError` if it's already `COMPLETED`/`FAILED`/
`CANCELLED`, and then branches on whether this *process* has a live task for it:

- If `_run_tasks` has a live entry, it calls `task.cancel()` — this raises `asyncio.CancelledError`
  inside `_execute_run()` at its next `await` point, which is handled as described below.
- If not — the run exists and is `PENDING`/`RUNNING` in the database, but this process has no task
  for it, which is exactly what happens after a backend restart — it writes the `CANCELLED` status
  directly. Without this branch, a run orphaned by a restart could never be cancelled at all, since
  there would be no live task to `.cancel()`.

**Exactly one audit record per cancellation, even under a real race.** `cancel_run()`'s initial
status check and its `task.cancel()` call are not atomic, so two concurrent cancel requests for the
same run can both read `RUNNING` and both proceed — confirmed live via a genuine concurrent-request
test. This is harmless on the `asyncio.Task` side (`.cancel()` on an already-cancelling task is a
no-op), but the live-task branch deliberately does **not** write its own `record_audit()` call for
this reason: only `_execute_run()`'s `except asyncio.CancelledError` handler does, and that handler
runs exactly once per task no matter how many times `.cancel()` was called on it, making it the
single source of truth. The direct-DB-write branch (no live task, e.g. post-restart) is the only
place that *does* write its own audit record — nothing else will ever run for that run — and even
there the `UPDATE ... WHERE status IN (...)` is checked via `result.rowcount` before writing, so two
concurrent requests hitting that branch for the same run still produce only one audit entry, not
two. Verified live, before and after, by querying `config_audit_log` directly during a real
concurrent-cancel race.

**Why a dedicated `except asyncio.CancelledError` branch is mandatory, not stylistic.** Since Python
3.8, `asyncio.CancelledError` inherits from `BaseException`, not `Exception` — the pre-existing
generic `except Exception as exc:` branch in `_execute_run()` silently does not catch it. Without an
explicit branch, a cancelled task's DB row would simply stay `RUNNING` forever (the task dies, but no
code ever runs to update the row), which is worse than doing nothing: a stuck `RUNNING` row with no
way to distinguish it from a genuinely slow scan. The fix adds a branch *before* the generic
`except Exception`, which updates the row to `CANCELLED`, records the audit event
`security_assessment.run_cancelled`, and then re-`raise`s — re-raising matters so the `Task` object's
own `.cancelled()` bookkeeping inside asyncio stays accurate, rather than being silently swallowed
into a normal return.

**Subprocess cleanup.** The same `BaseException` distinction applies one layer down, inside
`nmap_tool.py`: the existing `await asyncio.wait_for(proc.communicate(), timeout=...)` already had an
`except asyncio.TimeoutError` branch to kill a hung process, but a *cancelled* run reaches the same
`await` point via `CancelledError`, not `TimeoutError` — a second, explicit
`except asyncio.CancelledError: proc.kill(); await proc.wait(); raise` branch was added alongside it.
Without this, cancelling a run mid-scan would stop the Python-side bookkeeping but leave the real
`nmap` OS process running untouched — an orphaned subprocess that would keep consuming CPU/network
resources and, if it later happened to write to a since-closed pipe, could error unpredictably.

**Testing.** `test_security_assessment_api.py` adds a `_SlowFakeTool` (an `await asyncio.sleep(30)`
stand-in) specifically so the in-flight-cancellation test (`test_cancelling_an_in_flight_run_kills_it
_cleanly`) exercises a genuine mid-flight `task.cancel()` — the pre-existing `_FakeTool` resolves
before a cancel request could ever reach it, which would only prove the already-completed-run
rejection path, not real cancellation. A second test constructs a `SecurityAssessmentRun` row
directly at `RUNNING` status with no corresponding task in `_run_tasks`, simulating exactly what a
post-restart process sees, and confirms it still resolves to `CANCELLED` via the direct-DB-write
branch above. Beyond the mocked suite, this was also verified against a real, live `nmap` "standard"
profile scan through the actual HTTP API in a running Docker container: cancellation completed in
~1.6s (against a natural completion time of ~12s for that profile/target), confirmed via manual
`/proc/[0-9]*/cmdline` inspection (the container's minimal `python:3.12-slim` image has no `ps`
binary) that no orphaned `nmap` process remained.

**A schema lesson surfaced while adding the `CANCELLED` enum value.** The migration
(`8f4a1c2d9e6b_add_cancelled_security_assessment_status.py`) originally added the value as lowercase
`'cancelled'`, matching `SecurityAssessmentRunStatus.CANCELLED`'s Python `.value`. Two tests then
failed against a real Postgres container with `invalid input value for enum
securityassessmentrunstatus: "CANCELLED"`. Querying `pg_enum` directly showed the four pre-existing
labels are `PENDING`/`RUNNING`/`COMPLETED`/`FAILED` — uppercase, matching the Python enum members'
*names*, not their lowercase `.value` strings — because a plain `sa.Enum(SomeEnum)` column with no
`values_callable` override serializes `.name` on the wire, not `.value`. The migration was corrected
to `ADD VALUE IF NOT EXISTS 'CANCELLED'` (uppercase); since Postgres has no `ALTER TYPE ... DROP
VALUE`, the throwaway test database had to be torn down and recreated rather than patched in place.
The Python-side `.value = "cancelled"` string is unaffected and correct as-is — it's what
`_serialize_run()` returns to the API/frontend; it was never what gets sent to Postgres.

## 8. Bugs Found by Independent Re-verification (v0.2.2)

An independent re-verification pass (nine parallel reviewers, each reading the real code fresh
rather than trusting §7's own claims) re-proved the cancellation fix correct, then found four new,
real defects — all fixed and covered by new tests.

**IPv6 scans never actually ran.** `nmap` requires a literal `-6` flag for an IPv6 target
specification; without it, nmap logs `"<target> looks like an IPv6 target specification -- you have
to use the -6 option"` to stderr and exits `0` having scanned 0 hosts. Since `run()`'s only failure
check is `proc.returncode != 0`, this was indistinguishable from, and reported identically to, a
genuine clean scan (`completed`, 0 findings, `error_message: null`) — despite `supported_types`
having always included `IOCType.IPV6`. Fixed: `_PROFILE_ARGS`'s argv now gets `-6` prepended whenever
`ioc_type == IOCType.IPV6`. Live-reproduced: manually replaying the exact quick-profile command
against `::1` with and without `-6` confirmed the root cause and the fix (with `-6`, nmap correctly
reports the host up with all common ports closed — a real, current answer, not a skipped scan).

**Profile id was never validated before spawning a run.** `start_run()` validated `tool_id` (existence
and IOC-type support) up front but never checked `profile_id` against the selected tool's own
`profiles` dict. The only check lived deep inside each tool's `run()` (e.g. `nmap_tool.py`: `if
profile_id not in _PROFILE_ARGS: return self._error(...)`), which returns an ordinary
`ProviderStatus.ERROR` result rather than raising — `_execute_run()` doesn't treat that as
exceptional, so the run reached `COMPLETED` with `error_message: null` and empty findings, exactly
the fake-clean-result failure mode this module's own design principles rule out. Fixed with a new
`UnknownProfileError`, raised in `start_run()`'s existing per-tool validation loop (`if profile_id not
in tool.profiles: raise UnknownProfileError(...)`), mapped to a `400` in the route layer alongside the
existing `UnknownToolError`. This check is tool-agnostic — it applies uniformly to every tool in
`tool_ids`, not just Nmap, since the underlying gap was in the shared service-layer validation, not
any one tool adapter.

**A malformed CIDR lookup value crashed the endpoint.** `_validate_scope()`'s
`ipaddress.ip_network(lookup.ioc_value, strict=False)` call for `IOCType.CIDR` had no error handling;
a lookup reaching this code with a value that isn't a valid network string (only reachable via the
pre-existing, unrelated lookup-creation `ioc_type_hint` override, which doesn't itself validate
value-matches-hint) raised an uncaught `ValueError`, surfacing as a raw `500` — the only validation
failure in this function that didn't produce a clean `400`. Fixed with a new `InvalidTargetError`,
raised from a `try/except ValueError` around the `ip_network()` call, mapped to `400` in the route
layer. Not an injection/RCE vector either way — the crash happens before any run row exists and
before Nmap is ever invoked.

**Completion could clobber another writer's terminal state.** `_execute_run()`'s three terminal
UPDATEs (CANCELLED/FAILED/COMPLETED) had no `WHERE status IN (...)` guard, unlike `cancel_run()`'s own
direct-DB-write fallback branch (§7), which already had one. Confirmed live via a genuine race: the
startup orphan-recovery sweep (`_recover_orphaned_running_lookups()`) marked a run FAILED while its
task was still genuinely executing (triggered out-of-band by a concurrent test process calling that
same recovery function against the same live database — not a normal in-process restart); when the
task's own success path ran moments later, its unguarded UPDATE unconditionally overwrote the row
back to COMPLETED, but never touched the (COMPLETED-path UPDATE doesn't set) `error_message` column,
leaving the stale FAILED-only message attached to a COMPLETED row — a self-contradictory result.
Fixed: all three terminal UPDATEs now carry the same `.where(status.in_([PENDING, RUNNING]))` guard
`cancel_run()` already used, each gated on `result.rowcount` before writing its own audit record.
Findings/`ProviderResultRecord`s are still always persisted regardless of the guard's outcome — only
the run's own `status`/`completed_at` write is guarded, since real scan data stays valid evidence
even if an unrelated writer already finalized the row.

Also fixed in the same pass: an empty `tool_ids` array is now rejected at the Pydantic layer
(`Field(min_length=1)`) instead of silently producing a no-op `COMPLETED` run.

## 9. Installer / Deployment

`backend/Dockerfile` installs `nmap` via `apt-get` alongside the pre-existing `gcc libpq-dev curl`.
`GET /api/v1/security-assessment/tool-health` calls `shutil.which("nmap")` at request time rather
than assuming installation succeeded — a deployment that somehow lacks the binary degrades to
"unavailable" in the UI rather than a scan silently failing partway through. `backend/requirements.txt`
gained one new dependency, `dnspython`, for the DNS enumeration tool (stdlib alone does not expose
MX/TXT/NS/CAA record types). No `k8s/` manifest change was needed — the k8s backend Deployment
already builds from this same Dockerfile.
