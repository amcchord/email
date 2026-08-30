# Current Status

Last updated: 2026-08-30

## Active Objective

Prepare the consolidated product-polish release for explicit user testing in
production. The release combines the independently developed product branch
with the already-deployed OpenAI/Anthropic provider baseline, preserves both
histories, fixes final review blockers, records the complete delta, and deploys
only after full local and generated-browser verification.

## Baseline

- Release worktree: `codex/product-polish-cycle-1`; its editor-deferral slice
  is committed at `2e14758` and the merge of `origin/main` is in final review.
- Repository and production baseline: clean `main` at `41d2898` at the latest
  read-only preflight observation on 2026-08-30.
- The original AI worktree remains clean at `41d2898` and is not being edited;
  its provider/model work is incorporated through Git history only.
- Production services were active and the public `/api/health` response was
  `ok` during preflight. No production change has yet been made for this
  product release.

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

## Deployment Gate

- Resolve the progress-document merge and final frontend/backend review
  findings without editing AI-owned implementation files.
- Run the complete Python and frontend suites, migration-head checks, build
  manifest/asset-closure audits, and generated browser screenshots for desktop
  and narrow screens, including slow and fail-once editor enhancement.
- Review the exact commit, dependency and migration delta, confirm rollback,
  fetch/revalidate `origin/main`, push the release branch and fast-forward
  `main` without rewriting history.
- Before the authorized migration, create and verify a protected PostgreSQL
  backup. Then update `/opt/mail` as `mailapp`, install locked frontend
  dependencies, migrate, build, and restart only the affected application and
  worker services.
- After deployment, verify the exact Git revision, Alembic head, public health,
  service state, recent error-level logs, and delivered static assets. Do not
  open or mutate real email during user testing.

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
- If rollback is required, return application code to `41d2898` while leaving
  the additive outbox schema in place unless a separately reviewed data
  downgrade is necessary.
