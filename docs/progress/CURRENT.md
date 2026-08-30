# Current Status

Last updated: 2026-08-30

## Active Objective

Deploy and user-test the Calendar state-integrity release without touching the
separately owned At a Glance/terminal or AI-provider work. The application
candidate is `bbf96b327650b243cf50ae4d6c1707f12b08ad8c`; documentation and
post-deploy evidence are being finalized.

## Baseline

- Production and GitHub `main` are clean and exact at OAuth fail-safe release
  `aa91430b76c081d6ed0e0de5f1726086a850f8e5`. Public health is `ok` and all
  seven checked services are active.
- The Calendar release is isolated in
  `/Users/austinmcchord/Development/Email-calendar-state-integrity` on
  `codex/calendar-state-integrity`.
- The concurrent At a Glance task owns the terminal routers/models/services,
  Admin UI, two terminal Alembic revisions, terminal documentation, and an
  overlapping `docs/api.md` addition. Its owner will preserve both API sections
  while rebasing after this release.
- This Calendar candidate contains no migration, dependency-lock, worker,
  terminal/e-ink, AI-provider, Caddy/systemd, or production-configuration work.
  The rollback code point is `aa91430`.
- A validated 1.38 GB custom-format backup remains protected at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`, mode
  `0600`, owned by `postgres`. This release does not change the schema.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Calendar Release Scope

- Every view/account/timezone/range owns an immutable request identity.
  Superseded reads abort and late completions cannot overwrite the visible
  dataset or its loading/error state.
- Account authority is generation-scoped across login, logout, polling,
  unmount, retry, and same-document re-login. Calendar distinguishes account
  discovery from freshness/status reads.
- Empty results are described as verified only when every visible calendar has
  a successful full-sync window covering the displayed range. Unknown,
  disconnected, partial, stale, syncing, failed, and outside-window states use
  honest saved-data copy and recovery actions.
- Reload reads the local cache; Sync starts Google ingestion and monitors the
  exact submitted account set. Completion requires every target to reach a
  terminal/fresh state, and timeout copy only says “still running” when the
  final status response says a target is currently syncing.
- API date boundaries are local-date, DST-correct, half-open intervals. Timed
  and all-day events ending exactly at the lower boundary are excluded.
- Cross-midnight events render on every overlapping local day, including
  midnight-clipped and full-middle-day segments. Google all-day exclusive ends
  display correctly, and overnight details show both dates.
- Desktop and exact-375 layouts expose account scope, timezone, responsive
  Day/Month views, 44 px controls, accessible view/filter state, and a proper
  focus-trapped event dialog.

## Verification State

- `make check`: 341 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  156 frontend tests passed, and the 506-module production frontend built.
- Focused Calendar/account tests cover DST 23/25-hour ranges, exact boundary
  exclusion, month-grid ranges, stale response ordering, account-generation
  ABA races, retry recovery, sync target completion, coverage windows,
  exclusive all-day ends, and midnight/full-day geometry.
- Generated in-app browser QA covers loading, populated, verified empty,
  outside-window empty, failure/retry, disconnected/partial, unavailable
  status, slow account overlap, DST boundaries, reauthorization, event dialog,
  desktop, and exact 375×812 layouts.
- Fresh audit evidence contains only generated `.example.test` identities,
  exact expected Calendar GETs, zero accepted mutations, and zero unknown
  routes. The boundary day returned only IDs 9301–9304 and excluded exact
  lower/upper-boundary fixtures.
- Independent architecture, competitive UX, and QA release gates report no
  remaining P0/P1 blockers.

## Known Constraints and Follow-ups

- The two newly reported external Google accounts remain absent from the
  production allowlist. No allowlist or Google grant changed; prefer adding
  only the exact addresses after explicit confirmation.
- Calendar remains a bounded local cache. The UI now discloses ranges outside
  the confirmed full-sync window instead of certifying them empty. A future
  product slice could add demand-loaded historical/future ranges.
- Real mail and calendars remain read-only for user testing. Only generated
  fixture messages/events may be mutated.
- The remote-content and reply-envelope constraints documented in their
  release records remain in force.

## Next Safe Action

Push the reviewed Calendar branch and fast-forward `main`, deploy the exact
release commit with a frontend rebuild and only a `mailapp` restart, then
record health, service, Git, log, and read-only shell verification.
