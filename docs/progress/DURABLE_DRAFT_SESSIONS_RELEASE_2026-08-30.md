# Durable Draft Sessions Release — 2026-08-30

## Outcome

Full Compose now treats a draft as a durable, versioned writing session rather
than a best-effort request to Gmail. Text, recipients, sender identity, reply
provenance, rich HTML, and attachment bytes survive a hard reload. The UI says
whether a revision is saved locally, syncing, confirmed by Gmail, offline,
ambiguous, failed, conflicted, pending discard, or discarded.

The system preserves the safe outbound contract released earlier: sending a
draft links the exact owned client UUID and revision to one at-most-once send.
It never turns an uncertain provider result into a second blind create or send.

Release status at authoring: reviewed candidate on
`codex/durable-draft-sessions`; the exact landed and deployed runtime commit is
recorded in the post-deploy closeout below.

## User-visible changes

- Every new Compose action creates a distinct stable draft UUID. Opening two
  new composers no longer aliases both to a generic `new` slot.
- Compose stores the current draft in user-scoped IndexedDB before relying on
  the network. Old browser keys that did not prove an authenticated owner are
  purged; only safe owner-scoped legacy records are migrated after the durable
  write succeeds.
- The stable UUID is carried in the Compose URL. Reloading the page, using
  browser history, or returning to an in-progress Compose route reopens that
  exact local writing session.
- Autosave copy distinguishes `Unsaved changes`, `Saved on this device`,
  `Saving draft…`, `Draft saved`, offline recovery, ambiguous reconciliation,
  retryable failure, and a real cross-session conflict.
- Attachment import blocks Send until FileReader has finished. Imported bytes,
  type, name, identifier, and display size survive reload; a failed import is
  visible and actionable.
- The back arrow and Escape close Compose while retaining the draft. Destructive
  discard is a separate button and shortcut (`Ctrl+Shift+,`). `Ctrl+S` forces a
  durable save.
- Discard begins on the server and exposes Undo only for the authoritative
  ten-second window. The browser does not erase its local recovery copy until
  the server confirms provider deletion.
- If another session writes a conflicting revision, Compose keeps the local
  copy and offers an explicit review choice between the local and server
  versions.
- Drafts created by this application can be reopened from Gmail's Drafts
  mailbox. Provider drafts with no managed session remain safely read-only,
  avoiding a misleading edit flow that cannot preserve revision ownership.
- A reply's sending account stays locked to its authoritative source-message
  provenance. Draft autosave never guesses an account or reconstructs reply
  headers from display-only data.
- Send includes the exact draft UUID and revision. Compose clears the local
  editor only when the accepted send still owns that same revision; newer edits
  remain as their own safe draft.
- The browser retains the send-owned, auth-scoped IndexedDB snapshot until
  terminal truth. A confirmed send deletes it; Undo or failure opens a fresh
  Compose identity and removes the source only after that recovery is durable.

## Backend and provider behavior

### PostgreSQL authority

Migration `e2f3a4b5c6d7` follows `d1e2f3a4b5c6` and adds:

- `draft_sessions`: user/account ownership, client identity, immutable
  revision hashes, reply-source snapshots, stable RFC Message-ID, provider
  identity, attempt/reconciliation state, leases, discard deadlines, safe
  errors, timestamps, and optional send linkage;
- `draft_attachments`: ordered attachment identifiers, hashes, exact bytes,
  sizes, and content types owned by one draft session;
- `draft_mutations`: bounded receipts for idempotent upsert, discard, and Undo
  operations;
- optional `draft_session_id` and `client_draft_id` linkage on
  `outbound_messages`, including a one-send-per-session partial unique index.

Database constraints enforce valid lifecycle states, positive revisions,
non-negative attachment totals, lease/state agreement, discard deadline
agreement, scrubbed terminal rows, per-user client UUID uniqueness, per-account
RFC Message-ID uniqueness, provider-draft uniqueness, attachment order, and
mutation identity.

The upgrade is additive. Downgrade removes the outbound linkage and all three
draft tables, so it destroys retained draft-session content and must never be
run casually. Application rollback can leave the additive schema in place.

### Durable admission and quotas

`POST /api/compose/draft` commits the exact revision and attachment bytes before
returning 202. PostgreSQL serializes admission per user. It enforces 100 active
drafts per user, 60 per account, 120 recent mutations per user per minute, 90
per account per minute, 500 MiB retained per user, 250 MiB per account, and the
existing Compose recipient/body/attachment limits. Same-mutation replay does
not consume another logical mutation.

Changed content at an existing revision, stale revisions, mutation reuse with a
different payload, foreign accounts, inactive accounts, unsafe reply sources,
and invalid attachments fail before provider work. Errors expose stable safe
codes rather than database or Google details.

### Gmail reconciliation

The worker creates one deterministic RFC Message-ID and adds private client
draft headers. Initial provider creation is attempted at most once. If the
Gmail response is lost or the worker stops after the attempt boundary, recovery
searches for the stable identity and never blindly creates a replacement.
Confirmed sessions update the known Gmail draft for later revisions.

Work is leased in PostgreSQL with bounded retries and finite Gmail timeouts.
Redis only accelerates wakeup; `mailworker-cron` drains due sessions every
minute and reclaims expired leases. Account advisory locks serialize draft
provider changes with other account mutations.

Discard follows the same truth model. Undo is accepted only inside the
server-owned deadline. As soon as that deadline expires, recipients, bodies,
and attachment bytes are scrubbed before provider work; provider delete and
ambiguous-outcome reconciliation continue from a content-free tombstone.

### Send handoff

The outbound endpoint accepts a linked draft only when both
`client_draft_id` and `draft_revision` are present and prove the current user's
exact session. Admission moves that session to `sending`. Accepted outbound
admission schedules provider-draft cleanup for the authoritative Undo deadline;
that cleanup proceeds independently if outbound delivery is still retrying or
reconciling. The browser retains the send-owned recovery snapshot until
terminal delivery truth, so failed or cancelled delivery returns the editor
through the existing safe recovery surface without silently losing a newer
revision.

## API surface

The authenticated web session gains:

```text
POST /api/compose/draft
GET  /api/compose/drafts/recent?limit=20
GET  /api/compose/drafts/by-client-id/{client_draft_id}
GET  /api/compose/drafts/by-email/{email_id}
POST /api/compose/drafts/{client_draft_id}/discard
POST /api/compose/drafts/{client_draft_id}/undo-discard
```

Public `/api/v1` tokens cannot call these routes. Recent responses contain
metadata only. Detail responses are user-scoped and contain content and bytes
because they exist specifically to restore the authenticated editor. The full
request, response, state, limit, error, and safety contract is in
[`docs/api.md`](../api.md#web-session-only-durable-draft-sessions).

## Changed code

### Backend

- `backend/models/draft.py`, `backend/models/account.py`,
  `backend/models/outbound_message.py`, and `backend/models/__init__.py` define
  the durable graph and send relationship.
- `backend/services/drafts.py` owns admission, hashing, quotas, leases, Gmail
  create/update/reconciliation, discard/Undo, scrubbing, and cron draining.
- `backend/services/gmail.py` adds bounded draft create/update/delete and
  stable-identity lookup primitives without changing AI behavior.
- `backend/services/outbound_messages.py` validates and transitions an exact
  linked revision through send lifecycle.
- `backend/routers/compose.py` replaces direct best-effort draft saving with
  durable session routes and safe response shaping.
- `backend/schemas/email.py` adds draft request, mutation, metadata, and detail
  contracts; `backend/middleware/compose_body_limit.py` applies the existing
  bounded-body protection to draft bytes.
- `backend/workers/tasks.py` registers and schedules the draft drainer on the
  isolated cron/short-job queue. No AI worker behavior or provider-model file
  was changed.

### Frontend

- `frontend/src/lib/draftStorage.js` provides user-scoped IndexedDB storage,
  an in-memory test adapter, and fail-safe scoped legacy migration.
- `frontend/src/lib/draftSession.js` owns the reusable state machine, revisions,
  mutations, debounce/flush, offline recovery, reconciliation, conflicts,
  attachment gates, discard/Undo, and auth-generation suppression.
- `frontend/src/lib/composeDraft.js` creates stable per-intent UUIDs and maps a
  validated draft identity into the Compose URL.
- `frontend/src/components/email/DraftStatus.svelte` renders concise,
  accessible lifecycle copy and Retry, Undo, or Review controls.
- `frontend/src/pages/Compose.svelte` integrates durable storage, truthful
  autosave, reload-safe URL identity, attachment persistence, safe close,
  discard/Undo, exact send linkage, and account provenance.
- `frontend/src/components/email/EmailView.svelte` reopens only app-managed
  provider drafts and explains why an external draft remains read-only.
- `frontend/src/components/layout/Layout.svelte` and `Sidebar.svelte` create a
  fresh writing identity for every Compose command.
- `frontend/src/App.svelte` retains the validated UUID across reload and browser
  history without exposing message content in the URL.
- `frontend/src/lib/api.js` adds the authenticated lifecycle client, and
  `shortcutDefaults.js` separates safe close from destructive discard.

### Tests and generated QA

- Backend unit, ASGI, PostgreSQL, Compose, middleware, and outbound tests cover
  persistence, ownership, quotas, immutable revisions/mutations, provider
  ambiguity, deletes, leases, reply provenance, attachment bytes, send linkage,
  and migration behavior.
- Frontend tests cover isolated identities, storage migration, lost responses,
  pending acknowledgement, offline/reload recovery, conflict resolution,
  attachment gates, discard/Undo, stale authenticated sessions, managed Draft
  reopening, deep-linked reload identity, and shortcut semantics.
- `scripts/qa/generated_provider_draft_server.mjs` is a localhost-only,
  in-memory provider fixture restricted to reserved `.example.test` addresses.
  Its audit contains hashes and counters, never message or attachment content.
- `scripts/qa/generated_provider_draft_self_test.mjs` exercises clean create and
  update, immutable conflicts, lost response, attachment rehydration, exact
  reply/account provenance, stale sessions, discard/Undo replay, delete
  failure, offline recovery, and hostile-input rejection with zero external
  network calls. Generated Draft email IDs are immutable per logical draft, so
  removing one fixture draft cannot retarget a stale ID to another draft.

## Verification evidence

- Backend: 472 passed, 21 PostgreSQL-gated skips in the ordinary suite.
- Frontend: 256 passed after the final reload-time Undo recovery and dialog
  accessibility corrections.
- Production frontend build: 518 local modules before deployment.
- Disposable PostgreSQL 17: migration upgraded to `e2f3a4b5c6d7`, eight focused
  database tests passed, downgrade returned to `d1e2f3a4b5c6`, re-upgrade
  returned to `e2f3a4b5c6d7`, and the focused concurrency/scrub tests passed.
- Generated provider matrix: every scenario passed with zero unexpected
  mutations, unknown routes, or external network calls in the self-test.
- Browser QA at 1280×720 and 390×844 proved stable URL identity, hard-reload
  content recovery, attachment-byte and size recovery, truthful `Draft saved`
  status, and a clean final console. Browser inspection found and drove fixes
  for the missing reload identity, lost attachment size metadata, and an async
  file-input cleanup exception before release. The final fixture audit recorded
  one expected draft create and one attachment upsert with zero unexpected
  mutations, unknown routes, external calls, warnings, or browser errors.

Screenshots:

- `/Users/austinmcchord/Desktop/email-generated-durable-draft-desktop-2026-08-30.png`
- `/Users/austinmcchord/Desktop/email-generated-durable-draft-mobile-2026-08-30.png`

No browser QA request reached a real mailbox. The interactive fixture accepted
only `.example.test` draft mutations and reported zero unexpected mutations and
zero external network calls. Destructive discard/Undo behavior was exercised
by the generated self-test rather than through production.

## Scope deliberately deferred

- Flow and reader inline reply boxes still use their existing in-memory editor
  handoff until they expand into full Compose. Extending the same durable
  controller into both inline surfaces is the next email-client milestone.
- Recent draft metadata exists server-side, but no separate cross-device Recent
  Drafts picker ships in this slice; Gmail Drafts reopening covers managed
  provider drafts.
- This release does not change AI models, prompts, providers, summaries,
  classifications, or the separate terminal firmware/enrollment work.
- Production browser QA remains read-only. Creating, editing, discarding, or
  sending a real draft is left to explicit user testing.

## Deployment and rollback

Before migration, create and validate a fresh PostgreSQL custom-format backup.
Deploy the exact reviewed Git commit, run `alembic upgrade head` as `mailapp`,
build the frontend as `mailapp`, and restart only `mailapp` and
`mailworker-cron`. Requirements, Caddy, mailworker's AI queue, and mailtui do
not need a change.

For application rollback, stop the new API/cron code and return both services
to the prior Git commit while leaving the additive `e2f3a4b5c6d7` schema in
place. Downgrading to `d1e2f3a4b5c6` drops durable draft rows and attachment
bytes and therefore requires an explicit data-loss decision plus the validated
backup.

## Post-deploy closeout

Pending authorized release. Record the exact application commit, docs closeout
commit, backup path/size, production Alembic head, build count, service state,
health response, recent-log audit, and read-only user-facing verification here.
