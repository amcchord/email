# Share Availability Release — 2026-08-31

## Outcome

The authenticated writing surfaces now offer one explicit **Share
availability** action in Compose, reader reply, and Flow. The user chooses the
connected primary calendars to check, meeting length, next 7 or 14 days,
working hours, weekend inclusion, timezone, and individual proposed times.
Only the selected proposal is inserted at the current draft caret.

This is deliberately a synchronized snapshot rather than live availability, a
hold, a booking link, or an invitation. It adds no Google permission, provider
write, calendar event, durable availability policy, database migration, or
background job.

## Backend changes

- Added private, POST-only `POST /api/calendar/availability` with authenticated
  session ownership and `Cache-Control: private, no-store` on success and
  route-level validation/authentication errors.
- Added a strict request contract for exact active owned accounts, a 21-day
  local-date horizon, IANA timezone, supported duration/step values, bounded
  06:00–22:00 workday, weekend choice, and minimum notice.
- Added a narrow response allowlist containing only readiness, generation time,
  timezone/duration, per-account coverage/freshness, and bounded start/end
  slots. Event content and provider identifiers never leave the service.
- Required every selected account to retain Calendar read scope, a successful
  full sync, completed status, no reauthorization need, and a successful full
  or incremental sync within 30 minutes.
- Restricted conflict reads to synchronized `calendar_id=primary` rows and
  combined every selected account before proposing a time.
- Excluded cancelled, transparent, and self-declined events from conflicts;
  kept tentative, needs-action, opaque timed, and all-day events blocking.
- Added deterministic local-time handling for gaps and folds and rejected any
  slot whose real elapsed duration differs from the requested duration.
- Closed a partial-sync race: incremental Calendar synchronization now
  publishes `syncing` before provider/event mutations, persists a non-ready
  error after a partial failure, and restores `completed` only after success.
  Availability snapshots readiness, reads events, then re-reads exact account
  sync versions and discards every slot if coverage changed.

## Frontend changes

- Added one shared accessible desktop modal and 390px bottom sheet with exact
  calendar checkboxes, date/duration/workday/timezone controls, loading, retry,
  empty, stale, reauthorization, incomplete-sync, sync-error, and syncing
  states.
- Added per-account coverage and exact last-success display inside the picker,
  with a maximum of eight selectable, date-grouped proposed times.
- Added `Cmd/Ctrl+Shift+A` in Compose, Inbox reader reply, and Flow, plus a
  visible 44px availability control beside the existing writing actions.
- Preserved rich-editor remembered selection and sanitized HTML insertion in
  Compose/Flow. Reader reply preserves the captured textarea caret, native Undo,
  authenticated draft persistence, and focus.
- Added request/session/settings/sender generation guards so a late response
  cannot cross logout, account change, or changed picker configuration.
- Kept connected account addresses and sync timestamps in the private picker;
  recipient-facing text is natural prose containing only timezone, duration,
  exact dates/times, and a request to choose a suitable time.
- Corrected the README's prior absolute “no polling required” claim: SSE is a
  best-effort connected-browser stream while Gmail and Calendar ingestion still
  use scheduled background synchronization.

## Generated acceptance system

- Added a loopback-only `.example.test` fixture with deterministic accounts,
  private event-content sentinels, ready/stale/reauthorization/no-full-sync/
  sync-error/syncing/fail-once/slow-session scenarios, and generated draft state.
- The fixture rejects and audits every email send, mail action, Calendar sync,
  event create/hold, provider action, unexpected write, non-generated address,
  and external request.
- Added contract self-tests plus desktop Compose, reader, Flow, and 390×844
  browser acceptance. The browser clock is frozen to the generated epoch so the
  fixture cannot rot with wall-clock date changes.

## Verification

- Backend post-freeze suite: 817 passed, 75 skipped. The skips are existing
  disposable-PostgreSQL suites under the deliberately unreachable default test
  URL.
- Focused post-review Calendar tests: 28 passed, including ownership,
  readiness, partial incremental failure, post-event sync-version race,
  all-day/status/attendance semantics, notice/weekend rules, primary-calendar
  filtering, slot cap, and DST regressions.
- Frontend post-freeze suite: 532 passed.
- Focused Share Availability frontend tests: 10 passed.
- Frontend production build: 622 modules transformed.
- Generated fixture self-test: passed.
- Generated browser acceptance: passed Compose, reader reply, Flow, and
  390×844 Compose; 11 availability requests, 7 successes, 3 incomplete
  responses, 1 transient retry, 1 slow/stale-session response, and 7 generated
  draft writes.
- Browser safety counters: zero provider reads/calls/writes, email sends,
  mail/calendar mutations, event creates/holds, unexpected writes, unknown
  routes, external requests, or blocked external requests.
- One bounded P0/P1 review found no P0s. Its three P1 findings—the incremental
  sync race, exact-duration DST fold, and stale/privacy-unsafe generated
  assertions—were corrected and covered before release.
- `git diff --check`: passed.

Privacy-safe evidence is outside the repository:

- `/Users/austinmcchord/Development/Email-release-evidence/share-availability-2026-08-31/compose-desktop-picker.png`
- `/Users/austinmcchord/Development/Email-release-evidence/share-availability-2026-08-31/compose-mobile-picker-390x844.png`
- `/Users/austinmcchord/Development/Email-release-evidence/share-availability-2026-08-31/flow-desktop-picker.png`
- `/Users/austinmcchord/Development/Email-release-evidence/share-availability-2026-08-31/flow-desktop-inserted.png`
- `/Users/austinmcchord/Development/Email-release-evidence/share-availability-2026-08-31/flow-mobile-picker-390x844.png`

## Production and rollback

GitHub `main` and production received exact application/runtime commit
`cf812a451c43b1a63730eaa4989d67ba0af68ba5`. Production installed the pinned
frontend dependencies, built 622 modules, and restarted `mailapp`, `mailworker`,
and `mailworker-cron` so both the API and Calendar sync-readiness boundary use
the same code. Alembic remained exactly `b1c2d3e4f5a6 (head)`.

The previous API process exceeded its graceful stop timeout and systemd killed
that old process; the first immediate public health probe therefore observed a
transient 502. The replacement API and both workers then became active at
17:57:27 UTC with `NRestarts=0`; all seven checked services are active and the
public health endpoint is stable. Anonymous availability is 401 with
`Cache-Control: private, no-store`. Signed-in read-only production QA opened
Compose and the Share Availability picker, then closed it without checking
calendars, editing/saving a draft, sending mail, or causing a calendar write.

This release is migration-free. Rollback is an application Git revert,
frontend rebuild, and selective restart of `mailapp`, `mailworker`, and
`mailworker-cron`; there is no database downgrade, provider cleanup, event
cancellation, or mailbox mutation.

## Follow-ons

- Persisted working-hour policies, delegated/subscribed calendars, holds,
  scheduling links, and writable event creation remain separate contracts.
- Trainable Focused/Other rules are the next highest-impact mail workflow gap.
- Responsive shell/Settings navigation, narrow-screen Email sidebar behavior,
  and truthful command counts remain the next bounded UX cleanup milestone.
