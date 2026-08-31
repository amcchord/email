# First-class Per-account Signatures Release — 2026-08-31

## Outcome

The mail client now has first-class, default-off signatures for every connected
Google account. A user can edit rich content in **Settings → Writing**, enable
it independently for new messages, replies, and forwards, and Remove or Restore
the exact frozen signature on an individual message from Compose, the reader,
or Flow.

Signatures are not copied into editable authored text. The system keeps the
authored body, a versioned signature sidecar, and quoted history separate, then
builds the provider body exactly once as body → signature → quote. That makes
reloads, retries, scheduled delivery, forwarding, settings edits, and draft
recovery deterministic and duplicate-free.

## Everything that changed

### Data and ownership

- Added additive Alembic revision `f9a0b1c2d3e4`, directly descending from
  production head `e8f9a0b1c2d3`.
- Added one `account_signatures` row per exact `google_accounts.id`, with
  cascading deletion, revision and sanitizer versions, independent inclusion
  flags, bounded rich/plain content, and database-level coherence checks.
- An absent row is a safe disabled revision-zero default. There is no backfill,
  and production started with zero rows.
- Missing, inactive, and foreign account identifiers share one non-disclosing
  response. All service paths resolve the account through the signed-in owner.

### Policy API and sanitization

- Added session-only `GET /api/compose/signatures` and revision-safe
  `PUT /api/compose/signatures/{account_id}`.
- Exact replacement replay succeeds; stale revisions return a visible 409
  conflict. Reads are no-store and never create a row.
- Pinned `nh3==0.3.7` in both requirements manifests. The server removes active
  content, event handlers, inline styles, remote resources, and unsafe URL
  schemes, derives a coherent plain fallback, and versions the sanitizer.
- An enabled signature requires content and at least one selected message type.

### Settings → Writing

- Added an **Account signatures** region between automatic follow-ups and
  Personal Snippets.
- Added one account card with explicit Off/Enabled state, revision, content
  preview, New/Replies/Forwards summary, and an **Edit signature** action.
- Added a rich-editor modal with the existing formatting system, explicit Save
  and Cancel, `Cmd/Ctrl+Enter`, focus trap/return, 44-pixel controls, and no
  mutation during initial load.
- Added truthful loading, empty, API-error/retry, validation, saving, conflict,
  and narrow-screen states. A conflict reloads authoritative content instead
  of overwriting another session.

### Compose, reader, and Flow

- Added one shared `SignatureControl` and account/composition-aware resolution
  library across all three writing surfaces.
- New drafts use the selected account policy. New unsaved sender changes replace
  only provisional signature state; persisted/reply sender identity stays
  locked rather than cloning authority across accounts.
- Remove and Restore preserve frozen content and change only whether it is
  applied to this message.
- Policy loading failure visibly blocks every Send path. The user can Retry or
  explicitly Continue unsigned; a later successful Retry cannot replace the
  server-frozen unsigned acknowledgement with live policy content.
- The shared signature card is a positioned stacking boundary, so the rich
  editor hitbox cannot intercept visible Remove/Restore actions.

### Durable draft and outbound authority

- Added `composition_kind`, `signature_mode`, `quoted_html`, and `quoted_text`
  to draft/send contracts. Composition kind cannot change after draft creation.
- The server freezes one `signature_snapshot` on the first new explicit draft
  or unlinked send. It records applied state, exact account/policy revision,
  sanitized rich/plain content, SHA-256 content hash, and sanitizer version.
- Linked sends copy the draft snapshot exactly. Later settings edits cannot
  rewrite drafts, undo-window sends, scheduled mail, retries, or accepted
  outbounds.
- Save acknowledgements return authoritative signature state to the mounted
  writer. Full draft detail may include it; recent draft lists do not expose
  content. Valid empty frozen unsigned snapshots remain authoritative.
- Legacy drafts without a signature snapshot remain unsigned. A signature by
  itself does not make a draft nonblank.
- Provider draft and final-send rendering share one pure assembler and enforce
  the combined 10 MiB limit before Gmail contact.

### Forwarding and recovery

- Forwarded source history is no longer inserted into editable body content.
  It travels as a bounded structured quote and renders after the signature.
- Durable reader/Flow replies, full-Compose handoff, outbound failure recovery,
  autosave, reopen, and ambiguous response reconciliation all preserve exact
  signature and quote fields.
- Session/generation guards prevent late account-policy or save-ack responses
  from crossing an authenticated identity or replacing newer local intent.

### Generated QA and documentation

- Extended the localhost generated-provider fixture with two owned
  `.example.test` accounts, revisioned policy read/write/replay/conflict,
  immutable snapshots, Remove/Restore, forward quote state, accepted-and-undone
  outbound admission, content-free audit summaries, and strict schema parity.
- Extended the one-shot self-test for a revision-zero unsigned draft, later
  policy creation, future-only policy updates, distinct account settings,
  signature-applied send admission, and forward ordering.
- Documented the session-only API and durable sidecar decision as D-045.

## Review findings resolved before release

- Save acknowledgements initially updated controller/storage but not mounted
  Compose/reader/Flow signature state.
- Valid frozen empty unsigned snapshots were initially rejected client-side.
- Policy API failure initially risked an unexplained unsigned state instead of
  explicit Send gating.
- Generated saved policies initially omitted `sanitizer_version`, which browser
  QA correctly rejected.
- The rich editor hitbox initially covered the visible signature action card;
  browser hit-target inspection drove the shared stacking fix.
- Two older suite assertions/stubs were updated for the additive draft response
  and Send-gating contract.

## Verification

- Focused signature checks: 48 backend and 58 frontend tests before candidate
  freeze; later focused lifecycle checks also passed.
- Generated-provider self-test: passed with three frozen snapshots, one
  signature-applied accepted send followed by Undo, zero unexpected mutations,
  and zero external calls.
- Disposable PostgreSQL migration: exact
  `e8f9a0b1c2d3 → f9a0b1c2d3e4 → e8f9a0b1c2d3 → f9a0b1c2d3e4` passed.
- Generated browser: saved revision-one policy, default Compose preview,
  Remove/Restore, per-account sender behavior, desktop and 390×844 layout,
  zero console warnings/errors, zero unknown routes, zero unexpected mutations,
  and zero external calls.
- Independent P0/P1 review and final screenshot/audit user testing: SHIP.
- Consolidated release gate: 762 backend tests passed with 75 expected skips;
  all 500 frontend tests passed; production build transformed 609 modules.

Screenshots are stored outside the repository under:

```text
/Users/austinmcchord/.codex/visualizations/2026/08/31/01a0507b-7091-7032-b14a-772e3ef12b85/account-signatures/
  settings-saved-signature.png
  compose-signature.png
  compose-signature-mobile.png
```

## Production result

- Exact application/runtime and initial GitHub/production commit:
  `22320744f037bbdf18ed9893cb188ffe36f9b981`.
- Protected pre-f9 backup:
  `/var/backups/mailapp/maildb-pre-account-signatures-20260831T1303Z.dump`;
  validated with `pg_restore --list`; SHA-256
  `0465f637163571343a5f55f84b2c12c0388120e62d0aab6dc64bb268e6223c2d`.
- Production Alembic is exactly `f9a0b1c2d3e4 (head)` and the aggregate
  `account_signatures` count is zero.
- The replacement API and both workers have zero restarts and no warning-or-
  higher log entries after their 13:05:20 UTC active boundary. All seven
  checked services and public health are healthy.
- Anonymous signature policy access returns 401. Authenticated production
  Settings → Writing QA showed four default-off cards and no browser errors;
  it saved no signature, draft, send, mail action, or calendar action.
- The frontend built the same 609-module graph in production.

## Rollback boundary

Before any signature row exists, f9 can be downgraded to e8 and the application
can be reverted. Once a user saves a signature, downgrade drops user-authored
content and is data-lossy; normal recovery must retain f9 and roll application
code forward. The protected pre-f9 backup remains the disaster-recovery
boundary, not a routine application rollback.
