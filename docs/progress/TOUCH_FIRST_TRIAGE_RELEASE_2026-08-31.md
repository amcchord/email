# Touch-first Inbox Triage Release — 2026-08-31

## Outcome

Inbox now supports deliberate touch swipes and one coherent multi-selection
workflow across list and table views. The release is migration-free and reuses
the existing account-safe durable mail-action, Snooze, and Undo contracts.

## User experience

- Swipe left defaults to Archive; swipe right defaults to Snooze.
- Settings are cross-device and may instead use Toggle read, Toggle star, or
  No action in either direction.
- The mobile Inbox explains the active pair and exposes a visible Customize
  action. Every row also retains a 44-pixel non-gesture Actions target.
- Checkboxes, long press, `X`, Shift-range selection, Select loaded, and Clear
  share one session-local selection model across list/table rendering and
  same-dataset refreshes.
- A sticky accessible bulk bar exposes Archive, read/unread, star, Label, Move,
  Spam/Not spam, Trash/Restore as appropriate without replacing the existing
  protected-mailbox recovery paths.

## Safety contract

- Swipes run only for a primary touch/coarse pointer on current ordinary Inbox
  rows. Mouse drags, protected mailboxes, stale sessions/datasets, failed
  preference hydration, action-disabled rows, interactive descendants,
  multi-touch, cancellation, short drags, and vertical intent fail closed.
- Trash, Spam, and Move are not swipe choices.
- Archive, read, and star use the existing idempotent durable action and exact
  Undo path. Snooze opens the existing picker and writes nothing until an
  explicit return time is chosen.
- Selection is never stored in the browser or server. Account, mailbox, and
  session changes clear it; authoritative refreshes prune vanished rows.

## Verification

- The single consolidated post-freeze gate passed 841 backend tests with 75
  expected skips, all 554 frontend tests, and the 634-module production build.
- Focused gesture/selection tests passed 16 cases covering touch-only
  activation, vertical priority, short/cancelled/multi-touch/interactive
  zero-write paths, stale generations, once-only commit, range selection,
  dataset/session clearing, and authoritative pruning.
- The loopback-only two-account `.example.test` fixture self-test passed lost
  response reconciliation, exactly-once Archive plus Undo, explicit-time-only
  Snooze, protected-mailbox/session/dataset rejection, and zero provider,
  Gmail, send, Calendar, AI, worker, terminal, or external-network operations.
- In-app browser QA at desktop and 390×844 verified defaults, cancel, one exact
  generated preference save, list/table range selection, sticky bulk actions,
  mobile fallbacks, and the zero-write Snooze picker. Browser logs were empty;
  its final audit recorded zero mail-action and Snooze writes and zero external
  capabilities. Screenshots are stored outside the repository under
  `/Users/austinmcchord/Development/Email-release-evidence/touch-first-triage-2026-08-31/`.
- Signed-in production QA was strictly read-only: it loaded authoritative rows
  on desktop and the same row/action hooks at 390×844 with zero selection,
  bulk action, message open, gesture, or preference mutation.

## Release

- Application/runtime commit: `c7b9960653f48c0a7ab47f79a295d6fedd19695a`
- Production Alembic: unchanged at `c1d2e3f4a5b6 (head)`
- Production frontend: 634 modules
- Production replacement API: PID 2188272, zero restarts, active from
  2026-08-31 20:41:38 UTC, with no warning-or-higher log entries after the
  replacement boundary
- All seven checked services and public health are healthy. The prior API
  process exceeded its graceful-stop window and systemd terminated only that
  draining process before the replacement became active.

No real message, calendar, account, terminal, or provider state was changed by
QA. The only browser-side write was one preference update inside the generated
`.example.test` fixture.
