# Gmail Labels & Move Release — 2026-08-30

## Outcome

Email now treats existing Gmail user labels as first-class, durable mail
actions. A user can apply or remove a label from the list, table, bulk action
bar, or reader; move an Inbox conversation to an existing label; use `L` and
`V`; see catalog-resolved color chips; and Undo an accepted operation. The same
account, conversation, idempotency, retry, and worker-recovery boundaries used
by the established mail-action outbox remain authoritative.

The release intentionally does not create, rename, or delete Gmail labels.
Those provider-catalog mutations need their own durable lifecycle. Move is
offered only in the literal Inbox view because its exact contract is “apply the
destination label and remove Inbox,” not “remove every other Gmail label.”

## User Experience

- `L` opens one searchable, account-aware label picker. An existing label is
  removed only when every selected existing conversation message already has
  it; otherwise it is applied to all of them.
- `V` and visible Move controls exist only in Inbox. Move applies the selected
  label and archives the conversation. Other mailboxes keep Label without a
  misleading Move control.
- List, table, and reader surfaces show safe catalog names and Gmail colors,
  with bounded overflow instead of raw provider IDs.
- The picker explains conversation scope, refuses mixed-account selections,
  exposes loading/empty/error/retry states, owns all keyboard events while
  open, restores focus, and becomes a usable bottom sheet on narrow screens.
- Removing the active custom mailbox label removes the affected rows and
  advances focus. Move and other row-removing actions retain the same adjacent
  row or Inbox-root focus fallback.
- Optimistic state, accepted counts, ten-second Undo, lost-response lookup,
  retry, and later-action-safe rollback use the existing durable action UX.

## Durable Contract and Safety

- Migration `b5c6d7e8f9a0` is the direct child of Universal Snooze revision
  `a4b5c6d7e8f9`. It widens the audited action-name constraint for
  `add_label`, `remove_label`, and `move_to_label`; it adds no table or retained
  message content.
- A label action requires a positive local label ID, one owned Gmail account,
  a current `label_type=user` catalog row, and fully owned explicit email
  anchors. System, stale, missing, foreign, and mixed-account targets fail
  closed before optimistic state or outbox rows are committed.
- Explicit anchors expand to every locally synchronized message in the same
  account/conversation, capped at 200. Sent or previously archived siblings
  remain eligible for a valid Inbox move; only the explicit anchors must be in
  Inbox.
- The immutable idempotency payload uses the original sorted email IDs, action,
  and local label ID. Exact replay resolves before mutable label or mailbox
  validation, so accepted lost-response recovery survives later sync or Move.
- Every outbox item persists its exact add/remove Gmail-label delta. Worker
  retry, restart recovery, conflict ordering, and Undo do not re-derive it from
  a mutable catalog row.
- Successful Gmail label-list sync is authoritative and prunes account-scoped
  rows absent upstream only after validating the complete response. Malformed,
  empty, duplicate, or failed responses delete nothing.
- Downgrade maps the three new audit names to older accepted names while
  preserving the exact stored label deltas that older workers execute.
- All generated browser identities use `.example.test`; the acceptance server
  recorded zero provider calls and zero unknown routes. Production QA did not
  apply a label, move a message, open message content, or otherwise mutate a
  real mailbox.

## Verification

- Consolidated backend suite: 623 passed, 49 intentional opt-in skips.
- Consolidated frontend suite: 354 passed.
- Focused backend label/mail-action suite: 60 passed.
- Disposable PostgreSQL label lifecycle/replay coverage: 6 passed before the
  final anchor hardening, followed by 2 exact focused PostgreSQL tests for
  Inbox anchor, non-Inbox sibling, atomic rejection, and replay behavior.
- Disposable migration `a4 → b5 → a4 → b5` and seeded-delta preservation:
  passed.
- Final frontend label, modal-key, focus, projection, API, and surface gate:
  37 passed.
- Local and production frontend builds: passed, 539 modules transformed.
- Generated self-test passed conversation expansion, apply/remove/move,
  idempotent replay/conflict, mixed-account/system-label rejection, and Undo
  with zero provider calls.
- Desktop and 390-by-844 browser acceptance passed conversation-wide chips and
  accepted count, Undo, active custom-label mailbox removal, literal-Inbox-only
  Move, modal shortcut isolation, Escape/focus recovery, mixed-account refusal,
  responsive reader rail, and mobile bottom sheet. The final browser console
  had zero warnings or errors.

## Production Evidence

- Exact application/runtime commit:
  `a440801c18c8377b50a225af71f3937caa78c7af`.
- Protected pre-migration backup:
  `/var/backups/mailapp/maildb-pre-labels-move-20260830T232001Z.dump`,
  1,383,741,356 bytes, SHA-256
  `9c5cd5876d242b78aae394c5f563beaa1e35d398f8015f24d1bb770555bd004c`.
- Production upgraded exactly `a4b5c6d7e8f9 → b5c6d7e8f9a0`, restarted only
  the API and two workers, then built the new static frontend. The retired API
  process hit the host's known graceful-stop timeout; the replacement process
  started cleanly at 23:24:08 UTC.
- Exact production Git is clean, Alembic is `b5c6d7e8f9a0 (head)`, all seven
  checked services are active, affected services report `NRestarts=0`, public
  health is `ok`, anonymous label-catalog access is 401, aggregate new label
  actions remain zero, and warning-or-higher logs after the replacement
  boundary are empty.
- Authenticated read-only production browser QA confirmed the Label and Move
  command entries from Inbox with zero browser warnings/errors. No real mail
  action was submitted.

## Rollback Boundary

Roll application code forward with a reviewed fix once production has accepted
label actions. Do not downgrade the database while any actionable mail-action
row is still staged, processing, or retrying. If an offline schema rollback is
required after all writers/drainers are stopped and actionable rows are
resolved, the migration preserves exact provider deltas while translating only
the audit action name; the validated pre-b5 backup is the final data-recovery
boundary.

## Next Product Step

The next high-value mail-client milestone is conversation-first Inbox triage:
one trustworthy conversation row, split/focused Inbox rules built on the now
durable account-scoped label primitive, and keyboard-first navigation without
duplicating message-level state.
