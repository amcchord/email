# Safe Outbound Delivery and More Menu Release — 2026-08-30

## Outcome

This release replaces the web client's direct Gmail sends with durable,
idempotent, at-most-once outbound operations and adds a server-authoritative
ten-second Undo Send window. It also fixes the More dropdown so it opens below
its own trigger on Flow, Email, and Calendar.

The implementation never treats an HTTP response as proof that Gmail sent a
message. PostgreSQL owns accepted work, the provider-attempt boundary is
persisted before Gmail is called, and every ambiguous post-attempt outcome is
lookup-only: the system will not automatically send it again.

## User-Facing Changes

### Send and Undo

- Compose, message-detail replies, Reply All, and Flow replies now create one
  durable operation with one secure client UUID.
- The editor closes after the server owns the logical send, while an
  actionable Undo toast remains available until the server deadline.
- “Email sent” appears only after the server reports `sent`.
- Network-ambiguous sends show “Confirming send status — do not resend” and a
  global status bar with an explicit Check now action.
- Safe terminal failures restore the exact draft. A recovered message uses its
  own Compose intent; if another composer is active, recovery waits behind a
  Review draft action instead of interrupting or overwriting current work.
- Reloading during an unexpired staged operation restores the Undo action.
  When the browser no longer has the original in-memory callback, cancellation
  truthfully says “Send cancelled” rather than claiming a draft was restored.
- Compose and Flow Send commands are again visible in the command palette now
  that their execution is idempotent.

### Reply and Flow Integrity

- Reply payloads carry the authoritative local source email ID in addition to
  account, Gmail thread, Message-ID, and References headers.
- The server rejects a reply unless all source fields match one email in the
  same owned account. It never guesses the sender or thread.
- Flow's optional archive happens only after the reply is confirmed sent, and
  it uses the existing durable mail-action idempotency contract.
- Undo or failure recovery survives route teardown and authenticated-session
  checks; a delayed User A callback cannot change User B's UI.

### Global Status

- The authenticated shell monitors recent outbound operations independently of
  Compose, reader, or Flow component lifetimes.
- `reconciling` operations display do-not-resend guidance and a refresh action.
- `failed` operations provide truthful review guidance and can be dismissed.
  They deliberately do not expose one-click Retry: the recovered editor is the
  single place where a person can review the content and choose Send again.
- Standalone message views receive the same global status, and expanding or
  restoring a reply exits the pop-out route into normal Compose without a
  reload or loss of its in-memory draft.
- Browser-visible operation state contains no recipients, subject, message
  body, or attachment metadata.

### More Navigation

- The More button and menu now share a trigger-sized relative positioning
  wrapper. Desktop `left: 0` therefore means the More button's left edge, not
  the Flow tab's edge.
- The existing fixed mobile sheet, focus restoration, Escape behavior, and
  transparent Safari close backdrop remain unchanged.

## Durable Backend Design

The linear migration `d1e2f3a4b5c6` adds `outbound_messages` with:

- user/account/source ownership;
- user-scoped idempotency uniqueness and immutable payload hash;
- stable RFC Message-ID and optional Gmail result ID;
- staged, processing, retry, reconciliation, sent, failed, and cancelled state;
- authoritative Undo and execution deadlines;
- bounded attempts, reconciliation checks, leases, safe error fields, and
  terminal timestamps;
- partial indexes for staged work, retries/reconciliation, and expired leases.

Create locks the user/idempotency pair transactionally. Same key and same
payload returns the original operation; different content returns 409. The
account must be active and owned. Input validation bounds recipients, headers,
bodies, attachment count, decoded attachment bytes, and base64 content before
persistence.

The cron worker shares the existing per-account PostgreSQL advisory lock with
sync and mail actions. Redis can wake it after the Undo deadline, but a periodic
PostgreSQL sweep is the recovery authority. A worker:

1. claims due work under a lease;
2. searches Gmail Sent for the stable RFC Message-ID;
3. if no prior attempt exists, commits `provider_attempted_at`;
4. performs exactly one Gmail send execution;
5. records a concrete Gmail ID as sent, or enters lookup-only reconciliation
   when the result is missing, timed out, interrupted, or otherwise ambiguous.

An expired pre-attempt lease may retry safely. An expired post-attempt lease can
only reconcile. A post-attempt failure never exposes Retry. Sent and cancelled
operations remove the stored recipient/body/attachment payload.

Ingress is capped at 50 MiB before FastAPI parses a request. PostgreSQL also
enforces transactional active-operation and recent-acceptance quotas per user
and sending account, preventing a compromised authenticated session from
turning unique idempotency keys into an unbounded queue or storage flood.
Non-retryable failures scrub immediately. A rare explicitly authorized
pre-provider retry may retain content for one hour; admission and the minute
cron sweep close that window, set `can_retry=false`, and write a real SQL NULL.
SQLAlchemy parameter hiding and safe exception classification keep message
content and raw database failures out of application logs and API errors.

## Session-Only API

```text
POST /api/compose/send
GET  /api/compose/sends/recent?limit=20
GET  /api/compose/sends/by-idempotency/{idempotency_key}
GET  /api/compose/sends/{send_id}
POST /api/compose/sends/{send_id}/undo
POST /api/compose/sends/{send_id}/retry
```

All routes require the normal browser session and scope operations to its user.
They are not available to public API tokens. The exact request/response and
error contract is recorded in `docs/api.md`.

## Files Changed

### Backend and database

- `alembic/versions/d1e2f3a4b5c6_add_outbound_messages.py`
- `backend/models/outbound_message.py`
- `backend/models/__init__.py`
- `backend/database.py`
- `backend/main.py`
- `backend/middleware/compose_body_limit.py`
- `backend/schemas/email.py`
- `backend/routers/compose.py`
- `backend/services/outbound_messages.py`
- `backend/services/gmail.py`
- `backend/workers/tasks.py`
- focused backend tests for schema, API, provenance, idempotency, leases,
  at-most-once delivery, reconciliation, error redaction, and migration shape

### Frontend

- `frontend/src/lib/outboundSend.js` and focused tests
- `frontend/src/lib/outboundDraftRecovery.js` and focused tests
- `frontend/src/components/email/OutboundSendStatus.svelte` and contract tests
- outbound API client and shortcut catalog/tests
- `frontend/src/pages/Compose.svelte`
- `frontend/src/components/email/EmailView.svelte`
- `frontend/src/pages/Flow.svelte`
- `frontend/src/components/layout/Layout.svelte`
- reply envelope, Compose draft, and session-safety regressions
- `frontend/src/components/layout/TopBar.svelte` and positioning regression

### QA and documentation

- localhost-only generated outbound-send browser server and audit endpoint
- bounded application ingress and release-order runbook guidance
- `docs/api.md`
- `docs/progress/CURRENT.md`
- `docs/progress/JOURNAL.md`
- `docs/progress/DECISIONS.md` (`D-023`)
- this release record

## Verification and Production Record

- Final `make check`: 422 backend passed with 13 opt-in PostgreSQL tests
  skipped; all 208 frontend tests passed; the production build transformed 510
  modules successfully.
- Disposable PostgreSQL 17 rehearsal upgraded the entire migration chain to
  `d1e2f3a4b5c6`, passed all four outbound concurrency/race tests, downgraded to
  `c0d1e2f3a4b5` with the outbound table absent, and re-upgraded to the new head.
  The final schema exposed the expected capacity, recency, retry-expiry, due,
  lease, ownership, and failed-payload indexes/constraints.
- Focused recovery, standalone, reply-source, archive-reconciliation, session,
  and status regressions passed after independent review findings were fixed.
- Generated browser QA verified lost-response Undo and exact draft restoration,
  then kept active draft B untouched while failed send A waited behind a
  disabled Review action. Explicit review restored A exactly; discarding A and
  reopening Compose restored B exactly. Failure acknowledgment remained
  dismissed after the 15-second recent-status poll. The fail-first audit
  reported one intentional provider attempt, zero external provider calls,
  zero unexpected mutations, and zero unknown routes.
- Independent backend and UX reviews found no remaining P0 after their draft
  lifecycle findings were fixed. Commit SHAs, backup path, migration/restart
  actions, and production health remain for release closeout.

Release order is deliberately migration/API-first and frontend-last: retain the
old built frontend, back up, migrate, restart and verify `mailapp` plus
`mailworker-cron`, then build the new frontend. Once any outbound row is
accepted, rollback is roll-forward-only; never downgrade
the table away with staged, processing, retry-wait, or reconciling work.

No real email send, Undo, retry, archive, calendar write, Sync, or Todo mutation
is permitted during verification.
