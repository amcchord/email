# Automatic Follow-up Reminders Release — 2026-08-31

## Outcome

The mail client now offers private, reply-aware automatic follow-up reminders
across Settings, Compose, reader replies, and Flow. Each connected account is
default-off. A user may save a per-account schedule, inherit it for one send,
explicitly enable a reminder, or explicitly disable it.

The reminder is admitted with the immutable outbound operation but is not
scheduled until the provider confirms delivery and the exact Sent message is
synchronized. It uses no tracking pixel, read receipt, remote image, or copied
message content.

Exact application/runtime commit:
`bf5f7bb67440f294873c0e18cdd982554343859c`.

## User experience

- Settings → Writing contains one accessible policy card per active connected
  account. New accounts appear with an explicit default-off revision-zero
  policy; no database row is created until Save changes.
- Enabled policies support a 1–30 day delay, local `HH:MM` wake time, IANA time
  zone, and weekdays-only scheduling. Saved and unsaved state, revision,
  conflict, loading, empty, and error states are visible.
- Compose, the reader reply, and Flow share the same reminder control. The
  direct bell control shows the effective state, while Send options explains
  whether the selected value comes from the account default and provides a
  one-click return to that default after an override.
- Follow-up mode and time zone round-trip through durable drafts, reload,
  cross-device recovery, scheduled send, and retry without silently changing
  the user's choice.
- The selected account determines the inherited policy. Switching accounts
  updates the effective summary but does not mutate either account policy.
- Explicit enable is rejected for self-only or Bcc-only delivery because there
  is no observable external To/Cc reply contract. A mixed owned/external To/Cc
  send remains eligible.
- Automatic reminder rows are visibly labeled Follow-up in Snoozed and in the
  selected message summary. They remain visible in ordinary and smart Inbox
  projections instead of being treated like a manual Inbox-hiding Snooze.
- The compact mobile Compose header now reserves a full status row, preventing
  draft status text from collapsing vertically when the reminder bell expands
  the action toolbar.

## Delivery and reminder lifecycle

1. Send admission resolves `default`, `enabled`, or `disabled` exactly once.
   When effective, the same PostgreSQL transaction creates a content-free
   companion intent snapshot with the selected policy values.
2. Undo, scheduled cancellation, send-now, terminal failure, live authorized
   retry, retry expiry, and reconciliation update that companion intent in the
   outbound transaction. A cancelled or permanently failed send cannot leave a
   dormant reminder behind.
3. Provider-confirmed delivery advances the intent to Sent synchronization.
   The resolver matches the owned account by provider message ID first and a
   unique RFC Message-ID second. Identifier disagreement fails closed.
4. The synchronized Sent row's timestamp—not HTTP acceptance, scheduled time,
   worker start, or provider-call start—anchors the delay.
5. Local date/time calculation handles ordinary days, weekdays-only movement,
   spring-forward gaps, and repeated fall-back times deterministically.
6. The scheduler creates one `if_no_reply` Snooze with
   `origin=automatic_follow_up`. It never archives Inbox mail and keeps no
   original Inbox placement to restore.
7. At wake, a successful account sync checkpoint must cover the wake time. A
   later inbound message in the exact account/thread dismisses the reminder;
   otherwise it returns the representative conversation to Inbox.

Manual intent remains authoritative. Creating a manual Snooze atomically
supersedes an idle automatic reminder; a newer manual placement prevents an
automatic return. One stable transaction advisory lock derived from
`(user_id, account_id, gmail_thread_id)` serializes creators, lifecycle
mutations, and the Snooze worker. Caller-owned non-committing mail-action
helpers keep that lock through the complete Snooze state transition; events
and queue acceleration occur only after the owning transaction commits.

## Persistence and API

Additive Alembic revision `e8f9a0b1c2d3` descends directly from
`d7e8f9a0b1c2` and adds:

- `account_follow_up_policies`, keyed by owned account, with revisioned complete
  replacement and database constraints for delay, local time, zone length, and
  positive revision;
- `outbound_follow_up_intents`, with one immutable outbound relationship,
  content-free policy snapshot, delivery identities, lease/recovery state,
  optional Snooze relationship, and constrained lifecycle timestamps;
- `outbound_messages.follow_up_requested`, default false for every existing
  outbound row;
- `email_snoozes.origin` and `origin_outbound_id`, defaulting existing rows to
  manual and retaining a unique automatic origin boundary.

The migration requires no backfill beyond safe server defaults. Downgrade to
d7 drops automatic policy, intent, and origin history and is intentionally
data-lossy. Once an e8 intent or policy exists, normal rollback must retain e8
and roll application code forward rather than downgrade the schema.

Session-only API documentation now covers policy list/replacement, Compose and
draft request fields, outbound response truth, delivery-confirmed scheduling,
and automatic Snooze origin. Public API tokens cannot use the policy routes.

## Recovery and privacy boundaries

- PostgreSQL is authoritative. Redis wakes the drainer sooner, while periodic
  cron recovery reclaims due work and expired leases.
- Intent claims lock the outbound first and then the companion intent, matching
  outbound mutation order and avoiding an outbound/intent deadlock.
- Snooze and ordered mail-action changes share one transaction through final
  state. A two-session PostgreSQL regression pauses after mail-action staging
  and proves a competing Snooze cannot cross that boundary.
- Idempotent outbound replay returns the original accepted operation before
  reevaluating a later policy. The accepted policy snapshot cannot drift.
- Message recipients and content are not stored in the companion intent. Error
  messages and progress records remain content-free.
- Browser and generated-provider acceptance used only `.example.test`
  identities. Production QA was read-only and saved no policy, draft, send,
  Snooze, or calendar mutation.

## Verification

- Focused iteration checks passed for policy validation, schedule calculation,
  immutable draft/send round-trip, outbound lifecycle transitions, Snooze
  ordering, and automatic-Inbox preservation.
- Disposable PostgreSQL lifecycle: 9 passed, including default-off/opt-in,
  explicit recipient eligibility, provider/RFC conflict, delivery timestamp
  anchoring, manual supersession, scheduled-send transitions, retry expiry,
  advisory serialization, and the nested mail-action staging boundary.
- Exact disposable migration round trip passed:
  `d7e8f9a0b1c2 → e8f9a0b1c2d3 → d7e8f9a0b1c2 → e8f9a0b1c2d3`.
- Generated-provider self-test passed revisioned policy save/replay/conflict,
  exact durable draft reopen, requested-send admission, Undo, content-free
  audit, zero external calls, and zero unexpected mutations.
- Generated browser acceptance passed default-off Settings, revisioned policy
  save, Compose/account-default explanation, generated recipient/content draft,
  desktop and 390×844 Send options, mobile header containment, and zero browser
  warnings/errors. Screenshots are stored outside the repository at:
  `automatic-follow-up-reminders/settings-default-off.png`,
  `automatic-follow-up-reminders/settings-saved-policy.png`,
  `automatic-follow-up-reminders/compose-send-options.png`, and
  `automatic-follow-up-reminders/compose-mobile-send-options.png`.
- Independent lifecycle review found and drove fixes for Snooze lock ordering,
  outbound companion transitions, explicit recipient eligibility, Inbox smart
  views, and nested mail-action commits. Its final verdict was SHIP with no
  remaining P0/P1.
- One consolidated final `make check` passed 746 backend tests with 75 expected
  skips, all 482 frontend tests, and a 604-module production build.

## Production result

- GitHub `main` and production fast-forwarded from exact prior closeout
  `020d78548c283f67d128d4cd37ce71fc8a162c5b` to application/runtime
  `bf5f7bb67440f294873c0e18cdd982554343859c`.
- The validated protected pre-e8 backup is
  `/var/backups/mailapp/maildb-pre-follow-up-20260831T0522Z.dump`,
  1,383,711,616 bytes, mode `0600`, owner `postgres:postgres`, SHA-256
  `96464d3027b865ba76be4c356cb0fa24d09eaa1fd2eee6527c8f691b303a08ba`.
- Production upgraded exactly `d7e8f9a0b1c2 → e8f9a0b1c2d3 (head)` before
  publishing the new frontend. `mailapp`, `mailworker`, and `mailworker-cron`
  were replaced; the retired API hit the host's known graceful-stop timeout,
  and all three reviewed replacements became active at 05:25:06 UTC with
  `NRestarts=0`.
- Production installed the unchanged locked frontend dependency tree with zero
  audit findings and built the same 604 modules.
- All seven checked services are active, public health is `ok`, production Git
  is exact and clean, anonymous policy access is 401, and no warning-or-higher
  entry exists after the replacement boundary.
- Aggregate counts for saved account policies, outbound follow-up intents, and
  automatic follow-up Snoozes are all zero immediately after release.
- Signed-in read-only production browser QA loaded Settings → Writing with four
  account policy controls, four disabled Save buttons, and zero browser
  warnings/errors. It did not reveal account addresses in release evidence and
  performed no mutation.

## Rollback

Before the first saved policy or admitted intent, application Git and frontend
may be rolled forward with a reviewed revert while retaining e8. After durable
e8 work exists, do not downgrade the schema as an application rollback: doing
so destroys reminder recovery and policy truth. Stop API and both worker
writers, inspect aggregate state, and require explicit data-loss approval
before any downgrade or backup restoration.
