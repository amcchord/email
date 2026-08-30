# Current Status

Last updated: 2026-08-30

## Active Objective

Ship and user-test the session-ownership, Todo-ownership, Compose-lifecycle,
and Safari shell reliability release without touching real mail or calendar
data. Preserve the concurrently owned firmware work in its separate repository.

## Baseline

- GitHub `main` and production are clean at At a Glance docs closeout
  `2d20f6a3daad1734c2581dc579cb42e1012c809a`.
- Production Alembic is `b9c0d1e2f3a4 (head)` and all seven checked services
  are active; public health reports `ok`.
- Production preflight found zero Todo rows, so the ownership-cleanup migration
  has no current data impact. A new validated backup is still required before
  applying revision `c0d1e2f3a4b5`.
- At the user's request, `austin@mcchord.net` is an active administrator. Google
  OAuth now accepts the trusted organization domains `@mcchord.net`,
  `@casanacare.com`, and `@outsidersfund.com`; consumer domains remain
  exact-address only.
- The firmware milestone is isolated in the private `reterminal-color`
  repository and has not changed this Email checkout, migrations, or production.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Release Scope

- One authentication generation owns every user-derived store, request,
  refresh, stream, poller, timer, and delayed continuation. Identity changes
  synchronously clear prior-user data, and logout/login use an ordered cookie
  mutation barrier.
- Compose drafts and last-sender choices are scoped by user and intent; unsafe
  unscoped legacy drafts are purged. Navigation flushes the latest edit before
  teardown even inside the autosave debounce.
- Todo creation and AI action-item creation validate source email ownership,
  use a uniform non-disclosing 404, and are backed by a PostgreSQL ownership
  trigger plus conservative historical cleanup.
- Safari More and Sync popover backdrops remain transparent at desktop and
  mobile sizes. Cancel/failure stops browser-assisted bulk unsubscribe queues.

## Verification State

- Final `make check`: 399 backend tests passed, 4 opt-in PostgreSQL tests
  skipped; 183 frontend tests passed; 507 frontend modules built.
- Disposable PostgreSQL 17 upgrade, trigger enforcement,
  downgrade, and re-upgrade passed.
- Generated two-user in-app browser QA passed at 1280×720 and 375×812 with a
  delayed User A response released after User B login, zero leaked A content,
  zero mutation attempts, zero unknown routes, and zero console warnings/errors.
- Independent architecture, generated-QA, and competitive UX reviews approved
  the final candidate after closure of unsubscribe continuation, post-await
  toast, standalone/device surface, export/timer, Compose teardown, and
  auth-cookie races.

## Known Constraints and Follow-ups

- The generated browser harness proves deterministic A-to-B isolation without
  real mail or calendar access. Production browser verification remains
  read-only and must not trigger Sync, send, unsubscribe, or Todo mutations.
- Migration downgrade removes enforcement but cannot restore deleted or
  scrubbed historical content. The validated pre-upgrade backup is the rollback
  source.
- The At a Glance browser-flashing/API/docs slice remains deferred until this
  release is landed and its exact deployed SHA is sent to the coordinating task.

## Next Safe Action

Commit and push the exact approved candidate, take and validate a production
database backup, deploy/migrate/restart only the required application service,
then perform public health, aggregate ownership, service/log, and read-only
production shell verification.
