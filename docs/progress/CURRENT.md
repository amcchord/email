# Current Status

Last updated: 2026-08-30

## Active Objective

Iteratively improve the mail client toward a fast, complete modern email
workflow while treating mailbox data and mutations conservatively. Product
work remains isolated in its own worktree so the concurrent AI-model task can
continue without overlapping files or Git state.

## Baseline

- Product worktree: `codex/product-polish-cycle-1`, pushed to
  `origin/codex/product-polish-cycle-1`; product implementation is complete
  through `a41a90d`, followed only by progress documentation.
- Repository source baseline: `origin/main` at `41d2898`.
- Concurrent AI-model work is owned by another process in the original
  checkout; do not edit, stage, or reconcile its files from this worktree.
- Production observation at 2026-08-30 02:55 UTC: clean `main` at `0500d1a`,
  all application and supporting services active, and `/api/health` returned
  `ok`.
- Production was inspected read-only. No deploy, restart, migration, mailbox
  mutation, or configuration change was performed in these cycles.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Work Queue

### P0 — Reliable, reconcilable mail actions

- State: locally verified; review/merge pending
- Why: local mail state can diverge from Gmail when a remote mutation fails;
  fast triage also needs a trustworthy undo path.
- Scope: durable action outbox, idempotent retries, reconciliation status,
  exact staged undo, optimistic Inbox recovery, and visible partial failure.
- Acceptance: generated-message tests prove retries cannot duplicate or lose
  an action, failures remain visible, and supported actions can be undone.
- Next: preserve the verified branch while the separate AI owner finishes;
  then reconcile with current `origin/main` in an explicitly coordinated
  review before any production migration.

### P1 — Sync durability and account-scoped identity

- State: ready
- Why: the lossless checkpoint contract is unit-tested, but real PostgreSQL
  interleavings and account-scoped Gmail identity still need durable proof.
- Scope: disposable-PostgreSQL advisory-lock/CAS tests, composite
  `(account_id, gmail_message_id)` uniqueness migration, stale-row
  reconciliation after an unsafe legacy baseline, and a post-sync outbox.
- Acceptance: competing full/incremental jobs cannot both own a checkpoint,
  two accounts may safely contain the same Gmail ID, legacy recovery converges,
  and committed new mail always leaves durable downstream work.
- Next: provision a disposable PostgreSQL test target and prove lock lifetime
  plus competing checkpoint transactions before the schema migration.

### P1 — Fast retrieval and command surface

- State: ready
- Why: modern high-speed clients provide a discoverable command palette,
  composable search operators, and reusable saved views.
- Scope: command palette, complete shortcut registration, search operator
  parser, and saved splits/views.
- Acceptance: primary navigation and triage commands are keyboard discoverable,
  search operators compose predictably, and saved views remain account-scoped.
- Next: define the command registry and search grammar after the mutation
  durability item.

### P2 — Attachment cache lifecycle

- State: ready
- Why: secure received-attachment downloads now work, but cached blobs need an
  explicit retention and quota policy.
- Scope: bounded per-user retention, orphan cleanup, observability, and safe
  retry behavior during cleanup.
- Acceptance: cleanup cannot cross users or delete an in-flight download, and
  generated cache-pressure tests keep storage within policy.
- Next: choose retention and per-user quota defaults before adding cleanup.

## Completed This Cycle

- Enforced account ownership on sync-status reads (`c3fb912`).
- Prevented stale Inbox requests, selections, details, and actions from
  crossing result-shaping state; added persistent recovery UI and compact
  narrow-screen fallback (`278dfef`).
- Added authenticated, ownership-checked received-attachment downloads with
  bounded Gmail retrieval, safe caching/headers/filenames, accessible loading,
  error, retry, and mobile UX, plus generated browser verification (`ba903b5`).
- Made Gmail sync checkpoints lossless: strict batch completeness, fail-fast
  processing, authoritative high-water handling, per-account PostgreSQL
  transaction advisory locks, versioned full-scan checkpoints, exact CAS page
  ownership, existing-message refresh, and atomic baseline replay (`ae36211`).
- Added optimistic Inbox action removal/recovery, request-scoped idempotency,
  keyboard Undo, partial-failure rollback, and actionable status UI
  (`8f696d0`).
- Added a generated local-only action harness and browser scenarios without
  reading or mutating real mail (`55ed38c`).
- Implemented the durable PostgreSQL action outbox, exact staged Undo,
  per-email ordering, bounded Gmail/Redis I/O, sync overlay, visible failure
  recovery, and authenticated idempotency reconciliation; the implementation
  is verified locally and remains undeployed (`ee4fa19`).
- Made list/table actions keyboard operable, moved 375px list and bulk targets
  to at least 44px, prevented narrow-page overflow, and transferred real DOM
  focus to the adjacent row after keyboard triage. Ambiguous submissions retain
  their original queue position so newer same-email intent cannot overtake
  confirmation (`a41a90d`).

## Verification

- Latest `make check`: 215 backend tests passed, 4 disposable-PostgreSQL tests
  skipped by default, and 35 frontend tests passed; the production build
  passed with only the existing large-chunk advisory.
- Forty-three generated durable-action tests cover every supported transition,
  strict request validation, cross-account staging, idempotency, exact bulk
  undo, retry, bounded lease recovery, canonical Gmail results, lock ordering,
  credential failures, orphan recovery, worker registration, sync rebasing,
  Gmail transport deadlines, bounded Redis publication, lost-response lookup,
  and persistent failure visibility.
- The 23 generated sync tests cover partial/malformed batches, poison-message
  rollback, monotonic high-waters, busy locks, stale checkpoint owners, legacy
  recovery, existing-message refresh, replay update/delete, expired baselines,
  and atomic completion.
- A disposable PostgreSQL 17 cluster upgraded from the initial migration to
  `z7a8b9c0d1e2`, downgraded one revision, and upgraded again. Four opt-in
  two-session tests passed for concurrent idempotency, strict per-email
  sequencing, mixed-ownership atomicity, and claim-versus-Undo races.
- Browser QA passed with generated fixtures at 1280x720 and 375x844. The
  375px page had no horizontal overflow; list and bulk actions measured at
  least 44px. Two lost create responses plus lost lookup responses displayed
  persistent confirmation, then reconciled by idempotent POST without
  rollback. Desktop keyboard archive removed the row, opened the adjacent
  message, and moved DOM focus to that adjacent row. Browser console errors:
  none.
- Independent user, safety, and worker reviews were completed; their lock-order,
  bounded-lease, projection-reconciliation, and generated-fixture blockers were
  addressed. Generated API action logs remained empty; no real mail mutation
  was performed.
- Python compilation and `git diff --check`: passed.

## Known Constraints and Risks

- Production contains secrets and private mailbox data. Do not copy them into
  the workspace, tests, screenshots, logs, or progress documentation.
- Opening an unread message currently marks it read. Production browser audits
  must therefore avoid opening real messages; mutation testing must use
  explicitly generated messages.
- The sync-checkpoint suite still needs broader real-PostgreSQL CAS coverage;
  the new mail-action interleavings now have focused two-session coverage.
- The durable mail-action migration and worker are locally verified but not
  deployed; no production database has the new table or column.
- This product branch predates the separately owned AI-provider commits now on
  `origin/main`. Do not rebase or resolve the shared worker registry until its
  owner confirms the coordination point.
- Failed full-sync attempts can commit new mail before a later page fails; the
  mail is retained safely, but durable notification/analysis handoff remains a
  follow-up.
- The frontend build emits an existing bundle advisory over 500 kB. Route-level
  code splitting remains follow-up work.

## Next Safe Action

Preserve the reviewed, pushed product branch without rebasing it onto the
separately owned AI work. On the next cycle, confirm the coordination point,
then reconcile the shared worker registry and re-run all checks before any
merge or explicitly authorized deployment.
