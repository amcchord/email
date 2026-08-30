# Current Status

Last updated: 2026-08-30

## Active Objective

Ship the isolated, locally verified frontend security refresh to production for
user testing. Preserve the clean AI-provider worktree, use generated messages
for rendered-content/browser QA, and do not open or change real production mail.

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
- The frontend security candidate is isolated on
  `codex/frontend-dependency-security`. Its compatible lock refresh clears all
  11 production advisories, and its DOMPurify/jsPDF/Svelte/editor/browser gates
  pass locally and in clean Linux x86_64 Node 20.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Frontend Security Candidate Scope

- Compatible npm lock refresh from 11 production advisories to zero.
- Explicit display-only sanitizer policy for email HTML and AI Markdown.
- Single configured Tiptap Link/Underline extensions after the StarterKit
  update.
- Mobile Chat overlay sidebar, 44 px menu/download controls, and wrapping
  download actions.
- Exception-safe, section-aware multi-page Chat PDF generation.
- Generated hostile email/Markdown and multi-page PDF browser fixtures with
  dedicated read/mutation/unknown-route auditing.

## Verification Result

- `make check` passed with 303 backend tests, 4 opt-in PostgreSQL skips, 108
  frontend tests, and a successful production build.
- Clean Linux x86_64 Node 20 passed locked install, zero-vulnerability audit,
  all frontend tests, and the manifest build.
- Generated in-app browser QA passed hostile email/Markdown rendering, rich
  editor mount, desktop and exact 375 px Chat/email layouts, and multi-page PDF
  export. Mutation and unknown-route audits are empty.
- The four-page generated PDF was byte-checked and Poppler-rendered page by
  page; final pagination has no clipped or split content.
- Production deployment is the next action. No schema change, backup, service
  restart, real-mail read, or mailbox mutation is required.

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
