# Current Status

Last updated: 2026-08-30

## Active Objective

User-test the deployed At a Glance display and battery milestone, then begin
the secure browser-flashing baseline: reconcile firmware source, produce
immutable per-model artifacts, and add a recoverable Web Serial installer
without claiming OTA readiness.

## Baseline

- The deployed At a Glance runtime is clean and healthy at release candidate
  `c76cb5e67e3225ee1bb55b0e4986faa3c5c3c510`; a docs-only closeout follows.
  All seven checked services are active and `mailapp` has zero
  warning-or-higher entries since restart.
- The At a Glance application commit is
  `4c5a1febe7ba6508c74e51c1a950f7fb5ca9f124`; the firmware roadmap commit is
  `1359a24671d3a738dfcf64b08238562b703663c9`.
- Production Alembic is `b9c0d1e2f3a4 (head)`. Both new tables and the scoped
  credential indexes are present. A validated 1,383,479,646-byte custom-format
  backup is protected at
  `/var/backups/mailapp/maildb-pre-at-a-glance-20260830T1503Z.dump`, mode
  `0600`, owned by `postgres`.
- The sibling `reTerminalColor` checkout remains intentionally untouched. Its
  dirty working tree and single-slot, insecure-TLS baseline are not suitable
  release artifacts.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Release Scope

- One shared catalog defines Home, Day Ahead, and Clock views; Editorial and
  Swiss designs; and landscape 16:9 / portrait 9:16 profiles. Device and web
  renderer registries fail startup when a catalog content type lacks an
  adapter.
- Fullscreen browser pages preserve the existing designs through canonical PNG
  frames at exact 1280×720 or 720×1280 geometry. Browser credentials are
  high-entropy, bound server-side to one exact view/design/profile,
  private-cache protected, and individually rotatable without changing
  firmware URLs.
- The Admin screen promotes terminals to At a Glance, exposes ready-to-open
  display cards and link rotation, and keeps existing firmware/device controls.
- Sparse battery history has a five-minute ingestion floor and 90-day
  per-device retention cleanup. Predictions require a credible discharge
  window; stale telemetry and uncertain charging stay explicit, and critical
  charge notices take precedence.
- The firmware roadmap specifies immutable per-model artifacts, Web Serial
  first install, local-only provisioning, CA validation, device enrollment,
  signed A/B OTA, rollback, staged rollout, and rescue gates.

## Verification State

- Post-rebase `make check`: 387 backend tests passed, 4 opt-in PostgreSQL tests
  skipped, 156 frontend tests passed, and the 504-module production frontend
  built.
- Focused terminal/display/battery/renderer coverage: 91 passed.
- Disposable PostgreSQL 17 rehearsal upgraded through both new revisions,
  verified tables/indexes, downgraded the browser-display revision while
  retaining battery history, and re-upgraded to head.
- Generated in-app browser QA verified exact 1280×720 and 720×1280 stage,
  image, viewport, and overflow geometry. The preserved 3:4 Day Ahead artwork
  is centered within the 9:16 frame rather than cropped or distorted.
- Compile checks, focused import lint, and `git diff --check` passed.
- Production built 506 frontend modules. Public health is `ok`, `/` returns
  200, unauthenticated terminal settings return 401, unknown display tokens
  return 404, and five scoped display records have five distinct 32-character
  credentials.
- Signed-in production QA verified the At a Glance Admin cards, live terminal
  battery states, and an exact 1280×720 Clock display with no overflow. A
  caller-supplied view override did not change the token-bound Clock content.

## Known Constraints and Follow-ups

- Browser pages are HTML delivery shells around canonical raster renderers,
  not native semantic HTML/CSS recompositions. Native 9:16 reflow is a future
  design adapter; the current milestone intentionally preserves existing art.
- Battery runtime remains unknown until real terminals provide at least three
  useful samples across 12 hours. Charging is only confirmed after
  corroborating rises; predictions are advisory and never an OTA safety gate.
- Browser flashing, local provisioning, CA-correct firmware transport,
  per-device trust, A/B partition migration, signed OTA, and staged rollout are
  documented next milestones and are not yet exposed in production.
- The deployed Calendar state-integrity release remains available for separate
  read-only user testing; this slice does not alter Calendar behavior.

## Next Safe Action

Close out the deployed release record, then inventory and reconcile the dirty
sibling firmware checkout into a clean review branch. Establish reproducible
per-model CI artifacts and exact hardware/partition metadata before exposing a
Web Serial write path; keep OTA blocked until A/B, CA validation, device trust,
and rollback gates are implemented.
