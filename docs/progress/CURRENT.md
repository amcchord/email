# Current Status

Last updated: 2026-08-29

## Active Objective

Prepare the verified OpenAI GPT-5.6 and Anthropic Claude 5 provider expansion
for review and release. The implementation is complete locally; committing,
installing the scoped AustinLand credentials on production, and deploying are
separate follow-up actions.

## Baseline

- Local checkout: `codex/openai-anthropic-model-support`, based on the published
  workflow release `0500d1a`, with the provider expansion present as reviewed
  working-tree changes.
- Repository origin: `https://github.com/amcchord/email.git`.
- Production host: `root@email.mcchord.net` (host currently reports
  `localhost`; do not rely on the server hostname for identity).
- Production OS: Debian 13 (trixie).
- Production checkout: `/opt/mail`, owned by `mailapp:mailapp`.
- Production Git at observation: clean `main` at `ab33499`, aligned with
  `origin/main`.
- Active application services at observation: `mailapp`, `mailworker`,
  `mailworker-cron`, `mailtui`, and `caddy`.
- Supporting services: PostgreSQL 17 and Redis.
- Public entry point: Caddy on ports 80/443; FastAPI listens on
  `127.0.0.1:8000`; TUI listens on 2222/8022.

This is a point-in-time snapshot. Use `make remote-status` before relying on
live state.

## Work Queue

### P0 — Release GPT-5.6 and Claude 5 support

- State: ready
- Why: AI workloads can select the best cost/quality profile instead of being
  tied to one provider and one reasoning configuration.
- Scope: provider/model registry, workload defaults, Responses and Messages
  API adapters, preference API/UI, setup, dependency lock, and documentation.
- Acceptance: the six requested models and their valid effort levels work in
  chat, processing, replies, briefings, bundles, and unsubscribe where
  compatible; scoped credentials are installed securely; post-deploy health
  and one user-facing AI flow pass.
- Next: Review and commit the local branch. Deploy and install AustinLand keys
  only with explicit production authorization.

### P1 — Durable Google account authorization

- State: ready
- Why: External Google accounts can require weekly reauthorization while an
  OAuth app remains External/Testing. The UX release will surface structured
  recovery, but the Google Cloud publishing change remains an explicitly
  separate external configuration action.
- Scope: Google Cloud OAuth publishing status plus refresh-token reliability.
- Acceptance: External accounts remain connected beyond seven days and
  permanent authorization failures present a clear reconnect path.
- Next: Confirm the Google Cloud OAuth publishing status and, with separate
  authorization, move it out of Testing if needed before reauthorizing affected
  accounts once.

## Baseline Verification

- `make setup`: passed with Python 3.13.15 and locked frontend dependencies.
- `make test`: 117 tests passed.
- `make frontend-build`: passed; existing Svelte accessibility and large-chunk
  warnings remain.
- `make check` after the UX implementation: 128 tests passed and the frontend
  production build completed with no Svelte accessibility diagnostics. The
  remaining build notice is the existing large JavaScript chunk advisory.
- `make check` for the workflow-context release: 128 tests passed, including
  eight focused Andrea/Angie routing tests, and the frontend production build
  passed with only the existing large-chunk advisory.
- `make check` for the provider expansion: 136 tests passed and the frontend
  production build passed with only the existing large-chunk advisory.
- Python bytecode compilation and `git diff --check` passed. Seven focused
  provider-registry, preference, and request-shape tests passed.
- AustinLand created project entries `Email-openai` (minted) and
  `Email-anthropic` (shared assignment). Provider catalog checks found all six
  requested model IDs, and minimal no-data prompts succeeded against GPT-5.6
  Luna at `none` effort and Claude Sonnet 5 at `low` effort. Both provider
  adapters completed a forced structured-tool call, and OpenAI completed the
  stateless function-result continuation used by chat. No credential was
  printed, committed, or written to project documentation.
- Focused PostgreSQL compilation passed for the needs-reply and
  awaiting-response queue queries.
- Post-deploy verification at `ab33499`: production was clean, all application
  services were active, public health returned `ok`, no error-level API/worker
  entries appeared after startup, and a production-side Andrea-CC routing
  assertion passed without reading mailbox data.
- Three follow-up `make frontend-build` runs passed for the mobile Compose
  overflow correction and concise sender label found during visual QA.
- Authenticated production screenshots passed at 1440×900 and 390×844 for
  Flow, Inbox, Calendar, Compose, Subscriptions, Stats, and the More menu.
- `make remote-status` after the workflow implementation: production Git was
  clean and aligned at `e849e9f`, all seven checked services were active, and
  `/api/health` returned status `ok`; the post-release mailapp error log had no
  entries.
- `npm ci`: reported 11 dependency advisories (4 moderate, 6 high, 1 critical).
  Dependency review is future scoped work; no automatic audit fix was applied.

## Known Constraints and Risks

- The API configuration hardcodes `/opt/mail/.env`, frontend build paths, and
  attachment storage paths. The local bootstrap is intended for tests and
  builds, not a fully isolated local production clone.
- Production contains secrets and mailbox data. They must not be copied into
  this repository or progress documentation.
- `goals.md` has historical non-goals that no longer match the implemented
  calendar features; current code and README take precedence.
- The server checkout is owned by `mailapp`, so Git commands run as root need a
  `safe.directory` override. Prefer running application commands as `mailapp`.
- Database migrations and worker changes can affect live email processing and
  require explicit deployment authorization and a recovery plan.
- The frontend build emits a bundle chunk advisory over 500 kB. It does not
  fail the build; route-level code splitting remains scoped follow-up work.
- The frontend dependency audit reports 11 advisories as of 2026-08-26. Review
  the dependency paths and upgrades before changing lockfiles; do not apply a
  breaking automatic audit fix casually.
- AustinLand is local to the development Mac. Production cannot consume its
  vault directly; an authorized deployment must transfer only the two scoped
  Email provider keys into protected runtime configuration without exposing
  them in Git, logs, or chat.

## Next Safe Action

Review and commit the provider-support branch. If production deployment is
explicitly authorized, identify the exact commit, install the locked OpenAI SDK
and scoped AustinLand keys, restart only the affected API/worker services, then
verify health and one AI flow. Otherwise resume the read-only Google OAuth
publishing-status check.
