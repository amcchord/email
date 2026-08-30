# Progress Journal

Newest entries go first. Keep entries concise and factual. Never include
secrets, email contents, OAuth tokens, or raw private production data.

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
- Added three tests covering attachment MIME construction, invalid attachment
  data, and header-newline stripping.
- `git diff --check`: passed before release review.
- No Alembic revision, Caddy change, systemd change, or database migration is
  part of this release.

### Production Actions

- Deployment was explicitly authorized and is pending the reviewed Git commit.
- The parallel Andrea/Angie workflow task remains unstaged and is excluded from
  this release.

### Next

Push the exact reviewed commit, fast-forward production, rebuild the frontend,
restart only the API service, and verify health, logs, and desktop/mobile UI.

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
