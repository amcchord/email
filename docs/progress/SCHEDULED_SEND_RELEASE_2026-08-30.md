# Scheduled Send Release — 2026-08-30

## Outcome

Scheduled Send is a durable, first-class mail workflow across Compose, the
message reader, and Flow. A user can choose a clear quick time or a custom
local date/time, close or reload the browser, review every pending message,
send it immediately, or cancel it back into an editable durable draft.

The implementation builds on the existing PostgreSQL outbound outbox and
durable draft session. It adds no migration and preserves the production
Alembic head at `f3a4b5c6d7e8`.

## User Experience

- A shared split Send control appears in Compose, reader replies, and Flow.
- Quick choices use explicit zoned labels instead of vague relative wording.
- A native accessible dialog supports a custom local date and time, keyboard
  operation, 44-pixel touch targets, and a narrow-screen bottom sheet.
- Nonexistent daylight-saving times are rejected. Repeated fall-back times are
  presented as two offset-specific choices.
- The global Scheduled mail bar survives reload and cross-device sign-in. It
  lists account and delivery time with **Send now** and **Cancel & edit**.
- Scheduling uses a short confirmation toast. It does not misuse an hours-long
  Undo toast or poll the server every few seconds for a far-future operation.
- Cancelling restores the exact linked draft and opens it for editing without
  accidentally retaining the old schedule on a later send.
- Flow's default **Archive after send** choice is stored inside the durable
  outbound intent. It remains effective after reload instead of depending on a
  component callback that may no longer exist when a future send completes.

## Durable Delivery Contract

- `POST /api/compose/send` accepts an optional UTC `scheduled_for` instant and
  an IANA `schedule_timezone`.
- A scheduled operation must be 60 seconds to 365 days in the future and must
  link the exact current durable draft revision.
- The existing immutable idempotency key owns the logical send. Replaying an
  accepted request returns the same operation even after its requested time.
- PostgreSQL remains authoritative. Redis receives an exact deferred wake;
  periodic cron draining remains the recovery path if that wake is lost.
- The worker does not claim a scheduled operation before its due instant.
- Cancellation takes the outbound row lock, is idempotent, scrubs the retained
  payload, and restores the linked draft. A due-time race has one winner.
- **Send now** advances the same durable operation through the existing
  Message-ID preflight, provider-attempt boundary, retry, and reconciliation
  policy; it does not create a second logical send.
- Sent operations stage the linked provider draft for prompt discard. A
  terminal pre-provider failure restores it; an ambiguous provider outcome
  preserves the existing fail-closed reconciliation behavior.
- A confirmed Flow reply stages one deterministic durable archive action before
  the outbound operation becomes terminal. Crash recovery repeats the same
  idempotency key, never a second mailbox mutation.
- Active admission remains bounded at 30 operations per account and 60 per
  user. The Scheduled mail endpoint is bounded to 60 metadata-only rows.

## API Surface

Added session-authenticated routes:

```text
GET  /api/compose/sends/scheduled?limit=60
POST /api/compose/sends/{send_id}/cancel
POST /api/compose/sends/{send_id}/send-now
```

Outbound status now includes `scheduled_for`, `schedule_timezone`,
`can_cancel`, and `can_send_now`. Responses remain metadata only and public API
tokens cannot use these mutation routes.

## Generated-Provider Safety Harness

The localhost-only generated-provider fixture now models durable drafts and
scheduled outbox operations together. It rejects every recipient outside
`.example.test`, has a controllable fake clock, counts provider lookups and
sends, and exposes only content-free audit metadata.

Its deterministic self-test proves:

- due time minus one millisecond performs no provider operation;
- cancellation before due time prevents all later provider operations;
- the exact due boundary performs one lookup and one send;
- cancellation restores the generated provider draft and its content;
- **Send now** performs exactly one lookup and one send;
- external network calls, unknown routes, and unexpected mutations remain
  zero.

## Browser Acceptance

The generated `.example.test` browser flow was exercised on desktop and at a
390-by-844 narrow viewport:

1. Create a generated durable draft.
2. Schedule it through the shared Send Later dialog.
3. Confirm the persistent manager and short confirmation.
4. Reload and confirm the operation remains visible.
5. Cancel and confirm the exact subject/body return to Compose.
6. Confirm the audit records zero provider lookups and sends, zero external
   network calls, zero unknown routes, and zero unexpected mutations.

No real mailbox, calendar, provider draft, or email send was used for this QA.

## Verification

- Focused backend unit tests: 21 passed.
- Disposable PostgreSQL scheduled-send/outbound tests: 13 passed.
- Consolidated backend suite: 563 passed with 39 intentional opt-in skips.
- Frontend unit suite: 313 passed.
- Frontend production build: passed, 529 modules transformed.
- Generated scheduled-send self-test: passed.
- Corrected desktop/narrow browser acceptance passed: the dialog exposed its
  open accessibility state, the scheduled manager survived navigation, cancel
  restored the exact generated draft, and all provider/unknown/unexpected
  counters stayed at zero.

## Production and Rollback

The exact application and documentation commits, production build result,
service health, and post-deploy log evidence are recorded after deployment in
this section and in `JOURNAL.md`.

This release has no schema or dependency change. The rollback is a reviewed
Git revert followed by rebuilding the frontend and restarting the API and both
mail worker services. Existing staged scheduled operations remain valid
outbound rows understood by the pre-release outbox, but rollback should first
inspect aggregate outbound state and cancel future operations through the
released API when practical.
