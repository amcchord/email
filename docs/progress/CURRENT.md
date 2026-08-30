# Current Status

Last updated: 2026-08-30

## Active Objective

Replace every interactive web send path with one durable, idempotent,
ten-second Undo Send lifecycle. Prove at-most-once Gmail behavior, reply-source
ownership, draft recovery, session isolation, and truthful status using only
generated `.example.test` fixtures before promoting the migration and worker.

## Baseline

- GitHub `main` and production are clean at
  `9d0d4754a3c1ba3817f1c20244810231b4f8894d`. That small released fix anchors
  the More dropdown to the More trigger rather than the full navigation row.
- Signed-in read-only production browser QA measured a 0 px left-edge delta
  and 8 px vertical gap on both Flow and Calendar. All seven checked services
  are active, public health is `ok`, and the new 507-module frontend asset is
  live. No real Sync, send, mail action, calendar write, or Todo action ran.
- Production Alembic remains `c0d1e2f3a4b5 (head)`. The outbound candidate
  allocates the next linear revision `d1e2f3a4b5c6`; it is not deployed yet.
- The firmware repository milestone is independently merged at
  `1b5364e5d4b48666b3ecfd0cf8ba31ab7f4bd5c4`. Its Email browser-installer
  task is avoiding this release's shared API and progress documents.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Item

### P0 — Durable outbound delivery and Undo Send

- State: release-ready
- Why: the legacy request sent directly through Gmail, so a lost HTTP response
  could cause a user retry and duplicate real email; it also reported “sent”
  before provider truth and had no Undo Send.
- Scope: PostgreSQL outbound outbox, reply provenance, stable RFC Message-ID,
  one-attempt Gmail delivery plus lookup-only reconciliation, cron recovery,
  session-owned API routes, global status, Compose/reader/Flow integration,
  generated browser QA, API/release/progress documentation.
- Acceptance: one client UUID maps to one immutable payload; ambiguous provider
  outcomes are never replayed; Undo works only in the authoritative ten-second
  window; sent/cancelled payloads are scrubbed; failures restore a distinct
  draft without overwriting a newer composer; cross-user callbacks are inert;
  full checks, disposable PostgreSQL rehearsal, and generated browser tests
  pass before deployment.
- Next: commit and push the exact reviewed candidate, back up, migrate while
  the old frontend remains live, restart and verify the API plus cron worker,
  publish the new frontend, and verify production without sending real email.

## Near-Term Product Queue

- Durable Gmail draft identity/upsert and attachment continuity; repeated Save
  Draft currently creates separate provider drafts.
- Conversation-native inbox with compound account/thread identity and cursor
  pagination.
- General Remind Me/send later, label/move actions, recipient/contact
  completion, and bulk triage across all filtered results.
- Flow loading/stale-response truthfulness and mobile Sidebar drawer height,
  labels, inertness, and 44 px target corrections.
- Async shortcut rejection handling and broader generated user testing.

## Safety Constraints

- Real production mail and calendars remain read-only during automated and
  browser QA. Sending, Undo, retry, archive-after-send, and failure simulations
  use only local `.example.test` fixtures and fake Gmail transports.
- Do not modify the concurrent AI provider/model work or the terminal-specific
  browser-installer files. Coordinate shared docs and release SHA before that
  task rebases.
