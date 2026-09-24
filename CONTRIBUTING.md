# Contributing to HORIZON GRID

Thanks for considering a contribution. This is a small, mostly solo-maintained
project — please read this before opening a PR so review goes smoothly.

## Before you start

- **Security issues**: do not open a public issue or PR. Follow
  [SECURITY.md](SECURITY.md) instead.
- **Large changes**: open an issue first to discuss the approach before
  investing significant time — this avoids a large PR being rejected over a
  design disagreement that could have been caught early.
- **License**: this project is AGPL-3.0. By contributing, you agree your
  contribution is licensed under the same terms.

## Development setup

```bash
git clone https://github.com/neshboy/horizon-grid.git
cd horizon-grid
docker compose up -d      # full stack: backend, frontend, Postgres, Redis, Neo4j, OpenSearch
```

See the root [README.md](README.md#-installation--quick-start) for the full
prerequisites and configuration walkthrough (AI backend setup, provider API
keys, etc.).

### Backend (Python / FastAPI)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # .venv/Scripts/activate on Windows
pip install -r requirements.txt
python -m pytest app/tests/unit -q                   # fast, no external services needed
python -m pytest app/tests/integration -q            # needs the docker-compose stack running
```

### Frontend (Next.js / TypeScript)

```bash
cd frontend
npm install
npx tsc --noEmit       # type-check
npx vitest run         # unit tests
npm run build           # full production build (also runs eslint)
```

## Code conventions this codebase actually enforces

- **Read the comments before you change something they explain.** Comments in
  this codebase are deliberately used to record *why* a piece of code looks
  the way it does — usually a real bug that was found and fixed, with the
  live reproduction steps. If you're changing code with a comment like this,
  understand the original bug first so you don't reintroduce it.
- **Confirm claims by reading the actual code**, not by trusting an existing
  comment/doc — this codebase's own history has repeatedly found stale
  documentation that no longer matched the implementation. If you fix
  something, update any comment/doc that described the old (wrong) behavior.
- **Tests are expected to fail for a real reason.** A test that only checks a
  status code when the response body matters, or an assertion that can never
  fail, isn't considered done — see the existing test files for the level of
  specificity expected.
- **Security-sensitive code paths** (auth, RBAC, the crawler, the Pentest
  Suite, the Security Assessment Toolkit) get extra scrutiny. If your change
  touches outbound network calls, subprocess execution, or permission checks,
  say so explicitly in the PR's "Security considerations" section.

## Submitting a PR

1. Fork, branch, make your change.
2. Run the relevant test suite(s) above — a PR that doesn't pass CI
   (`.github/workflows/backend-tests.yml`, `frontend-build.yml`) won't be
   merged.
3. Fill out the [PR template](.github/pull_request_template.md) completely,
   including the security-considerations and breaking-changes sections.
4. Keep PRs focused — one logical change per PR is much easier to review
   than a bundle of unrelated fixes.

## Reporting bugs / requesting features

Use the issue templates under **New Issue**: bug report, feature request, or
documentation issue. For anything security-related, use
[SECURITY.md](SECURITY.md)'s process instead, not an issue.
