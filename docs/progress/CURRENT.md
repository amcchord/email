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
  through the safe attachment-preview gallery at `8fd46a0`.
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

- State: command surface and structured search complete; saved views deferred
- Why: modern high-speed clients provide a discoverable command palette,
  composable search operators, and reusable saved views.
- Scope: truthful executable command palette, complete shortcut registration,
  search operator parser, and saved splits/views.
- Acceptance: primary navigation and triage commands are keyboard discoverable,
  search operators compose predictably, and saved views remain account-scoped.
- Next: coordinate account-scoped saved-view persistence after the separate AI
  owner releases the shared authentication contract. Keep search-history and
  saved-query persistence out of URLs until its privacy/retention contract is
  explicit.

### P2 — Attachment cache lifecycle

- State: locally verified, independently reviewed, committed, and pushed
- Why: secure received-attachment downloads now work, but cached blobs need an
  explicit retention and quota policy.
- Scope: bounded per-user retention, orphan cleanup, observability, and safe
  retry behavior during cleanup.
- Acceptance: cleanup cannot cross users or delete an in-flight download, and
  generated cache-pressure tests keep storage within policy.
- Next: coordinate migration of the separate AI-owned Chat attachment path
  before claiming that all attachment consumers share this lifecycle.

### P2 — Safe attachment preview and download trust

- State: locally verified, independently reviewed, committed, and pushed
- Why: modern triage needs fast text/image/PDF inspection without trusting
  sender MIME metadata or silently downloading derivative preview bytes.
- Scope: owned byte-classified preview API, bounded pipeline admission,
  normalized raster/text renderers, untrusted PDF handoff, risk cues,
  confirmation-required downloads, accessible desktop/mobile gallery, and
  stale/cancelled request handling.
- Acceptance: generated tests and browser audits prove ownership isolation,
  renderer/type agreement, bounded CPU/memory admission, original-byte
  downloads, keyboard/focus behavior, responsive and short-height layouts,
  terminal/retry/abort states, and an empty mutation log.
- Next: keep raw PDFs explicitly untrusted and the separate AI-owned Chat
  attachment path outside this contract. Deploy only on explicit request.

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
- Added an accessible executable command palette with deterministic ranking,
  live handler/enabled-state truth, descriptive unavailable actions, exact
  focus restoration, modal key ownership, responsive 375px layout, complete
  navigation registration, real Inbox reply/forward actions, stack-safe page
  cleanup, and shifted-key normalization (`21fcb11`).
- Prevented command-surface mutation races: Compose/Flow sends have defensive
  reentry guards and remain outside the palette until send idempotency exists;
  Flow Ignore and Todo mutations return their promises, expose disabled state,
  and reconcile delayed completion to the captured item without clearing a
  newer cross-source reply or draft (`21fcb11`).
- Added composable structured email search with AND/OR groups, exclusions,
  exact phrases, sender/recipient/body/date/state/folder/account/label filters,
  local grammar feedback, accessible suggestions and removable chips,
  fail-closed ownership, bound JSONB/recipient predicates, deterministic
  sorting, truthful mixed-folder actions, and generated desktop/mobile/race
  verification (`0e8f8fd`).
- Bounded canonical received-attachment caching per user with 512 MiB hard and
  384 MiB low-water limits, 30-day idle retention, orphan/temp grace periods,
  fixed sharded cross-process locks, no-follow directory-descriptor I/O,
  cancellation-safe download/write behavior, duplicate-safe daily cleanup,
  aggregate observability, terminal/retryable UI states, and generated
  pressure/browser verification (`fe57077`).
- Added a safe attachment-preview gallery with the same owned membership join,
  two-slot retrieval-through-render admission, byte-derived text/raster/PDF
  contracts, metadata-stripped images, untrusted native PDF handoff, active and
  mismatched-file warnings, original-byte downloads, exact modal focus,
  three-transfer admission, and generated desktop/mobile verification
  (`8fd46a0`).

## Verification

- Latest `make check`: 293 backend tests passed, 4 disposable-PostgreSQL tests
  skipped by default, and 91 frontend tests passed; the production build
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
- Generated command-surface browser QA passed at 1280x720 and 375x812. Cmd+K
  opened and toggled the palette without browser-focus leakage; no-match Enter
  was inert; Escape restored the exact opener; shortcut help owned focus and
  its configured close key; disabled commands were keyboard-selected with an
  associated reason; Chat, Todos, and Flow registrations did not leak across
  navigation; and the 375px sheet had no horizontal overflow with a trapped
  focus path. Browser console errors: none.
- The localhost-only `.example.test` command harness rejected every mutating
  method. Its final audit reported empty `mutation_attempts` and
  `unknown_routes`; no real message was opened or changed.
- Generated structured-search QA passed for desktop and exact 375x812 mobile
  viewports: keyboard suggestions and Escape hierarchy, compound Unicode and
  quoted filters, chip removal, local and backend validation, retained results
  after 422/503 failures, no-match recovery, account preservation, mailbox
  restoration, and 44px/16px mobile controls without page overflow. An
  intentionally slow response completed after a newer fast response while the
  fast result remained authoritative. Trash, Spam, Sent, and mixed-folder
  scenarios exposed truthful scope, recipient rendering, Restore/Not Spam,
  and disabled ambiguous bulk actions.
- The structured-search harness used immutable `.example.test` fixtures,
  bound only to localhost, rejected all mutation methods, and finished with
  empty `mutation_attempts` and `unknown_routes`. No message was opened and
  no real mail, production service, or mailbox state was read or changed.
- Independent parser, UX, safety, and user-test agents reviewed the slice. All
  ownership, recipient JSON, OR scope, action reconciliation, protected-folder
  action, and scope-truth P0/P1 findings were corrected; the final safety pass
  found no remaining P0/P1 blocker.
- Generated attachment QA passed at 1280px desktop and exact 375x812 mobile.
  The mobile page had no horizontal overflow, every attachment target measured
  at least 44px, long Unicode/path/control filenames remained contained, and
  terminal 409/413/422 failures disabled the primary chip without showing a
  misleading Retry. A transient 503 recovered on Retry, while navigation
  cancelled a delayed request and suppressed stale feedback.
- The attachment harness audit recorded the expected 422, 503-to-200, 409, and
  aborted 499 reads, with empty mutation attempts and unknown routes. It used
  generated `.example.test` mail only. Independent backend and UX reviewers
  reported no remaining P0/P1 blocker in the canonical lifecycle.
- Independent feature and safety reviews identified and then cleared command
  lifecycle, modal ownership, duplicate-send, inaccessible disabled-state, and
  delayed Flow mutation blockers. The generated-user agent validated the
  harness but could not acquire a browser; the primary browser run completed
  those scenarios, and the final code review found no remaining P0/P1 issue.
- Generated attachment-preview browser QA passed for text, normalized image,
  untrusted PDF handoff, archives, active files, metadata mismatch, corrupt
  bytes, delayed cancellation, and 503-to-200 retry. Exact Escape/Cancel/
  backdrop focus restoration, trapped Tab focus, command-shortcut isolation,
  and original `/download` retrieval were verified. The three-transfer cap was
  visibly enforced; risky downloads showed in-dialog progress; and runtime 415
  failures promoted downloads to confirmation.
- At 375x812 the full-screen dialog had no horizontal overflow, five controls
  measured at least 44px, the app root was inert, and the image stayed within
  12px side gutters. At 375x390 the warning body became scrollable and the
  44px `Download anyway` control remained visible. Browser console errors,
  mutation attempts, and unknown generated routes were empty.
- Independent backend, frontend, and generated-user reviewers cleared all
  attachment-preview P0/P1 findings after the admission, PDF-trust wording,
  preview/download integrity, request-identity, contrast, and short-viewport
  corrections.
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
- Compose/send still lacks a durable client-keyed lost-response contract.
  Direct keyboard sending is preserved, but irreversible Send commands are
  deliberately excluded from the executable palette until that contract and a
  generated lost-response test exist.
- Shortcut override reset/reset-all still uses a merge-only persistence API;
  a removed override can reappear after reload. Coordinate the shared
  authentication preference contract with the AI owner before correcting it.
- The new attachment lifecycle covers only the canonical ID-derived browser
  download namespace. The separately AI-owned Chat path in
  `backend/services/chat.py` still reads `Attachment.storage_path`, performs an
  unbounded Gmail download, and writes a legacy non-user-scoped filename. It
  remains outside the quota, retention, locking, and no-follow guarantees and
  must be migrated in coordination with that owner.
- Attachment quota is per user, not a global disk-cap/minimum-free-space
  policy. Canonical cache integrity is checked structurally and by recorded
  size, not by a stored content digest; both are future hardening opportunities.
- PDF preview performs basic outer-signature and obvious-feature checks, not a
  structural safety proof or malware scan. PDF bytes remain untrusted and open
  in a separate browser-native viewer. The first typed-contract request and the
  user-opened viewer request may produce two cache-backed GETs by design.
- Failed full-sync attempts can commit new mail before a later page fails; the
  mail is retained safely, but durable notification/analysis handoff remains a
  follow-up.
- The frontend build emits an existing bundle advisory over 500 kB. Route-level
  code splitting remains follow-up work.

## Next Safe Action

Preserve the reviewed, pushed product branch without rebasing it onto the
separately owned AI work. Coordinate the legacy Chat attachment migration only
after its owner releases those files; until then, keep that path explicitly out
of the canonical lifecycle claim. The next isolated product slice should avoid
shared authentication/AI files and address route-level frontend bundle
splitting, beginning with the current 1.17 MB entry chunk. Repeat all checks
before any merge or explicitly authorized deployment.
