# Current Status

Last updated: 2026-08-30

## Active Objective

Iteratively improve the mail client toward a fast, complete modern email
workflow while treating mailbox data and mutations conservatively. Product
work remains isolated in its own worktree so the concurrent AI-model task can
continue without overlapping files or Git state.

## Baseline

- Product worktree: `codex/product-polish-cycle-1` at `ae36211`, pushed to
  `origin/codex/product-polish-cycle-1`.
- Repository source baseline: `origin/main` at `0500d1a`.
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

- State: ready
- Why: local mail state can diverge from Gmail when a remote mutation fails;
  fast triage also needs a trustworthy undo path.
- Scope: durable action outbox, idempotent retries, reconciliation status,
  safe undo semantics, and visible failure recovery.
- Acceptance: generated-message tests prove retries cannot duplicate or lose
  an action, failures remain visible, and supported actions can be undone.
- Next: define the smallest durable action/outbox contract before changing the
  data model or worker behavior.

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

## Verification

- `make check`: 172 backend tests and 10 frontend tests passed; the frontend
  production build passed with only the existing large-chunk advisory.
- The 23 generated sync tests cover partial/malformed batches, poison-message
  rollback, monotonic high-waters, busy locks, stale checkpoint owners, legacy
  recovery, existing-message refresh, replay update/delete, expired baselines,
  and atomic completion.
- Browser QA passed at 1440x900 and 390x844 with generated fixtures for Inbox
  request races and received-attachment loading, failure/retry, download, table,
  and mobile states.
- Independent user and safety reviews reported no blocking findings. Generated
  API action logs remained empty; no real mail mutation was performed.
- Python compilation and `git diff --check`: passed.

## Known Constraints and Risks

- Production contains secrets and private mailbox data. Do not copy them into
  the workspace, tests, screenshots, logs, or progress documentation.
- Opening an unread message currently marks it read. Production browser audits
  must therefore avoid opening real messages; mutation testing must use
  explicitly generated messages.
- Real PostgreSQL lock/CAS interleavings are not yet integration-tested.
- Failed full-sync attempts can commit new mail before a later page fails; the
  mail is retained safely, but durable notification/analysis handoff remains a
  follow-up.
- The frontend build emits an existing bundle advisory over 500 kB. Route-level
  code splitting remains follow-up work.

## Next Safe Action

Design and implement the durable action reconciliation/undo outbox with
generated messages in this isolated worktree. Continue to avoid every file
owned by the concurrent AI-model task.
