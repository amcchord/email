# Focused/Split Inbox Release — 2026-08-30

## Outcome

Inbox can now present one exact owned-account conversation in either Focused or
Other with truthful section totals, a visible stable reason, and keyboard-first
navigation. This replaces the old message-level “hide ignored” behavior. It is
a read projection only: no mail is moved in Gmail, no background classifier is
invoked, and no database migration is required.

## User experience

- The stateful `Split` control is available only in the literal, unfiltered
  Inbox. Its label, pressed state, disabled explanation, and help text make clear
  that it changes presentation without moving Gmail mail.
- Focused and Other are labelled sections in both list and table layouts with
  exact totals, concise explanations, visible reason chips, and truthful
  loading/empty states. Other is visible by default rather than becoming a
  hidden catch-all.
- J/K traverses the combined visual order, Shift+J/K jumps to the next/previous
  nonempty section, O opens, and Escape returns to the same conversation.
- Row-removing generated actions update the affected section immediately. Undo
  restores the conversation, exact totals, logical selection, and DOM focus.
- Split preference persists across reload. Search, labels, smart filters, and
  other mailboxes retain their ordinary authoritative conversation dataset.
- The 390-by-844 layout preserves both section headers and reason text without
  horizontal overflow; table mode exposes two labelled level-two heading rows
  without misusing table row-group header semantics.

## Authoritative placement contract

Placement occurs after `match_rank=1` selects the newest mailbox-matching row
for exact `(account_id, conversation_identity)`, then before count and
pagination. Focused and Other therefore cannot choose different anchors for the
same conversation.

The stable precedence is:

1. high priority or urgent → Focused / `high_priority`;
2. nonignored needs-reply with no later sent reply in the same account/thread →
   Focused / `needs_reply`;
3. trusted sender → Focused / `trusted_contact`;
4. routine scheduling already delegated to Andrea → Other /
   `delegated_scheduling`;
5. subscription → Other / `subscription`;
6. can-ignore → Other / `low_priority`;
7. missing analysis → Focused / `unclassified`; and
8. everything else → Focused / `direct_or_fyi`.

The primary API is one coherent `/api/emails/conversations/split` response.
One PostgreSQL statement ranks, pages, and counts both sections, preventing a
classifier update between two browser requests from omitting or duplicating a
conversation. Owned-account narrowing remains supported. Each response row
carries `inbox_placement` and `inbox_placement_reason`; the client validates
placement, rejects total drift, globally replaces a conversation that is
reclassified between appended pages, and computes only from exact server
totals. The section-specific `inbox_placement=focused|other` compatibility form
is restricted to the literal Inbox with no search, label, state, category,
needs-reply, or legacy exclusion filter.

## Safety and compatibility

- Placement uses persisted local signals only. It does not call, prompt,
  backfill, or modify the independently running AI pipeline.
- Unknown analysis fails visibly into Focused, so classifier lag cannot hide a
  new conversation.
- Later-reply correlation includes account ID and Gmail thread ID. Blank thread
  IDs retain their typed one-message identity and cross-account thread IDs
  never merge.
- Existing active-Snooze exclusion remains upstream of grouping. Conversation
  actions, labels, Move, Snooze, retry/replay, and Undo keep the exact durable
  account/conversation boundary.
- Omitting `inbox_placement` is backward compatible. No schema, dependency,
  worker payload, provider operation, or terminal control changed.

## Verification

- Backend suite: 696 passed, 56 expected opt-in skips.
- Frontend suite: 404 passed.
- Production frontend build: passed, 546 modules transformed.
- Focused backend placement/API tests: 43 passed.
- Fresh disposable PostgreSQL at exact Alembic `c6d7e8f9a0b1`: 2 passed,
  covering authoritative newest-anchor placement, trusted/delegated/
  subscription/unclassified precedence, sent-reply suppression, exact totals,
  disjoint union, and exact retained totals for an empty page beyond both
  section ranges.
- Generated boundary self-test: seven conversations, 4 Focused, 3 Other, exact
  union/disjointness, generated Undo, and zero provider calls.
- Generated desktop list/table and 390-by-844 browser acceptance passed exact
  headers/counts, reason chips, J/K, Shift+J/K, O/Escape, table section headings,
  reload persistence, archive/Undo, focus restoration, and responsive overflow.
- Browser diagnostics recorded zero warning/error entries, provider calls,
  rejected mutations, or unknown routes. Every generated identity used the
  reserved `.example.test` domain.
- Independent code/user review closed the two-request classifier race, stale
  delegated needs-reply contradiction, reclassification duplicate, same-section
  removal/Undo focus loss, out-of-range total drift, and table-header semantics;
  the final review reported no remaining actionable P0–P2 findings.
- Local screenshots: `focused-split-inbox-desktop.png` and
  `focused-split-inbox-mobile.png` in the task visualization directory.

## Exact source and production evidence

- Base terminal OTA docs closeout:
  `81a277e22cc0fcf5439735beaa74a775622de27a`.
- Focused/Split implementation commit: `e85ffa0` after the exact-base rebase.
- Generated/PostgreSQL evidence commit: `0e19fcd`.
- Final reviewed application/runtime and initial GitHub/production release:
  `dea8117f5b5348d8c4d3f78e0e6af08273a6367d`.
- Production built 546 frontend modules. The replacement API is PID 2132116,
  has zero automatic restarts, and has no warning-or-higher entries after its
  2026-08-31 01:03:15 UTC start boundary. The retired process exhausted its
  graceful-drain timeout at the replacement boundary; the replacement started
  cleanly, all seven checked services are active, and public health is `ok`.
- Anonymous access to `/api/emails/conversations/split` is 401. Authenticated
  read-only production QA showed both first-class sections, exact nonzero
  totals, 25 visible rows and reason chips in each section, and zero browser
  warning/error entries. It did not open, move, archive, label, snooze, or
  otherwise mutate real mail.
- Production remains at Alembic `c6d7e8f9a0b1`; this release is migration-free.

## Rollback boundary

The release adds no schema, dependency, worker contract, or provider mutation.
Rollback is an application/frontend fast-forward to a reviewed revert. The
ordinary conversation endpoint remains compatible when placement is omitted,
and existing durable mail-action/Snooze rows keep their current meaning.
