# Universal Snooze Release — 2026-08-30

## Outcome

Universal Snooze is a durable, conversation-level workflow across Inbox, the
reader, Flow, search, mailbox views, keyboard commands, and a first-class
**Snoozed** destination. A reminder can return at a specific zoned time or only
when nobody has replied. It survives browser reloads, process restarts, a lost
Redis wake, and provider retry without inventing a second logical reminder.

Exact Snooze application/runtime commit:
`231173b2d18966b603ed2f824f68380f8087de2c`.

The migration-free terminal candidate.5 integration was then deployed with
Snooze as combined runtime
`35e3700e8a22eabf49e701fb873d4662d5b7abdc`. The Snooze schema head is
`a4b5c6d7e8f9`, a direct child of terminal head `f3a4b5c6d7e8`.

## User Experience

- **Snoozed** is a first-class mailbox in the Email sidebar. The former AI
  smart view is retained under the distinct name **Paused replies**.
- Inbox rows, reader actions, Flow, the command palette, and the `H` shortcut
  use one accessible Snooze picker.
- Quick choices provide Later today, Tomorrow morning, and Next week with
  explicit local time and zone. Custom times reject daylight-saving gaps and
  distinguish both offsets in a fall-back fold.
- The reminder may return unconditionally or only if no later inbound reply
  exists in the exact account and Gmail conversation.
- Snoozing removes every visible sibling in the conversation from Inbox and
  smart views in one projection. Search, Starred, Sent, All Mail, and custom
  label views retain and annotate matching rows instead of flickering them out.
- Confirmation exposes ten-second **Undo**. Undo and later **Cancel reminder**
  restore the original mailbox placement; scheduled wake and explicit
  **Return now** add Inbox, including for reminders created from Sent/All Mail.
- Lost create or lifecycle responses reconcile the exact owned operation
  before the UI rolls back. An unresolved result remains visibly pending and
  cannot create a second logical reminder.
- Row focus advances predictably after conversation removal and returns to the
  restored conversation after Undo. Dialog focus, Escape, error announcements,
  touch targets, empty/loading/error states, and narrow-screen layout are
  explicit.

## Durable Conversation Contract

- A Snooze is uniquely active by `(user, account, gmail_thread_id)`, not by one
  local message row. Current eligible Inbox members archive together through
  one deterministic bulk mail-action operation.
- PostgreSQL owns reminder time, condition, conversation membership, original
  Inbox membership, per-message mail-action baselines, leases, attempts, and
  terminal state. Redis only accelerates draining; the minutely cron sweep is
  the downtime recovery path.
- Create is client-keyed and idempotent. A replay resolves before future-time
  validation, so a lost accepted response can still be recovered after wake.
- Due-time Return stages the ordered `unarchive` operation in the same database
  transaction that locks every current conversation row. A later manual
  placement therefore receives a higher sequence and wins.
- Trash, Spam, and members with a newer manual placement are filtered
  individually. One protected sibling cannot resurrect or block unrelated
  safe members.
- `if_no_reply` waits for a successful account sync checkpoint at or after the
  wake instant before concluding that nobody replied. Stale local mail cannot
  cause a premature return.
- Partial bulk state is evaluated as one reminder lifecycle. Retryable provider
  failures follow the existing durable mail-action retry policy; a terminal
  failure releases the active-conversation uniqueness guard instead of looping
  forever.
- Snooze state publishes `snooze_updated` through the existing authenticated
  event stream so Inbox and Flow refresh without making Redis authoritative.

## Session API

Authenticated browser-session routes:

```text
POST  /api/snoozes
GET   /api/snoozes?state=active&limit=50&offset=0
GET   /api/snoozes/by-idempotency/{idempotency_key}
GET   /api/snoozes/{snooze_id}
PATCH /api/snoozes/{snooze_id}/reschedule
POST  /api/snoozes/{snooze_id}/cancel
POST  /api/snoozes/{snooze_id}/return-now
```

Ownership follows the authenticated user through the exact Google account and
email. Public API tokens cannot call these routes. Foreign, missing, protected,
or conflicting targets fail without exposing another account's existence.

## Migration and Rollback

Migration `a4b5c6d7e8f9` creates the owner-scoped `email_snoozes` lifecycle
table, partial active-conversation uniqueness, due/lease indexes, action links,
and JSON shape constraints. It also extends the existing mail-action constraint
with `unarchive`; no mailbox row, label, reminder, or provider operation is
created by the migration itself.

Upgrade is additive except for replacing the action check constraint inside the
same PostgreSQL transaction. Downgrade drops all Snooze lifecycle/history rows.
Accepted `unarchive` mail-action history is compatibility-mapped to the older
runtime's `unspam` action name before restoring its old constraint; execution
still follows each row's persisted add/remove-label delta. Never downgrade
while actionable Snooze or mail-action rows exist. Prefer a reviewed forward
fix after production has accepted reminders.

## Generated-Mail Safety Harness

The localhost-only `.example.test` fixture models conversation siblings,
idempotency, fake time, reply conditions, protected mailboxes, Cancel,
Return-now, reschedule, and exact-boundary wake. It exposes aggregate audit
counters and cannot call a provider.

Its deterministic self-test proves:

- the conversation remains hidden one millisecond before wake and returns at
  the exact instant;
- every current Inbox sibling hides and returns together, and a second active
  reminder for a sibling conflicts;
- replay uses the same logical reminder;
- `if_no_reply` and Trash/Spam do not resurrect mail;
- Cancel preserves a Sent-only conversation outside Inbox while Return now
  brings the same conversation into Inbox;
- provider calls and unknown routes remain zero.

## Verification

- Focused backend/mail-action tests: 53 passed.
- Disposable PostgreSQL conversation, race, placement, partial-failure, and
  fresh-sync tests: 8 passed.
- Disposable migration roundtrip `f3 → a4 → f3 → a4`: passed.
- Consolidated backend suite: 603 passed with 47 intentional opt-in skips.
- Consolidated frontend suite: 335 passed.
- Final Snooze-focused frontend gate: 22 passed.
- Frontend production build: passed, 534 modules transformed.
- Generated Snooze self-test: passed with zero provider calls and unknown
  routes.
- Desktop and 390-by-844 browser QA passed conversation hide/Undo, first-class
  Snoozed management, reschedule, Return now, `H`, focus, dialog, and console
  checks. No real mailbox or calendar data was used.

## Production Evidence

- The validated pre-migration backup is
  `/var/backups/mailapp/maildb-pre-universal-snooze-20260830T2224Z.dump`,
  1,383,720,058 bytes, SHA-256
  `049ad0aae0b0cb3ee4cc3b2e34585cd5fe248b1654fbd2127d42a195b2a9ec16`.
- Production fast-forwarded from clean `4f85578` to combined runtime
  `35e3700e8a22eabf49e701fb873d4662d5b7abdc`, then upgraded exactly
  `f3a4b5c6d7e8 → a4b5c6d7e8f9`.
- All seven checked services are active, public health is `ok`, recent affected
  services have no post-start warning-or-higher entries, anonymous Snooze
  access returns 401, and the aggregate Snooze row count is zero.
- Production QA remained read-only. No Snooze was created against a real
  mailbox, and no Gmail, calendar, terminal, firmware, or enrollment mutation
  was used as release evidence.

## Remaining Product Work

Universal Snooze now covers the core modern-client reminder workflow. Useful
follow-ons are policy-based automatic reminders, reusable scheduling defaults,
and richer conversation grouping in the list itself. They should reuse this
one durable lifecycle rather than creating AI-only or client-only timers.
