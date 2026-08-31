# Conversation-First Inbox Release — 2026-08-30

## Outcome

Email now presents one trustworthy row for each exact owned Gmail conversation
instead of duplicating every synchronized message. Opening the row reveals the
full chronological thread, and row, bulk, reader, and keyboard actions apply to
the same durable conversation boundary. This release is migration-free and
preserves the existing message-list/API contract for specialized surfaces and
legacy callers.

Focused/split Inbox placement is intentionally not part of this slice. It can
now be implemented as a deterministic policy over one authoritative row rather
than trying to reconcile duplicate message projections.

## User Experience

- Inbox, normal mailboxes, labels, and search show one row with conversation
  count, unread count, attachment-any state, mixed/all star state, and mixed/all
  label coverage.
- The newest matching message anchors the row. Opening it shows an oldest-to-
  newest message rail and reuses the existing sanitized reader for the selected
  exact message.
- J/K changes focused conversation without opening it, O opens the focused row,
  and Escape closes the reader and restores focus. Mouse/touch focus and open
  state remain separate.
- Conversation-wide optimistic actions expose exact accepted counts, Undo,
  durable retry/replay, adjacent focus after removal, and an authoritative
  refresh when an offset page could have shifted.
- Narrow layouts provide 44-pixel action targets and a horizontally scrollable
  message rail without widening the reader.

## Authoritative Contract and Safety

- PostgreSQL applies ownership and filters, builds a typed conversation identity,
  groups/counts, chooses an anchor, and only then paginates. `total` therefore
  means conversations, not messages on the current page.
- Gmail thread identity is always paired with the owned account. A missing or
  whitespace-only ID becomes a unique message fallback; an ambiguous legacy
  unscoped thread read fails closed instead of combining accounts.
- Aggregate unread/star/attachment/label state uses all synchronized members;
  search `matched_count` remains distinct from total membership.
- The ordinary Inbox query excludes active durable Snoozes before grouping and
  counting. Search and other mailboxes retain those rows for explicit reminder
  annotation.
- `POST /api/emails/actions` accepts additive `scope=conversations`. Exact
  anchors expand and lock all current owned conversation members, capped at 200.
  Omitting scope remains byte-compatible message behavior; scope participates in
  new idempotency hashes.
- Every browser mutation used `.example.test` generated identities. Production
  acceptance is read-only: no real message is opened, labeled, archived,
  starred, snoozed, or otherwise mutated.

## Verification

- Consolidated backend suite: 684 passed, 51 intentional opt-in skips.
- Consolidated frontend suite: 392 passed.
- Production frontend build: passed, 545 modules transformed.
- Focused backend conversation/search/action/detail gate: 104 passed.
- Focused frontend conversation/action/label/surface gate: 36 passed.
- Disposable PostgreSQL grouping, ownership, pagination, and action expansion:
  8 passed at exact Alembic head.
- Generated boundary self-test passed a seven-row conversation total, three-row
  first page, two-member expansion, idempotent replay, Undo, and zero provider
  calls.
- Desktop browser acceptance passed one two-message row, chronological message
  switching, J/K/O/Escape, generated star plus Undo, retry recovery, and focus
  restoration. The 390-by-844 reader passed its responsive rail and controls.
- Browser diagnostics contained only Vite connection debug messages. The QA
  audit recorded zero provider calls, rejected mutations, and unknown routes.
- Screenshots: `conversation-inbox-desktop.jpg` and
  `conversation-inbox-mobile.jpg` in the task visualization directory.

## Review Findings Closed

- Whitespace-only thread IDs are trimmed at every frontend expansion/read
  boundary and retain per-message fallback behavior.
- Active Snoozes moved from a capped page-local client filter into the
  authoritative Inbox query, making totals and pagination truthful.
- Row-removing actions invalidate in-flight appends, restart page ownership, and
  force an accepted/Undo reconciliation so offset shifts cannot lose a row or
  overwrite totals.
- Conversation rollback preserves a newer optimistic intent instead of letting
  an older failed request overwrite it.

## Production Evidence

- Exact application/runtime code boundary:
  `f5be5851ae7c5e628e490223c50deb0be1c9c9b2`.
- GitHub `main` and production fast-forwarded from exact terminal docs baseline
  `93b9375b04dde8687421272a987c7590a89a8d47`; production first received release-
  record commit `e4f2ac249d9d6a18c7a20fafedc7f7265db26bc1` before the final docs-only
  closeout.
- Only `mailapp` restarted. The retired process reached the host's known
  graceful-stop timeout; the replacement became active at 00:11:15 UTC with
  `NRestarts=0`. Warning-or-higher logs are empty after 00:11:16 UTC.
- Production built 545 frontend modules. All seven checked services are active,
  public health is `ok`, anonymous `GET /api/emails/conversations` is 401, Git is
  exact/clean, and Alembic remains `b5c6d7e8f9a0 (head)`.
- Authenticated read-only production QA loaded 50 visible Inbox rows and proved
  all 50 carry conversation-row semantics. No message was opened and no mail
  action was submitted. Browser warnings/errors were zero.
- No migration, database backup/restore, dependency install, worker restart,
  Caddy change, provider call, or real-mail/calendar mutation was part of the
  release.

## Rollback Boundary

The release adds no table, migration, dependency, worker payload, or provider
operation. Rollback is an application/frontend fast-forward to a reviewed
revert. Existing durable mail-action rows remain valid because message scope is
the default and worker execution still consumes the same expanded item rows.

## Next Product Step

Build focused/split Inbox placement as an explainable, keyboard-first policy
over this authoritative conversation projection. Do not reintroduce a separate
message-level source of triage truth.
