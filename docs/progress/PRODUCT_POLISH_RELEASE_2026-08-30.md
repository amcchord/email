# Product Polish Release — 2026-08-30

This document records the complete user-facing, reliability, security,
performance, testing, and operational delta prepared for the 2026-08-30
production user-testing release. It describes the consolidated release from
the previously deployed production baseline `41d2898` through the final
product-polish candidate. Exact deployed revision and verification evidence are
recorded in the final section after deployment.

## Release Intent and Safety Boundary

- Improve the application toward a fast, keyboard-first, trustworthy modern
  email client while preserving account ownership and mailbox privacy.
- Keep the concurrent AI-provider work isolated during development, then merge
  its already-reviewed Git history into the release rather than editing or
  overwriting that worktree.
- Use generated `.example.test` messages for UI, race, failure, attachment, and
  mutation-path testing. The localhost QA servers reject all mutation methods.
- Do not open, send, archive, delete, label, or otherwise mutate real
  production email during verification. Production checks are limited to the
  exact revision, schema, services, public health, delivered assets, and safe
  shell paths.

## Reliable Synchronization

- Gmail sync is serialized per account with PostgreSQL transaction advisory
  locks shared by full sync, incremental sync, and mail-action execution.
- History and page checkpoints advance only after every item in the owned unit
  is resolved. Missing batch results, malformed responses, and poison messages
  fail the unit and retain its retry point.
- Full sync captures a versioned baseline, refreshes existing messages, replays
  changes since that baseline, and uses compare-and-swap ownership before
  publishing completion.
- Stale checkpoint owners, expired baselines, Gmail updates/deletes during a
  full scan, and overlapping jobs are covered by focused unit and opt-in
  two-session PostgreSQL tests.
- Sync-status reads now enforce authenticated account ownership and fail
  closed for foreign or missing account IDs.

## Durable Mail Actions and Undo

- Archive, trash, spam, read/unread, star, importance, label, and related
  supported actions now create ordered PostgreSQL outbox work in the same
  transaction as the optimistic local projection.
- One durable item is recorded per target email. Per-email ordering prevents a
  newer opposite action from overtaking an ambiguous or retrying request.
- Client idempotency keys, owned lookup, bounded Redis publication, bounded
  Gmail transport time, reclaimable leases, retry state, and persistent
  failures make accepted work recoverable across lost responses and process
  restarts.
- Exact staged Undo is available before execution. Partial bulk failures restore
  only failed rows and retain visible, actionable status.
- Inbox list/table removal, adjacent-row focus transfer, queue-position
  preservation, retry/confirmation messaging, and compact mobile recovery are
  included.
- Sync overlays the latest active outbox projection so remote refreshes do not
  erase accepted local intent while an action is pending.
- The additive Alembic revision
  `z7a8b9c0d1e2_add_durable_mail_actions.py` creates the durable action table,
  indexes, constraints, and reconciliation state required by this workflow.

## Fast, Truthful Inbox State

- Inbox results are authoritative for the complete mailbox/account/search/
  smart-filter/focused-mode/page-size request identity and component lifetime.
- Superseded list and message-detail responses cannot overwrite the active
  dataset, selection, or action target.
- Selection is invalidated and actions are disabled while replacement results
  load. Infinite-scroll failures restore the previous cursor and provide an
  explicit retry path.
- Direct-open actions validate that the target still belongs to the active
  result set. Narrow screens fall back from an unsuitable saved table
  preference to a usable compact list.
- List and table actions are keyboard operable; primary mobile row and bulk
  controls meet the 44-pixel target used by the generated audits.

## Structured Search

- Search supports quoted phrases, exclusions, AND clauses, OR groups, sender,
  recipient, subject/body, before/after dates, state, folder, account, and
  label filters.
- Parsing produces stable local feedback, accessible suggestions, and
  removable filter chips. Malformed backend requests return stable 422
  details without discarding the last successful results.
- All values compile as bound parameters. Account scope is enforced separately
  and immutably so search syntax cannot broaden access to another account.
- Folder semantics are explicit: normal mail is the default; Spam, Trash, Sent,
  and mixed-folder views expose only truthful actions and recipient/sender
  presentation.
- Clearing browser search restores the prior mailbox and filter stores rather
  than silently resetting the user's context.

## Command Palette and Keyboard Workflow

- A keyboard-first command palette now ranks commands deterministically from
  the shortcut catalog and the handlers registered by the active screen.
- Commands expose live enabled state and a human-readable unavailable reason;
  disabled commands remain discoverable but cannot execute.
- The palette and shortcut-help dialog own focus and keyboard events, restore
  the exact opener on close, handle async completion within the originating
  session, and remain contained at 375-pixel width.
- Navigation, search, Inbox reply/forward, Flow, Todo, Chat, Settings, and help
  registrations clean up with their owning screen so stale commands cannot run.
- Irreversible Send is deliberately excluded until it has a durable
  client-keyed lost-response contract.
- Toast feedback became an accessible actionable queue with keyboard Undo and
  persistent failure recovery.

## Attachments: Download, Cache, and Preview

- Received-attachment download requires authenticated ownership of the
  email/account/attachment membership and uses bounded Gmail retrieval.
- Response headers, filenames, cancellation, and retry behavior are hardened;
  sender-supplied paths and persisted `storage_path` values never select the
  canonical browser cache path.
- Canonical caching uses positive database IDs under a per-user namespace,
  fixed sharded cross-process locks, no-follow directory-descriptor I/O, and
  cancellation-safe temporary writes.
- Policy limits are 512 MiB hard capacity, 384 MiB low-water target, 30-day
  idle retention, 24-hour orphan grace, and one-hour temporary-file grace.
  Daily duplicate-safe cleanup reports aggregates rather than private paths.
- Preview shares the same ownership and canonical byte-loading boundary, then
  classifies a bounded renderer kind from bytes rather than trusting filename
  or MIME metadata.
- Images are normalized with metadata removed; text is inert and bounded; PDF
  is explicitly untrusted and opens in a separate native viewer after basic
  checks. Archive, active-file, type-mismatch, corrupt, capacity, and runtime
  failure states provide accurate warnings and confirmation.
- Preview and Download remain separate: Download always returns canonical
  original bytes, never a derivative.
- Desktop, narrow, and short-height galleries include focus trapping, exact
  focus restoration, app-root inertness, contained filenames, visible progress,
  and bounded simultaneous transfers.

## Frontend Loading and Navigation Performance

- The eager application shell retains authentication, global navigation,
  search, toasts, and recovery while all ten authenticated feature screens and
  standalone message viewing load through a literal allowlisted route registry.
- Imports are deduplicated, successful current modules are cached, failed
  imports are retryable, and superseded route results are discarded.
- Loading and failure states are accessible; route changes use real browser
  history and canonical query parameters. Back/Forward, deep links, invalid
  routes, cross-screen message intent, and focus recovery are covered.
- The main entry fell from roughly 1.17 MB minified / 343.5 kB gzip to about
  258 kB / 78.5 kB gzip before the final merge; feature screens are dynamic
  assets instead of bootstrap dependencies.
- Chromium module-load recovery preserves the canonical URL before a document
  reload. Mobile navigation and the More menu remain scrollable with 44-pixel
  targets.

## Writing Experience and Deferred Rich Editor

- Compose, Reply, and Forward render an immediately usable basic editor and
  dynamically import Tiptap only after writing intent; reading routes do not
  request the large rich-editor runtime.
- Concurrent editor imports share one request, successful imports are cached,
  failures are evicted from the application cache, and older failed attempts
  cannot evict a newer successful load.
- Basic-editor content, selection intent, and draft identity survive the rich
  enhancement. Enhancement failure leaves the basic editor usable rather than
  reloading the page or discarding reply context.
- Rich-editor updates distinguish user input from external content changes,
  avoiding feedback loops, repeated `setContent`, and caret churn.
- Writing controls include labels, pressed state, keyboard semantics, and
  mobile-sized targets.
- Local draft identity distinguishes new messages, replies, and forwards;
  synchronous page-exit persistence captures the latest editor content and
  warns when attachments cannot survive reload.
- Flow thread loading and reply/custom-reply completions are request-scoped so
  delayed work cannot overwrite or clear a newer selected message or its draft.
- Reply drafts retain `In-Reply-To` and `References` metadata through Gmail
  draft creation, preserving the intended thread when the saved draft is sent.
- Full Compose is gated while the thread is loading and derives the newest
  message from the active thread sort order instead of assuming the last array
  element is newest.
- Escape closes Compose while keeping the draft. Send remains guarded against
  duplicate in-flight submission.

## AI Provider Baseline Preserved

- The release retains the already-deployed provider-neutral registry for GPT-5.6
  Sol, Terra, and Luna plus Claude Fable 5, Opus 5, and Sonnet 5.
- Model capability, supported effort, workload compatibility, defaults,
  fallback, router/worker propagation, Settings controls, and provider request
  adapters remain exactly in the independently reviewed `origin/main` history.
- The product release does not copy secrets or modify the separate AI worktree.

## Generated QA and Test Coverage

- Localhost-only generated servers cover Inbox actions, structured search,
  command discovery, route loading, attachment download/preview, and deferred
  editor behavior with immutable `.example.test` fixtures.
- Mutation methods are rejected and audits record mutation attempts, unknown
  routes, asset requests, failure injection, and request ordering.
- Scenarios include cold and cached loads, 1.2-second delays, fail-once recovery,
  stale responses, cancellation, Back/Forward, direct links, exact keyboard
  focus, 1280-pixel desktop, 375-pixel mobile, and short-height layouts.
- Unit coverage was added for sync ownership/checkpoints, outbox state and
  two-session races, search parsing and API payloads, attachment caching and
  classification, command registration/ranking, route and editor import state,
  draft identity, toast queues, row focus, stale datasets, and provider models.
- Final verification results and screenshots are recorded below after the
  complete consolidated candidate has passed.

## Deployment and Rollback

- Deployment was a Git fast-forward from clean production `41d2898` to the
  exact pushed application revision `834eade`.
- Before Alembic runs, create a protected PostgreSQL custom-format backup and
  verify that it is non-empty. Do not print database credentials or private
  content.
- Install locked frontend dependencies, build production assets, run
  `alembic upgrade head`, and restart only `mailapp`, `mailworker`, and
  `mailworker-cron`; Caddy and TUI are unaffected.
- Verify exact Git and Alembic revisions, public `/api/health`, service state,
  recent error-level logs, and the delivered frontend asset map.
- Code rollback returns the application to `41d2898` while leaving the additive
  durable-action schema in place. A schema downgrade is unnecessary for that
  rollback and would require a separate data-impact review.

## Final Release Evidence

- Application release: `834eade9e1512ab2bd7a4a4c5c62d80eb5469640`
- Release branch and GitHub `main`: pushed at `834eade`
- Production application revision: `834eade`; a docs-only closeout commit
  follows it with no runtime delta
- Database backup: validated custom-format dump at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`,
  1,383,261,148 bytes, mode `0600`, owner `postgres:postgres`
- Alembic revision: `z7a8b9c0d1e2 (head)`; required table and email version
  column confirmed
- Local checks: `make check` passed with 303 backend tests, 4 opt-in PostgreSQL
  skips, 108 frontend tests, and a successful 498-module production build.
- Bundle evidence: 258.42 kB / 78.51 kB gzip eager entry; 4.83 kB / 2.23 kB
  gzip deferred-editor wrapper; 371.52 kB / 117.42 kB gzip dynamic rich editor.
- Generated browser and screenshots: passed for desktop reading/writing, typed
  slow enhancement, editable fail-once fallback, and exact 375px composition.
  Reading made zero editor requests; writing requested exactly the identified
  editor JS/CSS; mutation attempts and unknown routes remained empty.
- Production health and service verification: public health `ok`; `mailapp`,
  `mailworker`, `mailworker-cron`, `mailtui`, Caddy, PostgreSQL, and Redis all
  active; affected services report zero restarts and successful main status;
  zero error-level application/worker log lines since deployment; eager,
  deferred-editor, and rich-editor assets each returned HTTP 200.
- Dependency follow-up: the package manifest and lockfile were unchanged by
  this release except for the frontend test script, but `npm audit --omit=dev`
  reports 11 existing compatible-fix advisories (4 moderate, 6 high, 1
  critical). Update DOMPurify, jsPDF, Svelte, Vite, and affected transitive
  dependencies in an isolated, fully regression-tested follow-up.
