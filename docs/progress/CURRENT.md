# Current Status

Last updated: 2026-08-29

## Active Objective

Make Austin's real working relationships part of mail intelligence: Andrea
Durbin owns routine scheduling, and Angie Mecham is a trusted close colleague.
The local implementation is complete and verified; pushing and deploying it
remain separate production actions.

## Baseline

- Local checkout: `codex/andrea-scheduling-workflow`, based on the published UX
  release worklog at `e849e9f`.
- Repository origin: `https://github.com/amcchord/email.git`.
- Production host: `root@email.mcchord.net` (host currently reports
  `localhost`; do not rely on the server hostname for identity).
- Production OS: Debian 13 (trixie).
- Production checkout: `/opt/mail`, owned by `mailapp:mailapp`.
- Production Git at observation: clean `main` at `e849e9f`, aligned with
  `origin/main`.
- Active application services at observation: `mailapp`, `mailworker`,
  `mailworker-cron`, `mailtui`, and `caddy`.
- Supporting services: PostgreSQL 17 and Redis.
- Public entry point: Caddy on ports 80/443; FastAPI listens on
  `127.0.0.1:8000`; TUI listens on 2222/8022.

This is a point-in-time snapshot. Use `make remote-status` before relying on
live state.

## Work Queue

### P0 — Scheduling delegation and trusted colleagues

- State: ready
- Why: Austin almost never coordinates scheduling himself; Andrea owns that
  work, and messages involving Andrea or Angie need relationship-aware triage.
- Scope: AI analysis and reply prompts, thread/chat context, read-time email
  presentation, needs-reply/awaiting-response/important queues, and focused
  backend tests.
- Acceptance: routine low/normal-priority scheduling already sent to Andrea is
  removed from Austin's action queues; high/urgent exceptions remain visible;
  scheduling replies default to Andrea; direct questions from Andrea are not
  delegated back to her; and Angie is never treated as cold outreach.
- Next: Review the focused local commit and, with explicit release
  authorization, push and deploy it without a migration, then verify mailapp
  health and representative Flow/Inbox behavior.

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
- `make test` after the workflow-context implementation: 128 tests passed,
  including eight focused Andrea/Angie routing tests.
- Focused PostgreSQL compilation passed for the needs-reply and
  awaiting-response queue queries.
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

## Next Safe Action

Review the `codex/andrea-scheduling-workflow` commit. Push and deploy it only
with explicit production authorization; no schema migration or data rewrite is
required because read-time routing also corrects existing AI analyses.
