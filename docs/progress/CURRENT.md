# Current Status

Last updated: 2026-08-29

## Active Objective

Make Google account authorization durable beyond the seven-day lifetime that
applies while an External OAuth app remains in Testing. The OpenAI GPT-5.6 and
Anthropic Claude 5 provider expansion is complete in production.

## Baseline

- Local checkout: `codex/openai-anthropic-model-support` at application release
  `40bbc48`, with only the deployment closeout documentation following it.
- Repository origin: `https://github.com/amcchord/email.git`.
- Production host: `root@email.mcchord.net` (host currently reports
  `localhost`; do not rely on the server hostname for identity).
- Production OS: Debian 13 (trixie).
- Production checkout: `/opt/mail`, owned by `mailapp:mailapp`.
- Production application release: clean `main` including `40bbc48`, aligned
  with `origin/main` at verification.
- Active application services at observation: `mailapp`, `mailworker`,
  `mailworker-cron`, `mailtui`, and `caddy`.
- Supporting services: PostgreSQL 17 and Redis.
- Public entry point: Caddy on ports 80/443; FastAPI listens on
  `127.0.0.1:8000`; TUI listens on 2222/8022.

This is a point-in-time snapshot. Use `make remote-status` before relying on
live state.

## Work Queue

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
- Production verification for `40bbc48`: OpenAI 2.54.0 and both scoped runtime
  credentials loaded, the model controls were present in the built frontend,
  and application-adapter calls succeeded against Terra/medium, Luna/low, and
  Sol/high. Public health returned `ok`, all seven services were active, the
  checkout was clean, and the API/worker error-level log count after restart
  was zero.
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
- AustinLand is local to the development Mac. Production now holds only the two
  scoped Email provider keys in its protected runtime configuration; future
  rotation must use the same no-log, no-Git transfer path.

## Next Safe Action

Confirm the Google Cloud OAuth application publishing status without changing
it. If it remains External/Testing, obtain explicit authorization for the
publishing change and subsequent one-time reauthorization of affected accounts.
