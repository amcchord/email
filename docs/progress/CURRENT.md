# Current Status

Last updated: 2026-08-29

## Active Objective

Ship and deploy the app-wide user experience release identified by the
2026-08-29 production UI audit: responsive mobile layouts, consistent global
navigation and page states, trustworthy account health, clearer mail/Flow/
calendar/compose interactions, safer subscription cleanup, corrected stats,
and accessibility improvements.

## Baseline

- Local checkout: `main` at `15ff041`, tracking `origin/main`.
- Repository origin: `https://github.com/amcchord/email.git`.
- Production host: `root@email.mcchord.net` (host currently reports
  `localhost`; do not rely on the server hostname for identity).
- Production OS: Debian 13 (trixie).
- Production checkout: `/opt/mail`, owned by `mailapp:mailapp`.
- Production Git at observation: clean `main` at `15ff041`, aligned with
  `origin/main`.
- Active application services at observation: `mailapp`, `mailworker`,
  `mailworker-cron`, `mailtui`, and `caddy`.
- Supporting services: PostgreSQL 17 and Redis.
- Public entry point: Caddy on ports 80/443; FastAPI listens on
  `127.0.0.1:8000`; TUI listens on 2222/8022.

This is a point-in-time snapshot. Use `make remote-status` before relying on
live state.

## Work Queue

### P0 — App-wide UX release

- State: verifying
- Why: The authenticated production audit found the mobile shell unusable at
  390px, contradictory sync health, hidden feature pages, unsafe account
  defaults in Compose, misleading subscription/statistics data, dense AI and
  calendar surfaces, and accessibility/loading gaps.
- Scope: frontend application shell, navigation, responsive layouts, page
  states, account status, inbox previews, Flow triage, Calendar, Compose,
  Subscriptions, Stats, accessibility, focused backend data normalization, and
  tests.
- Acceptance: all ten audited improvements are implemented; desktop and mobile
  screenshots are verified; `make check` passes; the reviewed commit is pushed
  to `origin/main`; production is backed up when needed, deployed, and passes
  health, service, log, and user-flow verification.
- Next: Commit and push the reviewed UX-only file set, deploy the exact commit,
  then verify authenticated desktop/mobile flows and production health.

### P1 — Durable Google account authorization

- State: ready
- Why: External Google accounts can require weekly reauthorization while an
  OAuth app remains External/Testing. The UX release will surface structured
  recovery, but the Google Cloud publishing change remains an explicitly
  separate external configuration action.
- Scope: Google Cloud OAuth publishing status plus refresh-token reliability.
- Acceptance: External accounts remain connected beyond seven days and
  permanent authorization failures present a clear reconnect path.
- Next: After this release, confirm and change the Google Cloud OAuth publishing
  status with separate authorization if it is still in Testing.

## Baseline Verification

- `make setup`: passed with Python 3.13.15 and locked frontend dependencies.
- `make test`: 117 tests passed.
- `make frontend-build`: passed; existing Svelte accessibility and large-chunk
  warnings remain.
- `make check` after the UX implementation: 128 tests passed and the frontend
  production build completed with no Svelte accessibility diagnostics. The
  remaining build notice is the existing large JavaScript chunk advisory.
- `make remote-status`: production Git was clean and aligned at `15ff041`, all
  seven checked services were active, and `/api/health` returned status `ok`.
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

Commit the explicit UX file set without staging the parallel workflow-context
task, push the reviewed commit to `origin/main`, deploy without a database
migration, and complete health plus authenticated visual verification.
