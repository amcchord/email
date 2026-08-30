# Session Ownership and Shell Reliability Release — 2026-08-30

## Outcome

This release makes same-document sign-out and account switching an explicit
privacy boundary, fixes the Safari More/Sync blank-page regression, enforces
Todo source-email ownership at both the API and database layers, and preserves
the latest local Compose edit during fast navigation.

The automated and browser fixtures use only generated `.example.test`
identities, messages, Todos, and drafts. No real mailbox or calendar mutation
is part of validation.

## User-visible changes

- More and Sync menus no longer make the rest of the page appear blank in
  Safari. Their fullscreen close targets remain transparent while the popover
  stays above the application shell.
- Signing out or changing identity immediately clears mail, account, label,
  sync, Compose, search, Todo, Chat, Calendar, toast, and shortcut state.
- Late results from the prior identity cannot repopulate the next user's UI,
  open a URL, advance an unsubscribe queue, export a prior-user PDF, revive a
  shortcut overlay, or publish a success/error toast.
- Logout is ordered behind any in-flight access-token refresh; login remains
  unavailable until the final cookie-clearing response completes. This keeps a
  late refresh or duplicate logout from overwriting the next login's cookies.
- Compose drafts and last-sender choices are scoped by authenticated user and
  writing intent. Legacy unscoped V1/V2 drafts are deleted rather than guessed
  into an identity. Navigation flushes the latest edit before the session guard
  is disposed, even inside the 650 ms autosave debounce.
- Canceling or failing a browser-assisted bulk unsubscribe stops the remaining
  queue and cannot claim that bulk unsubscribe completed.

## Todo ownership boundary

The generic Todo create endpoint is manual-only. Titles are trimmed and
bounded to 500 characters, email IDs are strict positive integers, request
extras are rejected, and the optional source email must belong to the current
user through `Email → GoogleAccount.user_id`.

AI action items can be created only through the ownership-scoped from-email
route. Stored analysis output is accepted only when it is a list; non-string or
empty entries are ignored, titles are bounded, and duplicates are suppressed.
A foreign email, a missing email, and an owned email without analysis all
return the same `Email not found` response.

List, update, and delete remain user-scoped. Status input is limited to
`pending`, `done`, and `dismissed`. PostgreSQL trigger
`trg_todo_items_email_ownership` enforces the same invariant for future code
paths that bypass the router.

## Migration and recovery

Alembic revision `c0d1e2f3a4b5` follows `b9c0d1e2f3a4`.

- Cross-owner AI-derived Todos are deleted because their titles may contain
  source-email content.
- Cross-owner manual Todos retain the user-authored title, but the invalid
  email link and all AI draft fields are cleared.
- Owned and unlinked rows are preserved.
- Downgrade removes the trigger and function. It intentionally cannot recreate
  purged content or unsafe links; the pre-migration database backup is the data
  rollback path.

Disposable PostgreSQL 17 rehearsal passed upgrade, ownership enforcement,
downgrade, and re-upgrade. Production preflight reported zero Todo rows, so the
cleanup statements have no current production data impact. A fresh validated
custom-format backup is still required immediately before upgrade.

## Main implementation areas

- `frontend/src/lib/authSession.js`, `frontend/src/lib/stores.js`, and
  `frontend/src/lib/api.js`: central identity generation, synchronous reset,
  request/refresh/logout ordering, and stale-response rejection.
- `frontend/src/lib/composeDraft.js` and `frontend/src/pages/Compose.svelte`:
  per-user/per-intent storage plus lifecycle-safe final persistence.
- App, Login, TopBar, Sidebar, Inbox, Todos, Chat, Flow, AI Insights,
  Subscriptions, Email View, standalone email, Device Auth, Calendar, Stats,
  Admin, mail-action status, realtime, and shortcut state: guarded async work
  and teardown.
- `backend/routers/todos.py`: strict Todo input and owned-email/analysis joins.
- `alembic/versions/c0d1e2f3a4b5_sanitize_todo_email_ownership.py`: historical
  cleanup and durable database enforcement.
- Focused backend/frontend regressions and
  `scripts/qa/generated_session_isolation_server.mjs`: ownership, lifecycle,
  popover, stream, cookie-race, and two-user generated QA.

## Verification evidence

- Full pre-release checks: 399 backend tests passed, 4 opt-in PostgreSQL tests
  skipped; 183 frontend tests passed; 507 frontend modules built.
- Focused Todo ownership tests and the real PostgreSQL rehearsal passed.
- Source-contract and deterministic session tests cover stale requests,
  refresh/retry, streams, global-state reset, delayed action notifications,
  Compose teardown, and unsubscribe cancellation.
- Independent architecture, generated-QA, and competitive UX reviews were run;
  their Todo, stale-stream, toast, draft-lifecycle, unsubscribe-continuation,
  and auth-cookie findings were closed before release.
- `git diff --check`, harness syntax, and a tracked-file secret/path audit are
  required before commit.

Generated in-app browser QA at desktop 1280×720 and mobile 375×812 verified:

- transparent More and Sync backdrops with the application shell still visible;
- no narrow-screen horizontal overflow;
- a delayed User A Todo response released only after User B login was ignored;
- User B saw only the generated B Todo, an empty Compose draft, and the B sender;
- zero fixture mutation attempts, zero unknown routes, and zero browser warnings
  or errors.

The final post-review desktop rerun again released two delayed User A Todo
responses only after User B authenticated. User B retained exactly one B Todo,
no A draft marker, the B sender, and an empty Compose surface; the fixture audit
again recorded zero mutation attempts and zero unknown routes.

Screenshots:

- `session-isolation/more-popover-desktop-1280x720.png`
- `session-isolation/user-b-after-stale-user-a-todos-1280x720.png`
- `session-isolation/more-popover-mobile-375x812.png`
- `session-isolation/final-more-popover-desktop-1280x720.jpg`
- `session-isolation/final-user-b-after-stale-user-a-todos-1280x720.jpg`

## Production access policy change

At the user's explicit request, `austin@mcchord.net` was promoted to an active
administrator. The two initially blocked addresses were added exactly, then a
later explicit authorization widened the Google OAuth allowlist only to the
trusted organization domains `@mcchord.net`, `@casanacare.com`, and
`@outsidersfund.com`. Consumer domains such as `@gmail.com` remain exact-address
only. Aggregate verification found all three domain entries and one active
admin match; no allowlist value or private account data was printed. The
database-backed setting took effect without a restart.

## Deployment record

To be completed with the exact application commit, release-record commit,
backup path and size, applied Alembic head, service action, public health,
production browser QA, and rollback reference after deployment.
