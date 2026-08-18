# Backend Test Root-Cause Report

Investigation into the reported symptom: backend tests fail in the existing
dev setup, but work again after deleting the project and reinstalling from
scratch. Root-caused rather than papered over — the fix does not require
anyone to ever delete and reinstall the project again.

## 1. Original failure

Reproduced by running the test suite exactly as it stood, with zero changes
made first, against `backend/.venv` (one of two virtualenvs present in the
repo):

```
cd backend
.venv/Scripts/python.exe -m pytest app/tests/unit -q
```

Result: 4 collection errors, 0 tests run.

```
ModuleNotFoundError: No module named 'cryptography'
```

raised from `app/security_assessment/tls_tool.py:33` (`from cryptography
import x509`), which cascades into `app/core/security_assessment.py` →
`app/tests/unit/test_security_assessment_service.py` and three other files
that import that chain, aborting collection entirely.

## 2. Exact reproduction steps

```
cd backend
.venv/Scripts/python.exe -m pytest app/tests/unit -q
```

## 3. Failure frequency

**Deterministic, 2/2 runs, identical error both times.** This is an
import-time `ModuleNotFoundError` during test *collection*, not a runtime
assertion — there is no code path by which it could pass on a retry without
something in the environment changing.

## 4. Root cause

Two divergent backend virtualenvs coexist in this repo, `backend/.venv` and
`backend/.venv_test`, and nothing in the repo documented which one was
"the" canonical one for running tests (this exact gap was already noted,
but not fixed, in an earlier QA pass — see `docs/TESTING.md`'s
now-updated "Windows-specific gotchas" section).

- **`backend/.venv`** had `cryptography` missing entirely, and every other
  package resolved to whatever was *latest on PyPI* at whatever point each
  was separately installed — e.g. `fastapi==0.141.1` against a pinned
  `fastapi==0.115.0`, `pytest==9.1.1` against pinned `8.3.3`,
  `starlette==1.4.1` against pinned `0.38.6`. This venv was never installed
  from `requirements.txt`; it drifted from a long history of ad-hoc,
  unpinned `pip install <package>` calls.
- **`backend/.venv_test`** was much closer to `requirements.txt` but still
  had its own drift: `python-jose` at `3.4.0` where a fix earlier in this
  same investigation had bumped the pin to `3.5.0`, and `dnspython` at
  `2.8.0` against a pinned `2.7.0`.

A second, independent contributing root cause: **`requirements.txt` pinned
`asyncpg==0.29.0`, which has no prebuilt wheel for Python 3.13 on Windows**
(confirmed directly against PyPI's release file listing). A bare
`pip install -r requirements.txt` on this machine's Python 3.13 fails
trying to compile `asyncpg` from source (`Microsoft Visual C++ 14.0 or
greater is required`). This is almost certainly *why* the two venvs
diverged in the first place — whoever/whatever set each one up independently
worked around this wall differently (or not at all), rather than there
being one documented, working setup path.

## 5. Why a clean reinstall appeared to fix it

A full delete-and-reinstall naturally produces exactly **one** fresh venv,
installed once from the *current* `requirements.txt`. That sidesteps the
two-venv inconsistency entirely (there's nothing to diverge from), so it
"fixes" the symptom — without addressing the actual defect (the duplicate,
undocumented, drifted environments), which could recur the next time a
second venv gets created for some other purpose.

## 6. Actual fix

1. Deleted `backend/.venv` (the broken one — pure generated, regenerable
   content; zero unique source, config, or data; already `.gitignore`d).
2. Bumped `asyncpg` to `0.30.0` in `requirements.txt` — the first version
   with real `cp313` Windows wheels, verified against PyPI's file listing.
   No direct `asyncpg` usage exists anywhere in `app/` (confirmed via
   grep) — it's only reached through SQLAlchemy's async dialect, so this
   is a low-risk patch bump.
3. Reinstalled `backend/.venv_test` from the current `requirements.txt`
   (`pip install -r requirements.txt`), bringing `python-jose` and
   `dnspython` back in sync. Verified afterward: **0 mismatches across
   all 32 pinned packages** (installed versions programmatically diffed
   against `requirements.txt`).
4. Declared `backend/.venv_test` the one canonical backend virtualenv for
   this repo and documented the exact setup command in
   `docs/TESTING.md`, removing the "not documented anywhere" gap that
   doc itself had already flagged.
5. Documented (in `docs/TESTING.md`) that `docker compose up -d postgres
   redis` alone leaves an empty schema — migrations only run
   automatically when the `backend` service itself starts — and gave the
   exact `alembic upgrade head` command to run against the host-published
   port. Discovered this because running the full suite against fresh
   containers without it produced 36 failed + 27 errors, all
   `relation "... does not exist"`, which looks like an application bug
   but is a missing setup step.

## 7. Files changed

- `backend/requirements.txt` — `asyncpg` 0.29.0 → 0.30.0 (this
  investigation); `python-jose` and `cryptography`/`pyasn1` pins were
  already corrected earlier in this same session for an unrelated CVE
  finding, which is part of why `.venv_test` had drifted from it again.
- `docs/TESTING.md` — declared `.venv_test` canonical, added the setup
  command, added the migration step to "Running the backend tests",
  updated the bcrypt gotcha section to reflect the current fixed state.
- Deleted: `backend/.venv` (generated, not tracked by git).
- Deleted: `backend/backend/` (an unrelated empty stray directory,
  Docker's own auto-created bind-mount target from an earlier path typo
  in this session — unrelated to the venv investigation but cleaned up
  while in the area).

## 8. Tests added

No new automated test was added. The root cause is environment/tooling
drift between two ambient local virtualenvs, not applicaion logic — there
is no meaningful way to encode "no second stale venv exists on disk" as a
pytest test that runs *inside* a venv. The regression safeguard is
structural instead: one documented venv, one command to create it, and a
`requirements.txt` whose every pin is confirmed installable on the actual
target platforms (verified against both a Linux container matching
`backend/Dockerfile` and native Windows).

## 9. Before/after results

| | Before | After |
|---|---|---|
| `backend/.venv` unit tests | 4 collection errors, 0 run | *(deleted)* |
| `backend/.venv_test` unit tests | 282 passed (already using the right venv accidentally) | 282 passed |
| Fresh `pip install -r requirements.txt`, native Windows | **Fails** (asyncpg needs a C compiler) | **Succeeds** |
| Fresh `pip install -r requirements.txt`, `python:3.12-slim` container | Succeeds | Succeeds |
| Pinned-vs-installed mismatches in `.venv_test` | 3 (`python-jose`, `dnspython`, plus whatever else had silently drifted) | 0 of 32 |

## 10. Repeated test results

`backend/.venv_test`, unit suite, 5 consecutive runs, no changes between
runs: **282 passed, every time** (20.6–21.8s each). No flakiness observed.

A genuinely fresh venv created from scratch on this machine
(`python -m venv` + `pip install -r requirements.txt`, native Windows, no
Docker): **282 passed** on the first run.

## 11. Clean-install results

**PASS**, verified two independent ways:
- Native Windows, brand-new venv: fresh install succeeds (post-asyncpg-fix),
  282/282 unit tests pass.
- `python:3.12-slim` container (matches `backend/Dockerfile` exactly): fresh
  install succeeds, a direct `jose.jwt.encode`/`decode` round trip works,
  282/282 unit tests pass, and a fresh `pip-audit` in that same container
  confirms only the four already-documented, deliberately-deferred
  advisories remain (`starlette`, `lxml`, `pytest`, `ecdsa` — see
  `SECURITY.md`).

## 12. Existing-install results

**PASS.** `backend/.venv_test`, now fully synced to `requirements.txt` (0
mismatches), passes the unit suite 5/5 consecutive runs. Against real
Postgres/Redis with migrations applied, the combined unit+integration suite
went from 36 failed/27 errors (no migrations applied) to **344 passed**, 4
failed + 6 errors remaining — all `RuntimeError: Event loop is closed`,
which is a pre-existing, already-documented issue (see `docs/TESTING.md`
"Gotcha 2": SQLAlchemy/Redis connection pools bound to a since-closed
per-test event loop, triggered specifically when multiple integration test
files that touch real infra run together in one session) predating this
investigation and unrelated to the venv-drift root cause. Not fixed in
this pass — it's a separate, disclosed, pre-existing test-isolation issue,
not something introduced or masked here. The unit suite, which is what
actually gates CI, is unaffected by it (0 unit tests touch real Postgres/
Redis connection pools).

## 13. CI results

`.github/workflows/backend-tests.yml`'s `unit` job runs
`app/tests/unit + test_api_health.py` on a bare GitHub Actions runner —
exactly the self-contained subset unaffected by the event-loop gotcha above
— and has been green on every run since the dependency fixes in this
session landed. Its separate `integration-docker` job runs the full
integration suite *inside the real backend container* (via
`docker compose exec`), which naturally has migrations already applied
(the `backend` service's own startup runs them) and correct
container-network hostname resolution — both gaps this local investigation
hit are structurally absent in that path, which is why CI has stayed green
throughout.

## 14. Remaining risks

- The pre-existing "Event loop is closed" cross-file integration-test
  isolation issue (`docs/TESTING.md` Gotcha 2) is real but unrelated to
  this investigation's scope; it only affects running multiple
  infra-touching integration files together outside the container-based CI
  path.
- `starlette`, `lxml`, `pytest`, and `ecdsa` remain on versions with known
  advisories, deliberately deferred per `SECURITY.md` (starlette requires
  a coordinated FastAPI bump; lxml/pytest are major-version bumps needing
  their own regression pass; ecdsa has no upstream fix).
- No automated check currently prevents a *third* stray venv from being
  created and drifting again in the future — the fix here is procedural
  (one documented venv, one documented setup command) rather than
  mechanically enforced.

## 15. Final verdict

# BACKEND TEST STABLE

Verified via: deterministic reproduction of the original failure, a full
before/after comparison, 5 consecutive clean passes of the existing venv,
a first-try pass of a genuinely fresh venv on the actual affected platform
(native Windows), a fresh install verified in the real target container
image, and a green CI history throughout. The one remaining known issue
(cross-file event-loop teardown in the integration suite) is pre-existing,
already documented, does not affect the unit suite CI gates on, and is
called out above rather than hidden.
