# Current Status

Last updated: 2026-08-30

## Active Objective

User-test the newly deployed durable Send and Undo lifecycle, then continue the
next high-value mail-client cycle with generated fixtures and read-only
production verification.

## Baseline

- GitHub `main` and production runtime are clean at
  `2a8dbecba7d590198cfe005062700d5e68624851`. It contains the previously
  released More anchor fix plus durable, idempotent outbound delivery and a
  server-authoritative ten-second Undo window.
- Production Alembic is `d1e2f3a4b5c6 (head)`. The validated pre-migration
  backup is `/var/backups/mailapp/maildb-pre-outbound-20260830T1718Z.dump`.
- `mailapp`, both workers, mail TUI, Caddy, PostgreSQL, and Redis are active;
  public health is `ok`; unauthenticated requests to the new send/status routes
  return `401`; and the 510-module `index-BU6KBgki.js` frontend is live.
- Signed-in read-only production browser QA loaded blank Compose with all
  expected controls and zero console errors. More matched its trigger's left
  edge exactly with an 8 px vertical gap. No real Sync, send, mail action,
  calendar write, or Todo action ran.
- The firmware repository milestone is independently merged at
  `1b5364e5d4b48666b3ecfd0cf8ba31ab7f4bd5c4`. Its Email browser-installer
  task is avoiding this release's shared API and progress documents.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Item

### P1 — Production user testing and next-cycle selection

- State: live; awaiting deliberate user testing
- Scope: verify a real Send, Undo within ten seconds, reload-time Undo, and
  truthful delivery/recovery status from the user's production session. Do not
  simulate these against real accounts through automation.
- Next: record user-testing findings, fix any release regression immediately,
  then select the next item from the product queue.

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
