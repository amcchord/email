# Progress Journal

Newest entries go first. Keep entries concise and factual. Never include
secrets, email contents, OAuth tokens, or raw private production data.

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
