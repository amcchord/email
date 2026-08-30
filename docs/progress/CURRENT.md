# Current Status

Last updated: 2026-08-30

## Active Objective

Deploy the first At a Glance platform milestone: shared e-ink/browser views,
scoped 16:9 and 9:16 browser links, terminal battery-life guidance, and an
extensible renderer catalog. Browser flashing and managed OTA remain the next
firmware milestones, not capabilities claimed by this release.

## Baseline

- GitHub `main` and production are clean, healthy, and exact at Calendar
  closeout `a2c02bfcf62f0147209b365cdb918cb915d2a762`; all seven checked
  services are active.
- The rebased At a Glance application commit is
  `4c5a1febe7ba6508c74e51c1a950f7fb5ca9f124`; the firmware roadmap commit is
  `1359a24671d3a738dfcf64b08238562b703663c9`.
- The release adds two Alembic revisions after current production head
  `z7a8b9c0d1e2`: sparse battery history, then scoped browser-display
  credentials. Both are additive; old application code ignores the new tables.
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

Push the reviewed At a Glance candidate, fast-forward GitHub `main`, create and
verify a protected PostgreSQL backup, deploy the exact commit, run both Alembic
revisions, rebuild the frontend, restart only `mailapp`, and verify health,
schema head, services, logs, scoped link behavior, and the user-facing Admin
path.
