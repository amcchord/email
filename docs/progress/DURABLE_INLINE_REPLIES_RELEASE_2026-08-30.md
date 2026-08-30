# Durable Inline Replies Release — 2026-08-30

## Outcome

Reader and Flow replies now use the same durable writing-session contract as
full Compose. A reply is stored locally before remote debounce, survives close,
navigation, hard reload, offline work, and cross-device continuation, and keeps
one exact identity across Reader, Flow, Compose, and Drafts. The UI never calls
a reply saved merely because an editor still contains it, and it does not claim
send or discard success before the existing server state machines do.

This release is migration-free and preserves secure terminal enrollment head
`f3a4b5c6d7e8`. It changes no Gmail send worker, AI file, terminal runtime,
Caddy policy, firmware artifact, credential, or production mailbox data.

The exact landed and deployed application/documentation commit is
`9aa93f61fe7031ce267b833930a84c5d0a2121c3`. The following repository
closeout changes only progress documentation; no additional runtime is
deployed from it.

## User-visible changes

- Opening Reply in the message reader or Flow immediately creates or reopens
  one owner-scoped local writing session identified by the exact account and
  source email.
- Every edit is committed to IndexedDB before the remote debounce. Status copy
  distinguishes saved on this device, syncing, Gmail-confirmed, offline,
  failed, conflicted, send-owned, discard-pending, and discarded states.
- Close and internal navigation flush the current reply first. Navigation is
  refused with actionable copy if local storage failed, while discard is in
  progress, or while send reconciliation owns the draft.
- Closing a saved reply restores keyboard focus to its Reply control and tells
  the user that the draft is available from Drafts. Accepted send teardown also
  returns focus without announcing delivery prematurely.
- Reopening the same message, hard reloading, or opening the reply on another
  device restores the same server/client draft rather than creating a second
  Gmail draft.
- Reply and Reply All share the saved content. Switching modes rebases only the
  verified recipient envelope and reply headers, removes owned identities, and
  keeps the body and attachment state intact.
- The inline composer exposes Retry, conflict review, safe discard with Undo,
  open-in-full-Compose, and truthful send-state recovery through the shared
  Draft Status component.
- Flow keeps the active draft while changing messages, opening threads,
  closing the reply view, snoozing, ignoring, archiving, or moving to trash.
  Those actions proceed only after the draft transition guard succeeds.
- Drafts now starts with a responsive **Continue writing** region. It combines
  current-device and recent server metadata, shows sync state, and reopens the
  exact reply or Compose identity. It never downloads draft bodies merely to
  render the list.
- The Working Drafts card survives offline reload and preserves a known newer
  server revision so full Compose compares authoritative state before editing.

## Backend contract

### Exact-source lookup

The authenticated web session gains:

```text
GET /api/compose/drafts/by-source-email/{source_email_id}?account_id={account_id}
```

The lookup is scoped simultaneously to current user, active owned account, and
exact source email. It returns one active reply detail response, the same
non-disclosing 404 for missing or foreign state, and 409 when legacy duplicate
reply rows require explicit review.

### Concurrent first-save convergence

Draft admission already serializes per user. A new reply save now checks for an
active session with the same account and source before inserting. If another
client UUID won the race, the loser receives 409
`draft_source_exists`. The client then performs the exact-source lookup and may
adopt only an editable winner. Sending, discard-pending, discarded, conflicted,
or ambiguous sessions retain their own identity and cannot be silently
replaced.

This prevents two browser tabs or devices from creating parallel provider
drafts for one source message without weakening the existing revision,
mutation, account, provenance, quota, or provider-ambiguity checks.

### Metadata-only recent drafts

`GET /api/compose/drafts/recent` now projects only lifecycle and listing
metadata. Its query does not load recipients, subject, body, provider IDs,
reply headers, or attachment bytes. Content remains available only through an
authenticated owned detail lookup when the user explicitly opens a draft.

## Frontend architecture

### Shared durable reply wrapper

`frontend/src/lib/durableReply.js` defines the stable
`reply:{account_id}:{source_email_id}` intent, freezes exact reply provenance,
converts text/HTML safely, looks up cross-device state, and rebases only a
verified editable envelope. It binds every open to one captured authenticated
session and checks that session after each awaited storage or API boundary, so
a late user-A result cannot enter user-B storage or UI.

The existing `draftSession` controller now supports exact-source winner
adoption, conflict-locked sends, and a bounded discard lifecycle that survives
component teardown long enough to finish byte scrubbing or honor a captured
Undo action.

### Reader, Flow, and Compose

- `EmailView.svelte` hosts the inline controller, status/recovery actions,
  transition guard, Reply/Reply All envelope changes, discard/Undo, durable
  send handoff, Compose handoff, and focus restoration.
- `Flow.svelte` uses the same wrapper and guards every reply-view transition or
  mail action that could release the editor.
- `Inbox.svelte` asks the selected reader whether it is safe to change message,
  mailbox, account, search, smart filter, page, or an action that removes the
  selected row. A refused transition restores the last committed dataset
  controls.
- `Compose.svelte` compares the server revision advertised by Continue Writing
  after loading its local record, preventing a newer cross-device draft from
  being hidden by a stale local snapshot.

### Continue Writing

`WorkingDrafts.svelte` and `recentDrafts.js` merge local and server metadata
without merging identities. Each row retains its stable route intent, exact
reply intent when applicable, account/source identity, lifecycle state, and
known server revision. Discarded rows are excluded and fallback labels remain
useful without body retrieval.

## Changed code

### Backend

- `backend/routers/compose.py`: exact-source route and stable
  `draft_source_exists` response.
- `backend/services/drafts.py`: exact-source ownership lookup, first-save
  convergence, and metadata-only recent projection.
- `backend/tests/test_draft_sessions.py`,
  `test_draft_sessions_asgi.py`, and `test_draft_sessions_postgres.py`: route,
  ownership, projection, conflict, and concurrent first-save coverage while
  preserving the terminal f3 migration assertions.

### Frontend

- `frontend/src/lib/durableReply.js` and tests: shared reply identity,
  cross-device discovery, session capture, envelope rebase, and safe winner
  adoption.
- `frontend/src/lib/draftSession.js` and tests: conflict-locked send,
  source-winner rules, discard/Undo survival after UI disposal, and exact
  state-machine assertions.
- `frontend/src/components/email/EmailView.svelte`,
  `frontend/src/pages/Flow.svelte`, and `frontend/src/pages/Inbox.svelte`:
  durable inline editors and navigation/action guards.
- `frontend/src/components/email/WorkingDrafts.svelte`,
  `frontend/src/lib/recentDrafts.js`, and tests: responsive metadata-only
  Continue Writing surface.
- `frontend/src/pages/Compose.svelte`, `composeDraft.js`, and tests: advertised
  server-revision comparison before editing.
- `frontend/src/lib/api.js`, API tests, the Sidebar Drafts indicator, and
  source-level safety regressions complete the integration.

### Generated QA

- `scripts/qa/generated_provider_draft_server.mjs` implements exact-source
  fixture lookup and conflict behavior entirely in memory and only for
  `.example.test` identities.
- `scripts/qa/generated_provider_draft_self_test.mjs` covers repeated autosave,
  immutable conflicts, lost responses, attachment reload, exact provenance,
  first-save source conflict, metadata-only recent results, stable mailbox
  identity, stale sessions, discard/Undo, provider delete failure, offline
  recovery, and hostile-input rejection.

## Verification evidence

- After rebasing onto secure terminal closeout
  `2fd5e4c776e3dd808ac7e1bb32110a7e3ce16e73`, the ordinary backend suite passed
  550 tests with 35 intentional PostgreSQL/external skips.
- Ten focused draft tests passed against disposable PostgreSQL 17, including
  concurrent first saves and metadata projection.
- Frontend passed 295 tests. The production build transformed 524 modules.
- The generated provider scenario matrix passed. Expected hostile-input tests
  were rejected; all normal scenarios reported zero unexpected mutations,
  unknown routes, non-fixture delivery, or external network calls.
- Desktop and 390×844 browser QA used only generated `example.test` messages.
  It proved save, close, focus restoration, reopen, hard-reload recovery,
  full-Compose handoff, and Continue Writing on desktop and mobile. The final
  positive-flow audit recorded zero sends, discards, deletes, unknown routes,
  external calls, or non-`example.test` recipients.
- Three independent backend, frontend, and generated-QA reviews reported no
  remaining P0–P2 issue after session-transition, local-save navigation,
  discard-teardown, conflict-send, server-revision, and focus findings were
  corrected.
- `git diff --check` passed. No secret, OAuth credential, mailbox content,
  production configuration, database dump, generated build, or attachment was
  added.

## Production actions and closeout

- Fast-forwarded GitHub `main` and the clean production checkout from secure
  terminal closeout `2fd5e4c776e3dd808ac7e1bb32110a7e3ce16e73` to exact
  application/documentation commit
  `9aa93f61fe7031ce267b833930a84c5d0a2121c3`.
- Restarted only `mailapp` so the exact-source API preceded the new browser
  bundle. One retired worker retained a long-lived connection through the
  90-second stop window and systemd killed that old process; the replacement
  started cleanly with two ready workers, zero automatic restarts, and no
  warning-or-higher entry after application startup.
- Installed the unchanged locked frontend dependencies as `mailapp`: 145
  packages audited with zero vulnerabilities. Production built the same 524
  modules as the reviewed local candidate. No Caddy reload, worker restart,
  dependency change, schema migration, database backup, or data write was
  required.
- Postflight verified exact clean Git, Alembic still exactly
  `f3a4b5c6d7e8 (head)`, all seven checked services active, public health `ok`,
  the new durable-reply asset returning 200, and anonymous exact-source draft
  lookup returning 401.
- Authenticated read-only production QA opened Drafts and verified one visible
  **Continue writing** region and its Refresh control. It did not open a real
  message or draft, enter content, send, discard, archive, delete, change a
  terminal, or mutate a calendar.

## Rollback and next boundary

This slice has no migration and can be rolled back at the application commit
without changing Alembic `f3a4b5c6d7e8`. Existing durable draft rows retain the
same schema and remain readable by the preceding Durable Draft Sessions
release; the new exact-source route and Continue Writing UI simply disappear.

After production closeout, the exact shared-shell SHA is the rebase point for
the migration-free first-class At a Glance route. That follow-on may touch app
routing and primary navigation, but it must preserve the reply transition
guards and keep terminal Serial, firmware writes, enrollment, and OTA locked.
