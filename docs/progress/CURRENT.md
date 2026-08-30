# Current Status

Last updated: 2026-08-30

## Active Objective

Pause implementation while the consolidated product-polish release receives
explicit user testing in production. Preserve the verified release and its
rollback evidence; use generated messages for any mutation testing and do not
open or change real mail merely to exercise the UI.

## Baseline

- Application release: `834eade`, pushed to
  `origin/codex/product-polish-cycle-1` and `origin/main`, then deployed by
  clean fast-forward from `41d2898`.
- Production runs application release `834eade`; a docs-only closeout commit
  follows it with no runtime delta. Alembic is at `z7a8b9c0d1e2 (head)`, all
  seven checked services are active, and public `/api/health` returns `ok`.
- The original AI worktree remains clean at `41d2898` and is not being edited;
  its provider/model work is incorporated through Git history only.
- A validated 1.38 GB custom-format backup is protected at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`, mode
  `0600`, owned by `postgres`.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Release Candidate Scope

- Lossless, account-serialized Gmail synchronization checkpoints.
- Durable, ordered mail-action outbox with idempotent reconciliation, exact
  staged Undo, retries, lease recovery, and visible partial failure.
- Authenticated attachment download, bounded canonical cache lifecycle, and
  byte-classified text/image/untrusted-PDF preview behavior.
- Truthful executable command palette, complete shortcut discovery, and
  composable structured search inside an immutable account-ownership boundary.
- Route-level feature splitting, stale-safe loading/error recovery, browser
  history integration, and preserved cross-screen intent.
- Deferred Tiptap loading behind immediate writing intent, draft-safe basic
  editing, accessible writing controls, and stale reply/thread protections.
- OpenAI GPT-5.6 and Anthropic Claude 5 provider/model selection from the
  already-deployed `origin/main` baseline.
- Generated localhost-only QA harnesses that reject every mutation and use
  `.example.test` mail fixtures.

## Deployment Result

- `make check` passed with 303 backend tests, 4 opt-in PostgreSQL skips, 108
  frontend tests, and a successful production build.
- Generated in-app browser QA passed desktop, slow, fail-once, and exact 375px
  editor scenarios with empty mutation and unknown-route audits.
- Production used the exact reviewed commit, a validated pre-migration backup,
  transactional Alembic upgrade, locked frontend install/build, and scoped
  restarts of `mailapp`, `mailworker`, and `mailworker-cron` only.
- Post-deploy verification confirmed exact local/origin Git state, schema head,
  zero error-level application/worker log lines, zero service restarts, health
  `ok`, and HTTP 200 for eager, deferred-editor, and rich-editor assets.

## Known Constraints and Follow-ups

- Compose/send still lacks a durable client-keyed lost-response contract, so
  irreversible Send remains outside the command palette.
- Opening unread production mail marks it read. All mutation and rendered-flow
  QA for this release uses generated local fixtures; production verification
  is limited to health, services, schema, assets, and non-mailbox shell paths.
- The attachment lifecycle covers the canonical browser namespace; the legacy
  Chat attachment path remains a separately scoped migration.
- PDF preview is a bounded, untrusted browser-native handoff, not malware
  scanning or a structural safety proof.
- Shortcut override reset semantics and account-scoped saved views remain
  future work after the shared preference contract is deliberately extended.
- The unchanged frontend lockfile has 11 npm production advisories (4 moderate,
  6 high, 1 critical). Compatible fixes are available for DOMPurify, jsPDF,
  Svelte, Vite, and transitive packages; handle them as the next isolated
  dependency-update cycle with a full generated-browser regression pass.
- If rollback is required, return application code to `41d2898` while leaving
  the additive outbox schema in place unless a separately reviewed data
  downgrade is necessary.
