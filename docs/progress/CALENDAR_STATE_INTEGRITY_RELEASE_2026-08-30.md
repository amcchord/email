# Calendar State-Integrity Release — 2026-08-30

## Outcome

Calendar now behaves like an authoritative multi-account client instead of a
single best-effort fetch. Range, account, timezone, sync freshness, connection
health, and request generation are explicit. The UI cannot show events from a
superseded dataset, call an unconfirmed cache empty, or restore a prior user’s
account metadata after logout.

Application commit: `bbf96b327650b243cf50ae4d6c1707f12b08ad8c`.

## User-Visible Changes

- Navigation preserves the selected day when moving between unequal months;
  month reads exactly match the rendered 42-day grid.
- Account filters, view buttons, Previous/Next controls, and event openers have
  explicit accessible names and pressed state.
- Desktop shows Month, Week, and Day. Exact-375 mobile uses the usable Day and
  Month views, constrains account chips without document overflow, and keeps
  interactive controls at least 44 px.
- The toolbar discloses the display/query timezone.
- Reload refreshes the saved local dataset. Sync is separately labelled and
  starts Google ingestion only when the selected Calendar scope is healthy.
- Initial load, saved-data refresh, hard failure, cached failure, account-load
  failure, status failure, disconnected, reauthorization, partial, syncing,
  unverified, outside-window, and verified-empty states have distinct copy and
  recovery actions.
- Event counts deduplicate cross-account copies and say “saved events” when
  freshness is not verified.
- Day and Week start near the earliest event when it precedes the normal
  8 a.m. starting position.
- The event detail is a named modal with Escape, focus trapping, backdrop and
  Close actions, return focus, responsive bounds, timezone disclosure, and
  truthful overnight/all-day date ranges.

## Request and Account Integrity

- A Calendar request key includes view, exact range, selected account, and
  display timezone.
- Starting a new request aborts the prior request and invalidates both its
  result and its `finally` state. A slow old account/range response cannot
  replace a newer result.
- Cached data is reused only for the same immutable key. Dataset changes clear
  old visible events immediately and close stale event details.
- Account polling is single-flight and generation-scoped. Logout clears
  account/status/selection authority; late old-session responses are ignored;
  same-document login starts a clean generation; forced refresh coalesces with
  an in-flight read.
- Sidebar no longer performs an independent unguarded account fetch. App-level
  authenticated-session lifecycle owns polling and realtime start/stop.
- An account discovery error remains explicitly non-authoritative and exposes
  a retry. An empty placeholder array never masquerades as “no account.”

## Freshness and Sync Integrity

- Coverage evaluates every active visible account, including accounts without
  Calendar scope. Mixed connection health cannot claim verified data.
- `completed_at` is not used as proof of successful data because failed syncs
  can write it. Successful freshness uses `last_full_sync` or
  `last_incremental_sync`.
- Verified empty additionally requires the displayed date range to fall inside
  each selected account’s successful full-sync ingestion window. Far-history
  or far-future views say no saved events are available and explain why.
- Sync captures the exact account scope submitted by the click. Later filter
  changes cannot change the monitored targets.
- Every target must be terminal and fresh. A target is complete after
  server-observed active→idle progress, a new successful timestamp, or a
  terminal reauthorization/error state.
- Timeout copy says sync is still running only when a target is `syncing` in
  the final successful status response. Historical activity, missing status,
  or a failed status read results in “Couldn’t confirm sync completion.”
- Timers, event requests, and status requests are invalidated on unmount, so a
  departed Calendar screen cannot emit stale state or notifications.

## Date and Event Correctness

- `GET /api/calendar/events` validates ISO dates, reversed ranges, owned
  positive account IDs, and IANA timezones.
- Inclusive local query dates convert to a half-open UTC interval ending at
  midnight after the requested last day. Spring-forward and fall-back days
  therefore retain their real 23- and 25-hour durations.
- Timed overlap is `start < end_exclusive` and `end > start`; events ending at
  the lower boundary or starting at the upper boundary are excluded.
- Google all-day `end_date` remains exclusive in selection and is converted to
  an inclusive human date only for display.
- Timed events are clipped into every local day they overlap. Midnight-clipped
  ends map to minute 1440 rather than minute zero, so 11:30 p.m.–midnight
  segments and full middle days render at their real wall-clock height.
- Overnight details include the end date when it differs locally.

## Generated QA Harness

`scripts/qa/generated_search_server.mjs` now supports opt-in Calendar fixtures
for populated, verified empty, slow overlap, fail-once, disconnected, status
failure, slow initial load, and DST/boundary cases.

The fixtures use only `.example.test` identities and generated events. The
server truthfully filters range, timezone, and account, records received and
responded ordering, returns a same-origin read-only reauthorization sink,
rejects mutation methods with 405, and exposes exact Calendar read, mutation,
and unknown-route audits.

## Test Coverage

- Backend range tests cover ordinary ranges, invalid/reversed input, unknown
  timezone, 23-hour spring-forward, and 25-hour fall-back behavior.
- Calendar state tests cover exact month/week/day ranges, month clamping,
  immutable request identity, cancellation, multi-account coverage, account
  loading/failure, successful sync timestamps, full-sync windows, all-target
  monitoring, and final-response-only active assertions.
- Account polling tests cover logout-late-response, old/new generation ABA,
  coalesced refresh, retry after failure, and same-document logout/login.
- Display/layout tests cover all-day exclusive ends, cross-midnight clipping,
  half-open day boundaries, midnight minute 1440, and 24-hour middle-day
  geometry.

Final local validation:

- backend: 341 passed, 4 opt-in PostgreSQL tests skipped;
- frontend: 156 passed;
- production frontend: 506 modules transformed;
- harness syntax and `git diff --check`: passed.

Three independent architecture, competitive UX, and QA reviews found and then
verified closure of stale account authority, false loading/unavailable state,
midnight geometry, out-of-window verified-empty, and sync-timeout truthfulness
blockers. All three final release gates passed.

## Browser Evidence

Generated in-app browser evidence in the task visualization directory under
`calendar-state-integrity/` includes:

- `populated-final-1440x900.png` and `populated-final-375x812.png`;
- `verified-empty-final-1440x900.png` and
  `verified-empty-final-375x812.png`;
- `outside-saved-window-final-1440x900.png`;
- `load-error-final-375x812.png` and
  `retry-recovered-final-375x812.png`;
- `slow-primary-fast-secondary-week-final-1440x900.png`;
- `partial-disconnected-all-1440x900.png`;
- `status-unavailable-empty-1440x900.png` and
  `disconnected-account-1440x900.png`;
- `event-dialog-1440x900.png` and `event-dialog-375x812.png`;
- `dst-boundary-final-1440x900.png`.

The final DST day contained only generated carry-in, both repeated 1:30 a.m.
instants, and the all-day fixture (IDs 9301–9304). Exact boundary fixtures
9305–9306 were excluded. Fresh audits recorded zero accepted mutations and
zero unknown routes; generated reauthorization remained on the localhost sink.

## Deployment

Pending. The production rollback point is `aa91430`. This release requires no
migration, dependency-lock update, worker restart, terminal/e-ink change,
AI-provider change, Caddy/systemd change, Google grant, allowlist edit, mailbox
write, or calendar write. The deployment scope is a clean Git fast-forward,
locked frontend install/build, and restart of only `mailapp`, followed by Git,
health, service, log, and read-only app-shell verification.
