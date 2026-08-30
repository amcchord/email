# Reply Envelope Integrity Release — 2026-08-30

## Outcome

This release removes guessed sender identity from Inbox and Flow replies. It
uses one payload-ready envelope for both the visible From/To/Cc preview and the
eventual send or full-compose handoff. No real message was sent or mutated
during development or browser acceptance.

## What Changed

### Authoritative account and thread identity

- Email details and every thread member now expose exact `account_id` and
  `account_email` values.
- Thread reads accept an optional owned `account_id` scope. Flow supplies it
  for Needs Reply, Awaiting Response, and Active Threads so same-valued Gmail
  thread IDs cannot merge accounts in a reply workspace.
- Unknown, foreign, inactive, mismatched, ambiguous, or missing source
  identities disable Reply, Reply All, Forward, Full Compose, custom new-email
  handoff, and Send instead of falling back to the first account.
- A failed or stale thread read never falls back to an incomplete AI/list
  summary. The editor stays unavailable until the full account-scoped
  conversation is verified.

### Recipient and threading integrity

- A shared `replyEnvelope` module derives exact Reply and Reply All payloads
  for incoming and sent messages.
- Reply honors Reply-To. Reply All deduplicates recipients, removes every owned
  account and alias, preserves external To/Cc placement, and never copies Bcc.
- Existing `References` chains are exposed by the API and extended exactly once
  with the current Message-ID.
- Gmail header parsing now uses the standard-library RFC address parser, so
  quoted display-name commas and address groups no longer split into invalid
  recipients.
- Flow custom-generation compose handoff uses the same exact source-account
  resolver and has no first-account escape hatch.

### Inbox and Flow UX

- Inbox now offers an explicit Reply All action when multiple external
  recipients exist, shows the exact From/To/Cc envelope, labels the action
  `Send Reply All`, and keeps Reply as a distinct choice.
- Flow shows the exact sender and all recipients, labels multi-recipient sends
  `Send Reply All`, and presents an actionable reconnect/refresh state when
  verification fails.
- The unavailable Flow editor is removed from focus and typing order rather
  than accepting a draft that cannot be sent.
- Delayed send completion is generation-guarded, so navigation, mode changes,
  reopening the same message, or newer typing cannot erase a newer draft.
- Flow draft keys pin the initial account identity and survive account detail
  hydration and reopen across Needs Reply, Awaiting, and Active Threads.
- Inline composer icon buttons have accessible names and 44 px touch targets.
- At 375 px, the chat overlay yields to an open reply and the send/triage bar
  becomes a two-row, fully visible touch layout.

### Generated safety harness

- Opt-in localhost fixtures place the valid source account second behind a
  first-account decoy, include duplicate/self recipients, and include an
  unknown source-account message.
- A generated Active Thread proves account provenance survives the digest
  handoff.
- Fixture messages are read-only/read-state stable, every mutation route
  remains HTTP 405, and both JSON and browser-readable audit views report
  reads, mutation attempts, accepted mutations, and unknown routes.

## Verification

- `make check`: 325 backend tests passed, four opt-in PostgreSQL tests skipped;
  132 frontend tests passed; the 504-module production frontend built.
- Focused identity/address tests: seven passed.
- Harness syntax and `git diff --check`: passed.
- Generated in-app browser acceptance covered Inbox Reply, Inbox Reply All,
  unknown-source failure, Flow Reply All, Active Threads provenance, and exact
  375×812 layout without clicking Send.
- Final clean audit: exact account-scoped GETs only, zero mutation attempts,
  zero accepted mutations, and zero unknown routes.

Screenshots are stored outside the repository at:

- `/Users/austinmcchord/.codex/visualizations/2026/08/30/01a0507b-7091-7032-b14a-772e3ef12b85/reply-envelope-clean-inbox.png`
- `/Users/austinmcchord/.codex/visualizations/2026/08/30/01a0507b-7091-7032-b14a-772e3ef12b85/reply-envelope-clean-flow.png`
- `/Users/austinmcchord/.codex/visualizations/2026/08/30/01a0507b-7091-7032-b14a-772e3ef12b85/reply-envelope-flow-narrow-final.png`
- `/Users/austinmcchord/.codex/visualizations/2026/08/30/01a0507b-7091-7032-b14a-772e3ef12b85/reply-envelope-active-thread-final.png`
- `/Users/austinmcchord/.codex/visualizations/2026/08/30/01a0507b-7091-7032-b14a-772e3ef12b85/reply-envelope-clean-audit.png`

## Production Scope and Rollback

- No schema migration, dependency change, credential/configuration change,
  mailbox mutation, worker change, or AI-provider file is part of this release.
- Deployment requires a frontend rebuild and a `mailapp` restart for the
  additive API fields and account-scoped thread route.
- Rollback is a Git revert/fast-forward to the pre-release commit, a frontend
  rebuild, and a `mailapp` restart. No database rollback is required.

## User Testing

Use a conversation with multiple visible participants and confirm Reply and
Reply All remain distinct, the displayed From account is the account that
received the message, and the visible To/Cc lists match the intended audience.
For a disconnected account, confirm the UI explains the recovery step and does
not allow typing or sending until the account/thread can be verified.
