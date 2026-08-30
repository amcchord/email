# Current Status

Last updated: 2026-08-30

## Active Objective

Pause the deployed frontend security refresh for explicit production user
testing. Preserve the clean AI-provider worktree, keep rendered-content/browser
QA on generated messages, and do not open or change real production mail.

## Baseline

- Production and GitHub `main` run frontend security release `3f9e743`, built
  from a clean fast-forward over application release `834eade` and docs
  baseline `413d763`. Alembic remains at `z7a8b9c0d1e2 (head)`, all seven
  checked services are active with zero restarts, and public `/api/health`
  returns `ok`.
- The original AI worktree remains clean at `41d2898` and is not being edited;
  its provider/model work is incorporated through Git history only.
- A validated 1.38 GB custom-format backup is protected at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`, mode
  `0600`, owned by `postgres`.
- The frontend security release is also preserved on
  `origin/codex/frontend-dependency-security`. Its compatible lock refresh
  clears all 11 production advisories, and its DOMPurify/jsPDF/Svelte/editor/
  browser gates pass locally, in clean Linux x86_64 Node 20, and in the locked
  production build.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Frontend Security Release Scope

- Compatible npm lock refresh from 11 production advisories to zero.
- Explicit display-only sanitizer policy for email HTML and AI Markdown.
- Single configured Tiptap Link/Underline extensions after the StarterKit
  update.
- Mobile Chat overlay sidebar, 44 px menu/download controls, and wrapping
  download actions.
- Exception-safe, section-aware multi-page Chat PDF generation.
- Generated hostile email/Markdown and multi-page PDF browser fixtures with
  dedicated read/mutation/unknown-route auditing.

## Deployment Result

- `make check` passed with 303 backend tests, 4 opt-in PostgreSQL skips, 108
  frontend tests, and a successful production build.
- Clean Linux x86_64 Node 20 passed locked install, zero-vulnerability audit,
  all frontend tests, and the manifest build.
- Generated in-app browser QA passed hostile email/Markdown rendering, rich
  editor mount, desktop and exact 375 px Chat/email layouts, and multi-page PDF
  export. Mutation and unknown-route audits are empty.
- The four-page generated PDF was byte-checked and Poppler-rendered page by
  page; final pagination has no clipped or split content.
- Production fast-forwarded cleanly from `413d763` to exact `3f9e743`, then
  passed locked install, zero-vulnerability audit, and the 500-module build.
- Post-deploy checks found clean Git state, health `ok`, all seven services
  active with zero restarts, zero recent error-level log lines, and HTTP 200 for
  the eager, Chat, sanitizer, rich-editor, and jsPDF assets. No schema change,
  backup, service restart, real-mail read, or mailbox mutation occurred.

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
- Email compatibility still permits remote images, stylesheet links, and
  inline style. A separate remote-content/tracking policy remains necessary.
- Chat PDF is a polished raster export, not selectable/accessible document
  text; semantic PDF output remains a future enhancement.
- If rollback is required, return application code to `41d2898` while leaving
  the additive outbox schema in place unless a separately reviewed data
  downgrade is necessary.
- For this frontend-only candidate specifically, return to `413d763` and
  rebuild the locked frontend; no database rollback is involved.
