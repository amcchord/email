# Current Status

Last updated: 2026-08-30

## Active Objective

Iteratively improve the mail client toward a fast, complete modern email
workflow while treating mailbox data and mutations conservatively. Product
work is isolated in its own worktree so the concurrent AI-model task can
continue without overlapping files or Git state.

## Baseline

- Product worktree: `codex/product-polish-cycle-1` at `278dfef`, pushed to
  `origin/codex/product-polish-cycle-1`.
- Repository source baseline: `origin/main` at `0500d1a`.
- Concurrent AI-model work is owned by another process in the original
  checkout; do not edit, stage, or reconcile its files from this worktree.
- Production observation at 2026-08-30 02:55 UTC: clean `main` at `0500d1a`,
  all application and supporting services active, and `/api/health` returned
  `ok`.
- Production was inspected read-only. No deploy, restart, migration, mailbox
  mutation, or configuration change was performed in this cycle.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Work Queue

### P0 — Reliable, reconcilable mail actions

- State: ready
- Why: local mail state can diverge from Gmail when a remote mutation fails;
  fast triage also needs a trustworthy undo path.
- Scope: action persistence/retries, idempotency, reconciliation status, safe
  undo semantics, and visible failure recovery.
- Acceptance: generated-message tests prove retries cannot duplicate or lose
  an action, failures remain visible, and supported actions can be undone.
- Next: design the smallest durable outbox contract before changing the data
  model or worker behavior.

### P0 — Incremental sync checkpoint safety

- State: ready
- Why: advancing a history checkpoint after a partial failure can skip mail.
- Scope: Gmail incremental sync checkpointing, failure boundaries, retries,
  and generated fixtures.
- Acceptance: a failed page or message cannot advance beyond unprocessed
  history, and a retry converges without duplicates.
- Next: reproduce the failure with a deterministic fake Gmail history stream.

### P1 — Authenticated attachment download

- State: ready
- Why: received attachments are displayed but cannot currently be opened or
  downloaded, which is a core mail-client completeness gap.
- Scope: ownership-checked download route, shared cache/Gmail retrieval,
  filename/content-header safety, frontend loading/error UX, and generated
  attachment fixtures.
- Acceptance: cached and Gmail-fallback downloads work; cross-user,
  wrong-message, hostile-filename, and upstream-failure cases are denied or
  handled safely; browser QA uses only a generated attachment message.
- Next: implement this read-only feature as the next independently shippable
  slice.

### P1 — Fast retrieval and command surface

- State: ready
- Why: modern high-speed clients provide a discoverable command palette,
  composable search operators, and reusable saved views.
- Scope: command palette, complete shortcut registration, search operator
  parser, and saved splits/views.
- Acceptance: primary navigation and triage commands are keyboard discoverable,
  search operators compose predictably, and saved views remain account-scoped.
- Next: define the command registry and search grammar after the core safety
  items above.

## Completed This Cycle

- Enforced account ownership on sync-status reads, with indistinguishable 404s
  for missing and foreign accounts (`c3fb912`).
- Prevented stale Inbox requests, selections, details, and actions from crossing
  mailbox/search/account/view changes or component recreation (`278dfef`).
- Added persistent update/error feedback, safe retry behavior, failed-page
  rollback, and compact-list fallback on narrow screens.
- Added frontend safety tests to the standard `make check` path.

## Verification

- `make check`: 131 backend tests and 6 frontend safety tests passed; the
  frontend production build passed with only the existing large-chunk advisory.
- Browser QA passed at 1440×900 and 390×844 with generated fixtures across
  column/table preferences, selection invalidation, overlapping requests,
  component destruction/recreation, search/mailbox races, loading feedback,
  and the compact mobile fallback.
- Independent synthetic user testing reported no browser console errors.
- The synthetic API action log remained empty, confirming QA made no mail
  mutations.
- `git diff --check`: passed.

## Known Constraints and Risks

- Production contains secrets and private mailbox data. Do not copy them into
  the workspace, tests, screenshots, logs, or progress documentation.
- Opening an unread message currently marks it read. Production browser audits
  must therefore avoid opening real messages; mutation testing must use
  explicitly generated messages.
- The frontend build emits an existing bundle advisory over 500 kB. Route-level
  code splitting remains follow-up work.
- Schema, worker, OAuth, Gmail-action, calendar, and deployment changes require
  a focused recovery plan and explicit production authorization.

## Next Safe Action

Implement authenticated received-attachment download in this isolated
worktree, using generated fixtures and read-only browser verification. Continue
to avoid all files owned by the concurrent AI-model task.
