# Current Status

Last updated: 2026-08-30

## Active Objective

User-test the deployed session-ownership, Todo-ownership, Compose-lifecycle,
and Safari shell reliability release without touching real mail or calendar
data, then continue the next scoped product-improvement cycle. Preserve the
concurrently owned firmware work in its separate repository.

## Baseline

- The released application code is
  `18e80fdd9247c52825b225e55b85aabc240e76d3`; GitHub `main` and production
  contain that exact application state plus the docs-only closeout.
- Production Alembic is `c0d1e2f3a4b5 (head)`, all seven checked services are
  active, the exact frontend asset returns 200, and public health reports `ok`.
- Production preflight and postflight both found zero Todo rows and zero
  ownership mismatches. The ownership trigger/function are installed. The
  validated pre-upgrade backup is
  `/var/backups/mailapp/maildb-pre-session-ownership-20260830T1559Z.dump`.
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
- Production verification passed: exact clean Git, Alembic head, all services,
  public health, static asset, unauthenticated Todo boundary, aggregate database
  invariants, and zero new `mailapp` warning-or-higher log entries.
- Signed-in production browser QA opened More at 1280x720: the fullscreen close
  target was transparent, the menu and main page remained visible, and no
  browser warning/error appeared. No real-data mutation was exercised.

## Known Constraints and Follow-ups

- The generated browser harness proves deterministic A-to-B isolation without
  real mail or calendar access. Ongoing production user testing remains
  read-only and must not trigger Sync, send, unsubscribe, or Todo mutations.
- Migration downgrade removes enforcement but cannot restore deleted or
  scrubbed historical content. The validated pre-upgrade backup is the rollback
  source.
- The At a Glance browser-flashing/API/docs slice may rebase after receiving
  this release's exact landed/deployed docs closeout SHA.

## Next Safe Action

Have the user verify More and reauthorization for the newly trusted organization
domains. Continue generated-fixture product improvements and read-only
production observation; keep real mail, calendar, and Todo mutations out of
automated QA.
