# Progress Journal

Newest entries go first. Keep entries concise and factual. Never include
secrets, email contents, OAuth tokens, or raw private production data.

## 2026-08-29 — Scheduling delegation and trusted-colleague context

### Scope

Teach triage, follow-up options, chat, and mail queues that Andrea Durbin owns
Austin's scheduling and that Angie Mecham is a trusted close colleague, with
special handling when Andrea is included on To or Cc.

### Completed

- Added one structured workflow-context module for known relationships,
  address normalization, prompt context, deterministic AI result correction,
  and a shared SQL predicate for delegated scheduling.
- Included Cc recipients in email analysis, sent-mail classification, thread
  analysis, action-item replies, and custom-reply prompts.
- Made "Andrea to coordinate" the default scheduling quick reply when a
  response is needed and Andrea is not the sender.
- Removed routine low/normal-priority scheduling already sent to Andrea from
  Austin's action items, needs-reply, awaiting-response, and important queues;
  high/urgent exceptions remain visible.
- Applied the workflow correction at read time as well as analysis time so
  existing AI rows improve without a destructive reprocessing job.
- Prevented direct questions from Andrea from being delegated back to her and
  prevented Andrea or Angie from remaining classified as cold outreach.
- Coordinated file ownership and Git timing with the parallel app-wide UX task;
  neither task staged or rewrote the other's work.

### Verification

- `make test`: 128 tests passed.
- Added eight focused tests for address parsing, Cc context, routine and urgent
  scheduling, Andrea handoff options, direct mail from Andrea, Angie trust, and
  PostgreSQL queue predicates.
- Needs-reply and awaiting-response SQLAlchemy queries compiled successfully
  with the PostgreSQL dialect.
- Python bytecode compilation and `git diff --check`: passed.

### Production Actions

- Pushed `ab33499` to `origin/main` and fast-forwarded the clean production
  checkout from `e849e9f` to that exact commit as `mailapp`.
- Restarted `mailapp`, `mailworker`, and `mailworker-cron`; no dependency
  install, frontend rebuild, migration, data mutation, TUI restart, Caddy
  change, or proxy reload was required.
- The old Uvicorn process again retained a long-lived connection through its
  90-second stop timeout, producing a transient 502 until systemd killed the
  old process and started the replacement. Both API workers completed startup,
  both ARQ workers restarted cleanly, all application services are active,
  health is `ok`, and the post-start error count is zero.
- Ran a production-side pure routing assertion confirming that routine
  scheduling with Andrea on Cc becomes `fyi`, clears Austin's reply flag, and
  removes the scheduling action item without reading mailbox data.

### Next

The requested workflow is complete in production. Resume the separately scoped
Google OAuth publishing-status work when authorized.

## 2026-08-29 — App-wide UX release implementation

### Scope

Implement the ten user-facing improvements from the authenticated production
audit across responsive navigation, account health, mail/Flow, Calendar,
Compose, Subscriptions, Stats, loading states, and accessibility.

### Completed

- Reworked the mobile shell into overlay/list-detail patterns, added a global
  More menu for hidden feature areas, and made page routes deep-linkable.
- Unified mail and calendar account health, added reconnect actions, and
  preserved existing OAuth refresh tokens when repeat consent omits a new one.
- Cleaned encoded/invisible mail text, expanded cryptic classifications, and
  eliminated frontend accessibility diagnostics across mail rows, Flow reply
  cards, calendar events, settings forms, and common inputs.
- Ranked the visible Flow queue by urgency and freshness and made its chat pane
  a mobile overlay rather than a permanently fixed column.
- Added a narrow-screen Calendar day view, readable video-call locations, and
  keyboard-operable event cards.
- Added account-aware sender selection, visible sender context, debounced local
  draft recovery, recipient chips, and attachments with client/server limits.
- Added subscription evidence levels and review gating, removed default spam
  marking, corrected impossible relative dates, and limited bulk actions to
  high-confidence items.
- Added period/account Stats filters, future-date exclusion, normalized sender
  grouping, and Inbox drill-down from sender rows.
- Added skeleton loading states and useful empty actions to the largest
  asynchronous pages.

### Verification

- `make check`: passed; 128 tests passed and the production frontend build
  completed with no Svelte accessibility diagnostics.
- Three focused follow-up frontend builds passed after authenticated visual QA
  found and corrected a narrow-screen Compose sender overflow; the final sender
  control fits at 390px and uses a concise primary-account label.
- Added three tests covering attachment MIME construction, invalid attachment
  data, and header-newline stripping.
- `git diff --check`: passed before release review.
- Saved final authenticated screenshots for desktop Flow, More, Compose,
  Calendar, Subscriptions, and Stats plus mobile Flow, Inbox, Calendar, and
  Compose under the task's `post-deploy/` visualization directory.
- Loaded subscription rows showed high-confidence unsubscribe actions and
  separate review-only rows; unavailable dates rendered as unavailable rather
  than negative relative ages.
- No Alembic revision, Caddy change, systemd change, or database migration is
  part of this release.

### Production Actions

- Pushed the reviewed release to `origin/main`: `07d1110` for the app-wide UX
  implementation, followed by `296aa51`, `db6d883`, and `d0ba84d` for the
  mobile Compose correction discovered during production visual QA.
- Fast-forwarded production from `15ff041` through `d0ba84d`, installed the
  locked dependencies, built the frontend, and restarted only `mailapp` for the
  backend portion. No migration, data mutation, Caddy change, or worker restart
  was required.
- The old Uvicorn process retained one long-lived connection past its 90-second
  stop timeout and systemd terminated that old process before immediately
  starting the new one. The replacement service is active, public health is
  `ok`, all seven checked services are active, and the post-release mailapp
  error log has no entries.
- Rebuilt the static frontend after each visual-QA correction without another
  service restart. Final production Git was clean and aligned with
  `origin/main` at `d0ba84d` before this worklog-only follow-up.
- The parallel Andrea/Angie workflow files remained unstaged and were excluded
  from every release commit.

### Next

Confirm Google Cloud OAuth publishing status as the next separately authorized
work item; if it remains in Testing, publish it and reauthorize affected
accounts once.

## 2026-08-29 — External account authorization diagnosis

### Scope

Determine why connected Google accounts outside `mcchord.net` require
reauthorization after roughly one week and define a durable remediation.

### Findings

- Read-only production health checks passed; application, worker, supporting
  services, and the public health endpoint are healthy.
- Redacted account-health metadata showed three non-primary accounts active but
  failing mail authorization. Their last successful incremental syncs were on
  2026-06-08. The primary `mcchord.net` account synced successfully on
  2026-08-30 UTC.
- The failure pattern matches Google's documented seven-day refresh-token
  lifetime for External OAuth applications in Testing. Workspace trust can
  explain why an organization account is exempt while external accounts are
  not.
- Gmail sync records permanent authorization failures as generic errors and
  retries every five minutes. Calendar has a `needs_reauth` concept, but Gmail
  does not expose equivalent structured state.
- The OAuth callback overwrites an existing stored refresh token with an empty
  value when Google omits a new refresh token. The setup guide also says Testing
  is sufficient without warning that Gmail grants then expire after seven days.

### Verification

- `make remote-status`: production Git clean at `15ff041`; all checked services
  active; public health returned status `ok`.
- Inspected account, OAuth, Gmail sync, calendar sync, worker, and account UI
  paths locally; no focused OAuth or sync tests currently exist.
- Checked current official Google OAuth documentation for Testing, Published,
  and trusted Workspace behavior.

### Production Actions

- Read-only inspection only. No files, services, database rows, credentials,
  Google Cloud settings, or account grants were changed.

### Next

With explicit authorization, move the production Google OAuth app out of
Testing and reauthorize affected accounts once. Then implement structured
account auth health, stop retrying permanent auth failures, preserve refresh
tokens safely, surface a global reconnect action, and add focused tests.

## 2026-08-26 — Staging home base

### Scope

Establish this local folder as the working checkout for `email.mcchord.net` and
add agent guidance, repeatable setup, operations documentation, and a durable
progress system.

### Completed

- Cloned `https://github.com/amcchord/email.git` into the staging folder.
- Inspected the production topology and Git state over read-only SSH commands.
- Added repository-wide working and production-safety rules in `AGENTS.md`.
- Added the workbook, current status, journal, decisions, and operations
  runbook.
- Added a Python/frontend bootstrap, Make targets, and a read-only remote status
  command.
- Added the missing Pillow 12.2.0 pin to `requirements.lock`; it is required by
  `requirements.txt`, the e-ink test suite, and matches the production install.
- Added a deliberately unreachable test database URL so import-time SQLAlchemy
  setup cannot fall through to production configuration.

### Verification

- `make setup`: passed using Python 3.13.15; frontend `npm ci` completed.
- `make test`: 117 tests passed in 3.70 seconds.
- `make frontend-build`: passed (464 modules transformed). Pre-existing Svelte
  accessibility warnings and a large-chunk warning remain.
- Frontend install reported 11 audit advisories: 4 moderate, 6 high, 1
  critical. No automatic audit fix was applied.
- `make remote-status`: live Git clean at `15ff041`; checked services active;
  public health returned `{"status":"ok","version":"1.0.0"}`.
- Shell syntax checks and `git diff --check`: passed.

### Production Actions

- Read-only inspection only. No files, services, database rows, configuration,
  or Git refs were changed on production.

### Next

Select the first feature or operations objective and add it to `CURRENT.md`
with observable acceptance criteria.
