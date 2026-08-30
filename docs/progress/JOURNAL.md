# Progress Journal

Newest entries go first. Keep entries concise and factual. Never include
secrets, email contents, OAuth tokens, or raw private production data.

## 2026-08-30 — Session ownership and shell reliability candidate

### Scope

Make account switching a complete browser privacy boundary, enforce Todo source
ownership, fix the Safari More/Sync blank-page regression, and preserve drafts
during fast navigation while keeping all generated QA read-only with respect to
real mail and calendars.

### Completed

- Added one central authentication generation and synchronous reset for all
  user-derived stores; guarded requests, refreshes, raw streams, realtime,
  polling, timers, delayed continuations, navigation handoffs, and toasts.
- Ordered logout behind in-flight refresh and kept login unavailable until the
  final cookie clear; coalesced duplicate logout attempts.
- Scoped Compose draft and sender storage by user/intent, purged unsafe legacy
  keys, and persisted the latest edit before teardown.
- Made generic Todo creation manual-only, scoped email and analysis lookup
  through account ownership, normalized AI action items, added uniform 404s,
  and added PostgreSQL cleanup/enforcement revision `c0d1e2f3a4b5`.
- Fixed the transparent More/Sync fullscreen close targets in Safari and made
  cancel/failure stop remaining browser-assisted unsubscribe work.
- Added generated two-user, popover, auth-cookie, Todo, request, stream, action,
  draft, realtime, reset, and migration regressions.

### Verification

- Final `make check`: 399 backend passed, 4 opt-in PostgreSQL tests skipped;
  183 frontend passed; 507-module build completed.
- Disposable PostgreSQL 17 upgrade/downgrade/re-upgrade and trigger checks
  passed. Production aggregate preflight found zero Todo rows.
- Generated 1280×720 and exact-375 browser QA passed with delayed User A Todo
  responses released after User B login, no A data/draft in B, transparent
  shell backdrops, no overflow, zero fixture mutations/unknown routes, and zero
  browser warnings/errors.
- Independent backend, generated-QA, and competitive UX reviews approved the
  final candidate after all P0/P1 findings were fixed.

### Production Actions

- At the user's explicit request, promoted exact active
  `austin@mcchord.net` to administrator, initially added the two requested
  external addresses, then widened only trusted organization domains
  `@mcchord.net`, `@casanacare.com`, and `@outsidersfund.com`. Consumer domains
  remain exact-address only. Aggregate verification passed; no restart was
  required and no allowlist value was printed.
- Application deploy, database backup/migration, and post-deploy verification
  remain pending for the candidate.

### Next

Finish final review and aggregate checks, push the exact candidate, take and
validate a fresh database backup, deploy revision `c0d1e2f3a4b5`, and perform
read-only production shell and health verification.

## 2026-08-30 — At a Glance platform release

### Scope

Promote e-ink terminals into an extensible At a Glance platform with 16:9 and
9:16 browser delivery, robust battery guidance, isolated display credentials,
and a safe firmware-management path while preserving the concurrent Calendar
release.

### Completed

- Centralized view, design, profile, device-renderer, and web-renderer
  registration; added exact-size fullscreen HTML/PNG adapters alongside the
  existing BMP protocol.
- Added individually rotatable browser credentials bound to one catalog
  combination, leaving the firmware code and other display links unchanged.
- Added bounded sparse battery history, stale/partial telemetry handling,
  conservative runtime prediction, charge notices, and Admin presentation.
- Promoted the Admin section and documentation to At a Glance, including
  ready-to-open browser display cards and scoped link rotation.
- Documented the inspected firmware baseline and gated path through Web Serial,
  local provisioning, CA validation, per-device trust, signed A/B OTA, staged
  rollout, rollback, and rescue. The dirty firmware checkout was not modified.
- Coordinated with and rebased twice after the Calendar task; both Calendar and
  terminal additions remain present in `docs/api.md`.

### Verification

- Post-final-rebase `make check`: 387 backend passed, 4 opt-in PostgreSQL tests
  skipped, 156 frontend passed, and the 504-module production build completed.
- Focused terminal/display/battery tests: 91 passed. Compile/import lint and
  `git diff --check` passed.
- Disposable PostgreSQL 17 upgrade/downgrade/re-upgrade rehearsal passed for
  both new revisions and verified their tables and indexes.
- Generated browser QA confirmed exact no-overflow 1280×720 and 720×1280
  delivery. Existing artwork was preserved without cropping or distortion.

### Production Actions

- Pushed application `4c5a1fe`, firmware roadmap `1359a24`, and release record
  `c76cb5e` to the feature branch and GitHub `main`, then fast-forwarded clean
  production from Calendar closeout `a2c02bf` to exact `c76cb5e`.
- Created and validated a 1,383,479,646-byte PostgreSQL custom-format backup at
  `/var/backups/mailapp/maildb-pre-at-a-glance-20260830T1503Z.dump`, mode
  `0600`, owner `postgres:postgres`.
- The initial deploy precondition stopped before mutation when root Git lacked
  the required safe-directory flag. The corrected gate reconfirmed the exact
  prior commit and clean tree, then applied both additive Alembic revisions,
  built 506 frontend modules as `mailapp`, and restarted only `mailapp`.
- Post-deploy verification passed: Git is exact and clean, Alembic is
  `b9c0d1e2f3a4 (head)`, both tables and scoped-token indexes exist, public
  health is `ok`, all seven services are active, `mailapp` reports zero
  restarts and zero warning-or-higher entries, and expected public auth/404
  boundaries respond correctly.
- Signed-in production QA showed five individually rotatable browser cards and
  live battery collection/stale states. A 1280×720 Clock page had exact image,
  stage, viewport, and overflow geometry; a query view override could not
  change its token-bound content. No display URL was rotated.

### Next

Close out the docs-only release evidence, then begin the clean firmware
artifact and browser-installer milestone. OTA remains gated on A/B layout,
trusted transport, device authentication, signed manifests, and rollback.

## 2026-08-30 — Calendar state-integrity candidate

### Scope

Remove false-empty, stale-response, account-authority, date-boundary, and
responsive/accessibility ambiguity from Calendar while leaving real mail and
calendars read-only and preserving separately owned terminal/e-ink and AI work.

### Completed

- Added immutable range/account/timezone request identity, cancellation,
  same-key cache refresh, explicit loading/error/retry states, and stale modal
  closure.
- Centralized generation-scoped account authority across polling,
  login/logout, retry, and same-document re-login; removed Sidebar’s competing
  account writer.
- Separated cached Reload from Google Sync, captured submitted sync scope, and
  required all targets to finish or produce honest unconfirmed timeout copy.
- Added connection/freshness coverage states and limited verified-empty claims
  to ranges inside every visible account’s successful full-sync window.
- Corrected API DST/half-open range selection, Google all-day exclusive ends,
  cross-midnight display/geometry, merged counts, event-detail dates, focus
  behavior, mobile views/controls, timezone disclosure, and accessible labels.
- Expanded the generated localhost Calendar harness with immutable accounts,
  events, statuses, boundary/DST/failure/overlap/disconnected cases, a local
  reauthorization sink, and exact read/mutation auditing.

### Verification

- `make check`: 341 backend passed, 4 opt-in PostgreSQL tests skipped, 156
  frontend passed, and the 506-module production build completed.
- Harness syntax, secret scan, and `git diff --check` passed.
- Generated desktop/exact-375 browser QA passed for loading, populated,
  verified and unverified empty, error/retry, slow overlap, disconnected,
  status failure, event dialog, and DST boundary paths. Audit: zero accepted
  mutations and zero unknown routes.
- Independent architecture, competitive UX, and QA rereviews found and then
  verified closure of midnight geometry, account ABA, loading authority,
  coverage-window, and timeout-truthfulness blockers.

### Production Actions

- Pushed application commit `bbf96b3` and release record `b6cfd98` to GitHub
  `main` and `codex/calendar-state-integrity`, then fast-forwarded the clean
  production checkout from `aa91430` to exact `b6cfd98`.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 506-module frontend as `mailapp`, and restarted only `mailapp`.
  The prior process held a long-lived connection during shutdown and the
  restart completed after the initial command window; the replacement process
  is active and clean.
- Post-deploy verification passed: production Git was clean, public health,
  `/`, and the exact Calendar asset returned 200, the Calendar route returned
  the expected unauthenticated 401, all seven services were active, five
  application-edge restart counters were zero, Alembic remained at head, and
  the new `mailapp` process had zero warning-or-higher entries.
- No schema, dependency lock, worker, terminal/e-ink, AI-provider, Caddy/systemd
  configuration, Google grant, production allowlist, mailbox, or calendar data
  changed.

### Next

User-test read-only Calendar navigation, Reload, and event details with real
accounts. Keep Sync and real calendar/mail mutations outside automated QA.

## 2026-08-30 — Google OAuth callback fail-safe candidate

### Scope

Confirm the reported Calendar reauthorization Internal Server Error, protect
all adjacent Google callback exception paths, and preserve the concurrent AI
worktree and real-mail read-only boundary.

### Completed

- Correlated the supplied legacy state window with a redacted production
  `Missing code verifier` traceback that preceded the deployed PKCE release.
- Added typed signed-state validation, complete account/login callback
  exception boundaries, best-effort rollback, class-only redacted logging, and
  cookie-before-commit transaction ordering.
- Added safe handling for known legacy callback query parameters and more
  actionable account/login recovery copy.
- Added an exact legacy-state regression plus generated setup, malformed
  profile, database read, commit, cookie, rollback, and redaction coverage.
- Read-only allowlist matching confirmed the two newly reported external
  addresses are absent; no production configuration changed pending explicit
  confirmation of the exact-address additions.

### Verification

- `make check`: 336 backend passed, 4 opt-in PostgreSQL tests skipped, 135
  frontend passed, and the 504-module production build completed.
- Focused OAuth: 26 passed. `git diff --check`: passed.
- Independent architecture, competitive UX, and QA reviews found and verified
  closure of database/setup and cookie-before-commit blockers.
- Generated exact-375 in-app browser QA passed with an accessible recovery
  notice, cleaned URL, no overflow, zero mutation attempts, zero accepted
  mutations, and zero unknown routes.

### Production Actions

- Pushed application commit `a499d9d` and release record `2877a28` to GitHub
  `main` and `codex/oauth-callback-reliability`, then fast-forwarded the clean
  production checkout from `bf8062b` to exact `2877a28`.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 504-module frontend, and restarted only `mailapp`. The old
  process retained a long-lived connection through its stop timeout and was
  killed by systemd; the replacement started immediately and cleanly.
- Production Git is clean and exact; public health and `/` return 200; an empty
  generated callback returns the sanitized Profile & Accounts 303; all seven
  services are active with zero reported restarts; Alembic remains at head;
  and the new mailapp process has zero warning-or-higher entries, callback
  tracebacks, or missing-verifier traces. A read-only browser shell check also
  passed without inspecting mail content.
- No mail, Google grant, allowlist, schema, dependency lock, worker, TUI,
  Caddy/systemd configuration, or AI file/service changed.

### Next

Add only the two exact requested allowlist entries if confirmed, then use fresh
one-time Google authorization flows.

## 2026-08-30 — Reply-envelope integrity candidate

### Scope

Remove wrong-account and recipient-envelope ambiguity from Inbox and Flow
without touching the concurrent AI-provider worktree or mutating real mail.

### Completed

- Added authoritative account identity and References state to details/thread
  members, plus optional owned-account thread scoping.
- Centralized fail-closed Reply/Reply All derivation, removed first-account
  fallbacks, preserved RFC recipient/threading semantics, and made visible
  From/To/Cc values identical to send/full-compose payloads.
- Added explicit Inbox Reply All, truthful Flow action labels, generation-
  guarded delayed completion, stable hydrated draft keys, unavailable-editor
  suppression, accessible icon controls, and an exact-375 Flow layout repair.
- Added generated second-account/decoy, unknown-source, and Active Thread
  fixtures plus a browser-readable read/mutation audit. Three independent
  reviewers found sender, stale-state, thread-scope, parser, accessibility, and
  mobile blockers; each was fixed before final gating.

### Verification

- `make check` passed: 325 backend tests, 4 opt-in PostgreSQL skips, 132
  frontend tests, and a successful 504-module production build.
- Generated in-app browser desktop/exact-375 QA passed for Inbox, Flow,
  unavailable source, and Active Threads. Audit: zero mutation attempts, zero
  accepted mutations, and zero unknown routes.
- Final architecture, competitive UX, and QA rereviews found no release
  blockers.

### Production Actions

- Committed application release
  `70c67a3b1cde9266c6d6d87e15695d778c198bca`, pushed it to GitHub `main` and
  `codex/reply-envelope-integrity`, and fast-forwarded the clean `/opt/mail`
  checkout to that exact commit.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 504-module frontend as `mailapp`, and restarted only `mailapp`.
  No dependency lock, migration, database data, configuration, Google grant,
  worker, Caddy/systemd, real mailbox, or AI-provider file/service was changed.
- Post-deploy verification passed: production Git was clean and exact, public
  health was `ok`, `/` returned 200, all seven checked services were active,
  five application-edge services reported zero restarts, Alembic remained at
  `z7a8b9c0d1e2 (head)`, the five-minute mailapp warning-or-higher count was
  zero, and a read-only in-app browser shell check loaded `Mail` with one main
  landmark.

### Next

User-test with an explicitly generated multi-recipient conversation; do not
send or mutate real mail. Then continue with the next isolated product slice.

## 2026-08-30 — Google OAuth callback reliability candidate

### Scope

Diagnose and fix the raw Internal Server Error reported after Calendar Google
reauthorization, while preserving the separate AI worktree and using only
redacted production evidence and generated OAuth/browser fixtures.

### Completed

- Redacted production traceback inspection identified a missing PKCE verifier
  at token exchange; no code, token, credential, mail, or raw private log was
  retained.
- Added an explicit shared PKCE flow, encrypted verifier handoff, one-time
  browser nonce, access-cookie-independent callback identity, target-account
  binding, actual-scope and durable-refresh validation, allowlist enforcement,
  sanitized 303 outcomes, and safe Google-login parity.
- Returned Calendar initiators to Calendar, centralized accurate result/error
  notifications and URL cleanup, fixed the nonexistent callback Settings tab,
  and normalized legacy/unknown Settings tabs.
- Added `OAUTH_REAUTHORIZATION_RELEASE_2026-08-30.md`, 15 backend regressions,
  four frontend regressions, and an exact-375 generated browser wrapper.

### Verification

- `make setup` and `make check` passed: 318 backend tests passed, 4 isolated
  PostgreSQL tests skipped, 117 frontend tests passed, and the 503-module
  production frontend built successfully. Npm reported zero vulnerabilities.
- Harness syntax and `git diff --check` passed.
- Generated in-app browser desktop/exact-375 QA showed accurate success and
  account-mismatch notifications on visible Calendar/Profile landings, cleaned
  result parameters, no horizontal overflow, zero mailbox mutations, and zero
  unknown routes.

### Production Actions

- Committed application release `1ded3ccba22b0d300123a080fe25adae77dcc8df`,
  pushed it to GitHub `main` and `codex/oauth-reauthorization`, and
  fast-forwarded the clean `/opt/mail` checkout to that exact commit.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 503-module frontend as `mailapp`, and restarted only `mailapp`.
  No dependency lock, migration, database data, Google grant, configuration,
  Caddy, systemd, worker, mailbox, or AI file/service was changed.
- Post-deploy checks passed: Git was clean and exact, all seven checked services
  were active, five application-edge services reported zero restarts, public
  health was `ok`, `/` returned 200, an empty generated callback returned a
  sanitized 303 landing, and the post-deploy mailapp warning-or-higher count was
  zero.

### Next

Use a fresh Google reauthorization for user testing. Confirm the Calendar
landing and green reconnection notice; do not reuse the failed one-time
authorization code.

## 2026-08-30 — Remote-content privacy controls

### Scope

Block sender-controlled email resources by default across every reader and
quoted Compose path, provide a truthful one-message direct-load control, and
deploy the generated-only validated frontend release for user testing without
touching the separately owned AI worktree.

### Completed

- Added a shared CSP-isolated email frame for Inbox, standalone/subscription,
  and Flow with no-referrer requests, safe parent link handoff, System-aware
  theme updates, scoped approval reset, and accessible privacy announcements.
- Parsed sender HTML inside a CSP-locked detached template before DOMPurify,
  then blocked remote images/media/CSS, pings, stylesheets, same-host resources,
  and broad SVG/MathML references. Direct permission restores only absolute
  external-host HTTP(S) image/media values; CSS, fonts, pings, SVG references,
  active content, and authenticated app requests remain blocked.
- Added deliberate accessible placeholders for blocked/unavailable images and
  hardened Forward/Compose plus both basic and rich editor ingestion.
- Added a deterministic generated mailbox/resource beacon covering mixed,
  embedded, permanently blocked, permission-reset, same-host, Inbox, Flow,
  Forward/Compose, theme, desktop, dark, and exact-375 states. Three parallel
  reviewers handled architecture/security, competitive UX, and final QA; all
  release blockers were fixed before deployment.
- Added `REMOTE_CONTENT_PRIVACY_RELEASE_2026-08-30.md`, three screenshot
  artifacts, a captured request audit, and durable decision D-016.

### Verification

- `make check`: 303 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  113 frontend tests passed, and the 502-module production build completed.
- Harness syntax, audit JSON parsing, and `git diff --check` passed.
- Generated browser QA recorded zero requests before permission; exactly seven
  approved external-host image/media requests afterward, all without referrer;
  and zero mailbox mutations or unknown routes. CSS/SVG/ping/same-host vectors
  stayed blocked, theme changes did not re-request, and A → B → A cleared
  permission.
- Safe embedded raster and permanently-blocked-only states were truthful;
  desktop, exact 375×812, and dark Flow visual reviews passed with 44 px mobile
  controls and no overflow. No real mail was opened or changed.

### Production Actions

- Pushed `9b9730a` to `origin/codex/remote-content-controls` and fast-forwarded
  GitHub `main` from `ee93396` without rewriting history.
- Fast-forwarded clean production `/opt/mail` to exact full commit
  `9b9730a68c65de2b7ee9910c0d2c3bd70939e273` as `mailapp`, ran only the locked
  frontend install and build, and observed zero npm vulnerabilities.
- No database migration/write/backup, Python install, service restart, or
  Caddy/systemd change occurred. Public health, seven active services with zero
  restarts, representative static assets, recent error-level logs, and clean
  Git state all passed. The concurrent AI worktree remained untouched.

### Next

Pause for production user testing. When work resumes, coordinate the existing
AI Markdown-image SSRF follow-up with its owner, then design the owned
remote-resource proxy/manifest and CID mapping as a separate security release.

## 2026-08-30 — Frontend dependency security candidate

### Scope

Refresh the compatible frontend dependency graph in isolation, address
regressions exposed by the upgrades, and prove security-critical rendering,
mobile Chat, editor, and PDF paths using generated data only.

### Completed

- Cleared 11 npm production advisories without force or declared-range changes;
  DOMPurify is 3.4.14, jsPDF 4.2.1, Svelte 5.57.0, Vite 6.4.3, and Rollup
  4.63.1.
- Made email/AI renderers explicitly display-only, fixed duplicate Tiptap Link
  and Underline registration, rebuilt Chat's narrow-screen sidebar/download
  controls, and made PDF cleanup exception-safe.
- Replaced fixed PDF raster cuts with structured heading/block boundaries plus
  whitespace and pixel-inspection fallbacks. Iterative Poppler rendering caught
  and eliminated text, heading, and blockquote page-boundary defects.
- Extended the immutable localhost harness with generated hostile email HTML,
  hostile Chat Markdown, long Unicode PDF content, exact 375 px wrappers, and
  dedicated read/mutation/unknown-route evidence.
- Three parallel agents handled compatible lock implementation, dependency
  reachability/risk review, and generated user testing. Their DOMPurify,
  jsPDF, Linux Node floor, and Tiptap warning findings were resolved.

### Verification

- `make check`: 303 backend passed, 4 opt-in PostgreSQL skipped, 108 frontend
  passed, and the 500-module build completed.
- Clean Linux x86_64 Node 20.20.2 passed `npm ci`, zero-vulnerability audit,
  all frontend tests, and `vite build --manifest`.
- Generated in-app browser desktop/exact-375 QA retained safe content, removed
  all active tags/events/JavaScript URLs, mounted one enhanced editor, met 44
  px Chat controls, and recorded no mutation or unknown-route attempts.
- Final generated PDF: sanitized filename, `%PDF-`, 1,041,576 bytes, four
  letter pages. Poppler page renders passed visual inspection without clipping,
  splitting, overlap, or unreadable Unicode. Harness syntax and
  `git diff --check` passed.

### Production Actions

- Pushed `3f9e743` to `origin/codex/frontend-dependency-security` and
  fast-forwarded GitHub `main` from `413d763` without rewriting history.
- Fast-forwarded clean production `/opt/mail` to exact full commit
  `3f9e743a4027a1c66b8e416bd3b6291a2c0b084b` as `mailapp`, then ran only the
  locked frontend install and 500-module build. The production audit is zero.
- No database backup/migration, Python install, service restart, Caddy/systemd
  change, real-message open, or mailbox mutation occurred. Post-deploy health,
  seven service states, zero restart counts, five representative static assets,
  recent error-level logs, and clean Git state all passed. The concurrent AI
  worktree remains untouched.

### Next

Pause for production user testing. Next, design a deliberate remote-content
and tracking-control policy before changing email image or stylesheet behavior.

## 2026-08-30 — Consolidated product release and deployment

### Scope

Freeze the product-polish work, preserve the separately completed AI-provider
baseline through a normal Git merge, close final editor/reply review blockers,
create a complete change record, and prepare the explicitly authorized
production deployment without reading or mutating real mail.

### Completed

- Merged `origin/main` at `41d2898` into the product branch without rebasing or
  editing the clean AI worktree; code merged automatically and both progress
  histories were preserved through documentation-only conflict resolution.
- Fixed Tiptap content feedback so user edits no longer trigger external
  `setContent` caret resets, while true external changes use the Tiptap v3
  no-update contract.
- Scoped Flow thread, custom-reply, Full Compose, and delayed send behavior to
  captured message/thread/source identity; restored reply drafts; selected the
  newest thread message by display order; and prevented delayed completion
  from clearing or navigating away from newer work.
- Kept editor-load failures in a fully usable, focused basic editor rather than
  reloading and stranding reply context.
- Preserved reply `In-Reply-To`, `References`, and Gmail `threadId` through
  saved Gmail drafts with route and decoded-MIME tests.
- Created `PRODUCT_POLISH_RELEASE_2026-08-30.md` as the complete release,
  safety, validation, deployment, and rollback record.

### Verification

- `make check`: 303 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  108 frontend tests passed, and the 498-module production build completed.
- The final entry is 258.42 kB / 78.51 kB gzip; DeferredRichEditor is 4.83 kB /
  2.23 kB gzip; RichEditor/Tiptap remains a separate 371.52 kB / 117.42 kB
  gzip dynamic asset.
- Generated in-app browser QA verified zero editor requests while reading Flow,
  exact editor JS/CSS loading after writing intent, focused draft continuity,
  typing during a slow enhancement, fully editable fail-once fallback, and a
  375px composer with no horizontal overflow and ten 44x44 toolbar controls.
- Final generated audits recorded zero mutation attempts and zero unknown
  routes. All fixtures used `.example.test` data; no real message was opened or
  changed. `git diff --check` and harness syntax passed.

### Production Actions

- Pushed candidate `834eade` to the product branch and fast-forwarded GitHub
  `main` from `41d2898` without rewriting history.
- Created and validated a 1.38 GB PostgreSQL custom-format backup at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`, mode
  `0600`, owned by `postgres`. The dump was moved out of the checkout after
  verification caught the untracked backup directory; production Git is clean.
- Fast-forwarded `/opt/mail` as `mailapp`, ran the locked frontend install and
  498-module production build, upgraded Alembic transactionally to
  `z7a8b9c0d1e2`, and restarted only `mailapp`, `mailworker`, and
  `mailworker-cron`. Requirements, Caddy, systemd, and TUI were unchanged.
- Verified exact local/origin revision, schema objects, public health `ok`, all
  seven services active, zero service restarts, zero error-level application/
  worker log lines, and HTTP 200 for the eager, deferred-editor, and rich-editor
  assets. No production message was opened or mailbox mutation performed.
- The unchanged npm lockfile reports 11 compatible-fix advisories (4 moderate,
  6 high, 1 critical); record a separate dependency-update cycle rather than
  mixing unverified framework and PDF-library upgrades into this release.

### Next

Pause feature work for user testing. Next, clear the npm audit in an isolated
dependency update with full browser regression, then resume the product queue.

## 2026-08-30 — Resilient route-level frontend splitting

### Scope

Reduce authenticated startup cost and harden feature navigation without
touching the separately owned AI checkout or using real mailbox data.

### Completed

- Replaced eager feature imports with a literal lazy registry for all ten
  authenticated screens and standalone message viewing. Concurrent imports
  deduplicate, successful routes stay warm, rejected imports can recover, and
  generation guards prevent late chunks from replacing newer navigation.
- Added delayed accessible skeletons, assertive failure recovery, runtime
  boundaries, route-ready announcements, document reload for Chromium-cached
  module failures, intent prefetch, canonical deep links, and real browser
  Back/Forward behavior.
- Hardened keyboard and mobile navigation: named focusable main regions,
  focus-if-lost routing, immediate eager-shell search focus, exact More focus
  restoration, current-page semantics including Settings, 44px targets, and a
  short-height scrollable More menu whose backdrop is outside tab/AT order.
- Preserved cross-screen message intent through Inbox's first authoritative
  dataset so a cold Todo/Flow/Insights handoff cannot be erased by selection
  invalidation. Shortcut customization now targets the durable Preferences
  tab rather than a timing-only event.
- Extended the localhost generated harness with route chunk discovery,
  delay/failure/race cases, mobile wrappers, generated Todo-to-message data,
  read-only Admin fixtures, and route/mutation auditing.

### Verification

- `make check`: 293 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  99 frontend tests passed, and the production build completed without the
  prior bootstrap chunk warning. Harness syntax and `git diff --check` passed.
- Entry JS fell from 1,171.80 kB / 343.51 kB gzip to 258.40 kB / 78.50 kB;
  every feature screen and standalone message is a dynamic entry.
- Generated in-app browser QA verified delayed direct-message opening,
  immediate search focus while Inbox still loaded, stale-route suppression,
  503 recovery, direct/invalid URLs, Back/Forward focus, Settings/Preferences,
  More Escape/selection/tab order, and 375x390 scrolling. The final standard
  build's manifest-free fallback recorded only expected route GETs; browser
  logs, mutation attempts, and unknown routes were empty.
- Three independent architecture, UX, and generated-user agents reviewed the
  slice. Their cache-race, focus, current-state, direct-open, recovery, and
  short-height P0/P1 findings were addressed. The concurrent AI checkout
  remained clean and untouched at `41d2898`.
- A final generated-contract audit rendered Preferences, E-Ink Terminals, and
  Data Management with production-shaped payloads and no runtime boundary,
  console error, unknown route, or mutation attempt.

### Production Actions

- None. No deploy, restart, migration, configuration change, production write,
  real-mail read, message open, or mailbox mutation occurred.
- Committed the implementation as `f912410` and pushed it to
  `origin/codex/product-polish-cycle-1` without rebasing or editing the AI
  owner's checkout.
- Committed the generated Admin contract follow-up as `95d13bb` and pushed it
  to the same branch.

### Next

Profile and defer the 369.83 kB / 116.92 kB gzip RichEditor/Tiptap shared chunk
behind explicit writing intent, staying outside files owned by the AI task.

## 2026-08-30 — Safe attachment preview gallery

### Scope

Add modern text, image, and PDF attachment previews plus truthful download-risk
UX using immutable generated mail only, while leaving the separately owned AI
checkout and Chat files untouched.

### Completed

- Added a session-authenticated preview route that reuses the exact owned
  account/email/attachment membership join and canonical byte loader. Known
  oversized metadata fails before retrieval, and a two-slot process admission
  lease covers retrieval through cancellation-draining classification.
- Added byte-derived preview contracts: bounded strict UTF-8 text with safe
  truncation, Pillow-verified JPEG/PNG/WebP normalized to metadata-free bounded
  raster output, and basic PDF signature/tail/obvious-feature checks. PDFs stay
  explicitly untrusted and open in a separate browser-native viewer.
- Added no-store/nosniff/same-origin/sandbox response headers, stable
  404/413/415/503 behavior, client kind/MIME/size agreement, expected-kind
  enforcement, revocable image URLs, and stale request/object cleanup.
- Rebuilt attachment cards and the preview dialog with separate Preview and
  Download actions, safe filenames/type labels, archive/active/MIME mismatch
  cues, runtime-415 confirmation, original-byte-only downloads, three-transfer
  admission, in-dialog download progress, retry/error states, gallery
  navigation, trapped focus, exact focus restoration, inert app background,
  accessible scroll regions, and desktop/full-screen/short-mobile layouts.
- Extended the localhost generated harness with text/image/PDF, active,
  archive, mismatched, corrupt, delayed, retryable, concurrency, original
  download, 375x812, and 375x390 fixtures plus a read/mutation audit.

### Verification

- `make check`: 293 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  91 frontend tests passed, and the production frontend build completed with
  only the existing large-chunk advisory. Fifty-four focused attachment tests,
  Python compilation, harness syntax, and `git diff --check` passed.
- Generated desktop browser QA verified text escaping, normalized image,
  untrusted PDF handoff, unsupported/risky/mismatched/corrupt states, terminal
  415, delayed 499 cancellation without stale UI, 503-to-200 retry, exact
  Escape/Cancel/backdrop focus restoration, focus trapping, command isolation,
  three visible concurrent transfers, in-dialog risky-download progress, and
  authoritative `/download` retrieval. Console errors were empty.
- At 375x812 the dialog exactly filled the viewport with no horizontal
  overflow, an inert app root, a contained image, and five controls at least
  44px tall. At 375x390 the warning body scrolled and the 44px confirmation
  control remained visible. Generated mutation attempts and unknown routes
  were empty.
- Independent backend, frontend, and generated-user agents cleared all final
  P0/P1 findings after fixes for retrieval admission, untrusted PDF wording,
  derivative-download integrity, request identity, status/contrast, modal
  background ownership, and short-viewport scrolling.
- The concurrent AI checkout remained clean and untouched at `41d2898`.

### Production Actions

- None. No deploy, migration, restart, configuration change, production write,
  real-mail read, message open, attachment fetch, or mailbox mutation occurred.
- Committed the implementation as `8fd46a0` and pushed it to
  `origin/codex/product-polish-cycle-1` without rebasing or editing the AI
  owner's checkout.

### Next

Keep the AI-owned Chat attachment path outside the preview/cache guarantee
until coordinated migration. Use route-level frontend bundle splitting as the
next isolated product slice, starting with the current 1.17 MB entry chunk.

## 2026-08-30 — Bounded attachment cache lifecycle

### Scope

Bound received-attachment storage and improve download recovery UX using only
generated mail, while leaving the separately owned AI checkout and Chat files
untouched.

### Completed

- Added an ID-derived per-user cache namespace with 512 MiB hard and 384 MiB
  low-water limits, 30-day idle retention, 24-hour orphan grace, and one-hour
  temporary-file grace. Fresh temporary bytes participate in reservations, and
  uncertain capacity fails closed for caching while downloaded bytes still
  reach the user.
- Added fixed sharded cross-process entry/user locks, cancellation-draining
  blocking-operation wrappers, entry-to-user lock ordering, atomic private
  writes, and no-follow directory-descriptor traversal for reads, scans, and
  inode-checked deletes. Cleanup cannot follow swapped parents or remove an
  in-flight download.
- Added a duplicate-safe daily maintenance loop that inventories canonical
  positive-numeric user roots, uses database ownership snapshots when
  available, preserves orphans on database failure, and reports aggregate
  counts without paths or mailbox content.
- Removed request-session commits and legacy `storage_path` writes from the
  browser download path, bounded Gmail transport and coroutine time, and made
  post-download cache/touch failures nonfatal.
- Added per-file concurrent loading/error state, abort-on-navigation, freshness
  checks before browser save, HTTP-status retry classification, disabled
  terminal chips, accessible alerts/Retry targets, and narrow-screen wrapping.
- Extended the generated localhost harness with delayed abort, repeatable 503
  recovery, terminal 409/413/422 errors, adversarial filenames/details, and a
  read/mutation audit.

### Verification

- `make check`: 267 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  82 frontend tests passed, and the production frontend build completed with
  only the existing large-chunk advisory.
- Forty focused attachment tests passed across quota pressure, retention,
  orphans, temporary files, database outages, cross-process contention,
  cancellation, parent/leaf link swaps, downloader collapse, response mapping,
  and scheduled cleanup. Python compilation, harness syntax, and
  `git diff --check` passed.
- Generated browser QA passed at 1280px desktop and exact 375x812 mobile. The
  narrow page had no horizontal overflow and at least 44px attachment targets;
  long adversarial text stayed contained; 409/413/422 failures were terminal;
  a 503 retried to 200; and navigation aborted a delayed request without stale
  UI. The audit contained no mutation attempts or unknown routes.
- Independent backend and UX agents reported no remaining P0/P1 blocker for
  the canonical browser-download lifecycle. They confirmed that the legacy
  Chat attachment path remains outside this contract and must be migrated with
  its separate AI owner.
- The concurrent AI checkout remained clean and untouched at `41d2898`.

### Production Actions

- None. No deploy, migration, restart, configuration change, production write,
  real-mail read, message open, attachment fetch, or mailbox mutation occurred.
- Committed the implementation as `fe57077` and pushed it to
  `origin/codex/product-polish-cycle-1` without rebasing or editing the AI
  owner's checkout.

### Next

Coordinate the legacy Chat attachment migration after the AI owner releases
those files. Until then, keep its unbounded `storage_path` path explicit as a
release caveat and choose another isolated product slice such as attachment
preview/risk cues or frontend bundle splitting.

## 2026-08-30 — Composable structured email search

### Scope

Replace substring-only Inbox search with a safe, discoverable structured
grammar and modern desktop/mobile result UX, using only immutable generated
mail while leaving the concurrent AI-model checkout untouched.

### Completed

- Added a bounded parser/compiler for implicit AND, OR groups, one-term
  exclusion, exact phrases, and `from`, `to`, `cc`, `bcc`, `subject`,
  `body`, `after`, `before`, `is`, `has`, `in`, `account`, and
  `label` filters.
- Kept the account-ownership predicate independent and immutable, failed closed
  on unknown outer accounts, bound every user value, searched only recipient
  object/string values, made negation NULL-safe, used explicit IANA date
  boundaries, preserved complete literal fallback, and added stable sorting.
- Replaced the placeholder-only search input with an accessible combobox,
  keyboard suggestions, inline grammar alerts, exact 512-character parity,
  removable filter chips, truthful folder scope, retained inert results on
  errors, Retry/Clear/Edit recovery, latest-request guards, and context restore.
- Added list/detail/thread state fields so mixed-folder results render Sent and
  Draft recipients and derive Restore/Not Spam actions from each message.
  Mixed protected-folder selections disable ambiguous Spam/Trash/Archive
  actions instead of applying the wrong operation.
- Coalesced accepted/failed/undone action reconciliation behind the exact
  normalized search dataset. Versioned dirty state keeps actions disabled until
  a non-stale refresh succeeds, including rapid same-message action races and
  repeated refresh failures.
- Added a localhost-only generated search server with exact scenario oracles,
  two accounts, legacy/object recipients, protected folders, date/null/race
  edges, 422/503 responses, mobile wrappers, mutation rejection, and auditing.
- Documented the browser-session search contract and recorded the immutable
  ownership/scope decision.

### Verification

- `make check`: 245 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  79 frontend tests passed, and the production frontend build completed with
  only the existing large-chunk advisory.
- Focused backend search tests passed 30/30; parser/URL/dataset/action/scope
  frontend coverage is included in the 79-test suite. Python compilation,
  harness syntax, SQL compilation review, and `git diff --check` passed.
- Generated browser QA passed on desktop and exact 375x812 mobile wrappers for
  search discovery, keyboard suggestions, Escape behavior, compound filters,
  chips, validation without requests, 422/503 retained-results recovery,
  no-match, account/mailbox restore, responsive touch targets, and no page
  overflow.
- An out-of-order slow/fast pair received slow first but responded fast first;
  the final UI retained only the fast result. Generated Trash, Spam, Sent, and
  mixed-folder scenarios verified truthful scope and recovery controls without
  clicking an action. The final audit had no mutation attempts or unknown
  routes; no message was opened.
- Independent safety and generated-user reviews exercised the flow. Recipient
  JSON keys, OR mailbox scope, action projection/reconciliation races,
  protected-folder controls, and scope-label blockers were corrected; the
  final safety gate reported no remaining P0/P1 issue.
- The concurrent AI checkout remained clean and untouched at `41d2898`.

### Production Actions

- None. No deploy, migration, restart, configuration change, production write,
  real-mail read, message open, or mailbox mutation occurred.
- Committed the implementation as `0e8f8fd` and pushed it to
  `origin/codex/product-polish-cycle-1` without rebasing or touching the
  separately owned AI branch.

### Next

Audit attachment-cache retention, per-user quota, orphan cleanup, and in-flight
download safety as the next isolated slice. Defer saved search/view persistence
until the separate AI owner releases the shared authentication contract.

## 2026-08-30 — Executable command surface

### Scope

Replace informational and ghost shortcuts with a truthful, accessible command
surface while using generated mail only and preserving the concurrent AI
owner's checkout and files.

### Completed

- Added a visible Cmd/Ctrl+K command trigger and deterministic palette that
  exposes only registered commands for the active page, ranks normalized
  queries, reports live disabled reasons, and never executes an unavailable or
  no-match result.
- Added dialog semantics, initial focus, background inerting, scroll lock,
  focus trapping/restoration, configured-key toggle, IME safety, stale async
  session rejection, desktop and bottom-sheet layouts, and equivalent modal
  ownership for the existing shortcut-help dialog.
- Replaced the single shortcut handler slot with stack-safe owned
  registrations and deterministic cleanup. Chat, Flow, and Todos now register
  synchronously, so async loading cannot leak stale page closures after
  navigation.
- Removed advertised no-op commands, registered Subscriptions navigation and
  real Inbox reply/forward actions, corrected Compose and cross-page Search
  navigation, and normalized shifted punctuation and letters.
- Added reentry and promise tracking for Compose/Flow send, Flow Ignore, and
  Todo mutations. Non-idempotent Send remains a direct shortcut but is hidden
  from the palette until a durable lost-response contract exists.
- Reconciled delayed Flow completion against captured email/source identity,
  including navigation to another item or another Flow source and the
  last-needs-reply case, without closing or clearing the newer reply draft.
- Added a localhost-only read-only generated command harness that serves
  immutable `.example.test` fixtures, audits reads, rejects all mutation
  methods, and has no outbound calls.

### Verification

- `make check`: 215 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  58 frontend tests passed, and the production frontend build completed with
  only the existing large-chunk advisory.
- Focused tests cover ranking, context filtering, selection, modal sessions,
  registry ownership, disabled actions, shifted keys, Send palette exclusion,
  per-item pending guards, delayed A/B completion, cross-source draft
  preservation, and last-item reconciliation.
- Generated browser QA passed at 1280x720 and 375x812 for Cmd+K open/toggle,
  filter/no-match behavior, disabled-reason selection, Escape return focus,
  shortcut-help focus/key ownership, Chat/Todos/Flow lifecycle cleanup,
  mobile no-overflow layout, 44px help controls, and focus trapping. Browser
  console errors: none.
- The final generated harness audit contained no mutation attempts and no
  unknown routes. Saved screenshots contain generated content only.
- Independent feature and safety reviews found lifecycle, duplicate-send,
  accessibility, and delayed-mutation blockers; every P0/P1 finding was
  corrected and the final gate was ready.
- Harness syntax, `git diff --check`, and the concurrent AI checkout status
  passed; the AI checkout stayed clean at `41d2898`.

### Production Actions

- None. No deploy, migration, restart, configuration change, production write,
  real-mail read, or mailbox mutation occurred.
- Committed the implementation as `21fcb11` and pushed it to
  `origin/codex/product-polish-cycle-1` without rebasing or touching the
  separately owned AI branch.

### Next

Implement composable structured search against generated fixtures. Coordinate
with the AI owner before changing shared authentication persistence for saved
views or shortcut reset, and add durable client-keyed send idempotency before
making Send palette-executable.

## 2026-08-30 — Durable mail actions and recovery UX

### Scope

Replace best-effort inline Gmail mutations with an honest, durable backend
contract for all current mail actions, using generated fixtures only.

### Completed

- Added an ordered per-email `mail_actions` outbox and
  `emails.mail_action_version`, including ownership/idempotency identity,
  immutable Gmail identity, exact before/after snapshots, label deltas,
  staged undo deadlines, retry/lease state, sanitized errors, timestamps,
  constraints, and worker/query indexes.
- Replaced `POST /api/emails/actions` with strict 1–200 fully owned atomic
  staging and added owned operation status, recent, undo, and retry routes.
- Made repeated idempotency keys return the existing operation and reject
  mismatched payloads; bulk undo is all-or-none and restores exact snapshots.
- Refactored the account advisory lock into a shared helper used by sync and
  action draining. The PostgreSQL drainer claims oldest-per-email due work with
  `SKIP LOCKED`, one-attempt idempotent Gmail label changes, expiring leases,
  bounded backoff, canonical response persistence, partial item results, and
  per-account failure isolation.
- Standardized mutable paths on Email-before-MailAction row locking, bounded
  lease-expiry recovery at the attempt limit, reconciled failed action chains
  without reviving later cancelled intent, and surfaced orphan/credential
  failures as durable operation updates.
- Added a deferred Redis wakeup plus periodic database sweeper so accepted work
  does not depend on Redis delivery.
- Added hard deadlines around mail-action Redis publication/enqueue and a
  finite `httplib2` transport timeout for one-attempt Gmail mutations, so
  post-commit best-effort I/O cannot hold an API response or account lock.
- Added owned idempotency-key lookup for lost create responses and made the
  bounded recent-operation query prioritize unresolved failures.
- Added active-action overlay during sync upsert so Gmail refresh cannot erase
  staged, processing, or retrying local intent.
- Kept a lost create response optimistic and visibly pending, retried with the
  same idempotency key, used an owned lookup as positive evidence only, and
  continued idempotent POST confirmation when a lookup could not find the
  operation. Overlapping actions serialize per email, an uncertain action
  retains its queue position until confirmation, and rollback changes only its
  own label delta.
- Rebuilt normal list rows around separate native select, star, and open
  buttons; added table keyboard activation, 44px mobile/bulk targets,
  responsive bulk layout, and real adjacent-row DOM focus transfer.
- Extended the generated local browser harness to simulate lost responses and
  lost reconciliation lookups without touching Gmail or real mailbox data.
- Documented the browser-session action API and recorded the durable ordering
  decision.

### Verification

- `make check` passed 215 backend tests, 35 frontend tests, and the production
  build with only the existing large-chunk advisory.
- Forty-three generated action tests passed without network, credentials, real
  mailbox data, or production access.
- A disposable PostgreSQL 17 cluster upgraded from the initial schema through
  the new head, downgraded the action revision, and upgraded it again. Four
  opt-in two-session tests passed for concurrent idempotency, strict sequence
  allocation, mixed-ownership atomicity, and claim-versus-Undo races. The
  disposable cluster was stopped and moved to Trash after validation.
- Generated browser QA passed at 1280x720 and 375x844. The narrow page had no
  overflow and 44px list/bulk targets; the deliberately ambiguous response
  state stayed visible until idempotent POST confirmation; desktop keyboard
  archive moved DOM focus to the adjacent message. Saved screenshots contain
  generated content only. Browser console errors: none.
- Python compilation, harness syntax, and `git diff --check` passed.

### Production Actions

- None. No deploy, production migration, service restart, production write, or
  real mailbox action was performed. The original AI checkout remained clean
  and untouched.
- Committed the durable backend as `ee4fa19` and the ordered recovery and
  accessibility frontend as `a41a90d`; both were pushed to
  `origin/codex/product-polish-cycle-1` without rebasing over the AI work.

### Next

Preserve this isolated pushed branch without rebasing over the separately owned
AI-provider work. Coordinate the shared worker registry before merge, then
repeat checks and deployment preflight only if deployment is explicitly asked.

## 2026-08-30 — Product safety cycle 2

### Scope

Complete received-attachment download and make Gmail synchronization lossless
without overlapping the concurrent AI-model task or mutating real mail.

### Completed

- Added a session-authenticated attachment route with a single ownership join,
  bounded Gmail retrieval, size/length validation, per-user canonical caching,
  atomic private writes, and safe response headers.
- Added accessible attachment loading, success, error, and retry behavior with
  stale/duplicate request suppression and safe client filenames.
- Replaced partial-success Gmail sync semantics with strict requested-ID
  completeness and fail-fast parse/upsert behavior.
- Serialized full and incremental sync per account with a PostgreSQL
  transaction advisory lock while retaining compare-and-swap as the final
  checkpoint guard.
- Added versioned full-sync checkpoints carrying a pinned Gmail baseline plus
  scan/replay phase. Full scans now refresh existing rows, replay all changes
  since the baseline, and atomically commit replayed mail, the authoritative
  high-water, completion state, and checkpoint removal.
- Added safe recovery for legacy/invalid checkpoints and expired history
  baselines without surrendering checkpoint ownership.

### Verification

- `make check`: 172 backend tests and 10 frontend tests passed; the production
  frontend build passed with only the existing large-chunk advisory.
- Twenty-three generated sync tests passed across partial/malformed batches,
  processing rollback/retry, monotonic high-waters, advisory-lock contention,
  stale CAS owners, legacy recovery, existing-message refresh, replay
  update/delete, expired baselines, and atomic completion.
- Generated browser QA passed for attachment table/mobile layouts, accessible
  loading and full filename labels, failure with retry, and successful download.
- Independent final sync review reported no blocking findings.
- Python compilation and `git diff --check`: passed.

### Production Actions

- None. No deploy, restart, migration, production write, or real mailbox action
  was performed.
- Pushed `ba903b5` and `ae36211` to
  `origin/codex/product-polish-cycle-1`; did not push or merge `main`.
- The original checkout and all concurrent AI-model work remained untouched.

### Next

Implement a durable mutation reconciliation/undo outbox, then add disposable
PostgreSQL interleaving tests and account-scoped Gmail message uniqueness as
separate focused changes.

## 2026-08-30 — Product safety cycle 1

### Scope

Audit the current mail client against modern email workflows, then implement
the highest-confidence safety improvements without overlapping the concurrent
AI-model task or mutating real mail.

### Completed

- Created a separate product-polish worktree and kept all AI-model files owned
  by the other active process untouched.
- Added an ownership check to account sync-status reads so foreign and missing
  account IDs both return 404.
- Made Inbox results authoritative per mailbox, account, search, smart filter,
  focused mode, page size, request generation, and component lifetime.
- Invalidated selection and disabled actions while replacement results load;
  late list/detail responses can no longer overwrite or authorize the active
  dataset.
- Added persistent update and retry feedback, direct-open action validation,
  infinite-scroll rollback after failure, and a compact mobile fallback for a
  saved desktop table preference.
- Added frontend safety tests to `make check`.
- Completed read-only feature, UX, and safety audits. The next prioritized
  slices are attachment download, mutation reconciliation/undo, incremental
  sync checkpoint safety, and a command/search surface.

### Verification

- `make check`: 131 backend tests passed, 6 frontend safety tests passed, and
  the production frontend build passed with only the existing large-chunk
  advisory.
- Browser QA and independent synthetic user testing passed at 1440×900 and
  390×844 across column/table preferences, rapid mailbox/search changes,
  component recreation, loading feedback, and selection/action invalidation.
- Browser console errors: none. The generated mock API recorded zero actions.
- `git diff --check`: passed.

### Production Actions

- None. `make remote-status` was read-only and reported production clean at
  `0500d1a`, all checked services active, and public health `ok`.
- Pushed `c3fb912` and `278dfef` to
  `origin/codex/product-polish-cycle-1`; did not push or merge `main` and did
  not deploy.

### Next

Implement authenticated received-attachment download with generated fixtures
and browser verification, continuing to isolate all AI-model work.
## 2026-08-29 — OpenAI GPT-5.6 and Anthropic Claude 5 support

### Scope

Add provider-neutral model selection and reasoning-effort controls using the
project credentials available through AustinLand, with workload-specific
defaults for quality, speed, and cost.

### Completed

- Registered GPT-5.6 Sol, Terra, and Luna plus Claude Fable 5, Opus 5, and
  Sonnet 5 with provider, effort, label, and workload-compatibility metadata.
- Set balanced defaults: Terra/medium planning, Luna/low parallel execution and
  email processing, Sol/high final verification, Terra/medium custom replies,
  and Sonnet 5/medium Computer Use unsubscribe.
- Added OpenAI Responses API support for text, structured tools, and the
  plan/execute/verify loop; upgraded Claude 5 calls to adaptive
  `output_config.effort` and retained Claude-only Computer Use routing.
- Carried model and effort through routers, worker jobs, bundles, briefings,
  dashboard snippets, and user preferences, including retired-model fallback
  and model/effort validation.
- Added model and effort controls to Settings, OpenAI setup/configuration,
  provider-neutral documentation, the OpenAI SDK dependency, and a regenerated
  Python 3.13 lockfile.
- Added focused provider-registry, validation, fallback, OpenAI request-shape,
  and Anthropic request-shape tests.

### Verification

- `make check`: 136 tests passed and the frontend production build completed;
  the existing large JavaScript chunk advisory remains.
- Python bytecode compilation and `git diff --check`: passed.
- AustinLand created the idempotent `Email-openai` project-scoped entry and
  recorded the shared `Email-anthropic` assignment. No secret value was
  printed, persisted in this checkout, or recorded in the workbook.
- Live provider catalog retrieval found all six requested model IDs. Minimal
  smoke calls returned the requested response from GPT-5.6 Luna with `none`
  effort and Claude Sonnet 5 with `low` effort. Both provider adapters passed a
  forced structured-tool call, and the OpenAI stateless tool-result
  continuation used by the chat executor also passed.

### Production Actions

- Committed and pushed application release `40bbc48`, then fast-forwarded the
  clean production checkout from `0500d1a` to that exact commit as `mailapp`.
- Provisioned the scoped AustinLand entries into `/opt/mail/.env` through an
  in-memory transfer, after creating protected backup
  `/opt/mail/.env.pre-ai-models-20260830T025842Z`; the resulting file remained
  mode `0600`. No key value appeared in Git, command output, logs, or docs.
- Installed `requirements.lock` (adding OpenAI 2.54.0), ran `npm ci`, rebuilt
  the frontend, and restarted only `mailapp`, `mailworker`, and
  `mailworker-cron`. The API restart spent about one minute draining the prior
  long-lived connection and then completed successfully.
- No Alembic revision, database backup or migration, Caddy/systemd change,
  TUI restart, or mailbox-data mutation was required.
- Verified the production application adapter directly against GPT-5.6
  Terra/medium, Luna/low, and Sol/high; all three returned the expected
  response. Public health was `ok`, all seven services were active, the new
  frontend model controls were present, and the post-restart API/worker
  error-level journal count was zero.

### Next

The requested provider expansion is complete in production. Resume the
separately scoped Google OAuth publishing-status work when authorized.

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
