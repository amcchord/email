# Decisions

Durable decisions are numbered and never silently removed. If a choice changes,
add a new entry that explicitly supersedes the old one.

## D-001 — Git-first staging workflow

- Date: 2026-08-26
- Status: accepted
- Decision: Use this local checkout for development and `origin/main` as the
  code source of truth. Use `/opt/mail` only as the production deployment
  target.
- Reason: Keeps review, testing, history, and recovery available while avoiding
  configuration drift from direct server edits.
- Consequence: Emergency live changes must be reconciled back into Git
  immediately.

## D-002 — Production mutations require explicit scope

- Date: 2026-08-26
- Status: accepted
- Decision: Read-only production inspection may support normal work. Deploys,
  restarts, migrations, configuration edits, and data changes require an
  explicit request in the current task.
- Reason: The host is actively processing private mail and root SSH access has a
  large blast radius.
- Consequence: Completing a local change does not imply deploying it.

## D-003 — Progress lives beside the code

- Date: 2026-08-26
- Status: accepted
- Decision: Keep current state, session evidence, durable decisions, and the
  operations runbook in version-controlled Markdown.
- Reason: Future work should resume from repository state rather than private
  chat history.
- Consequence: Material sessions update `CURRENT.md` and `JOURNAL.md`; durable
  choices update this file.

## D-004 — Never mirror production secrets into staging

- Date: 2026-08-26
- Status: accepted
- Decision: Do not copy `/opt/mail/.env`, databases, mailbox content,
  attachments, OAuth tokens, or private logs into the staging checkout.
- Reason: The local workspace is a code and documentation home base, not a
  production data replica.
- Consequence: Local integration work uses fakes or separately provisioned
  non-production credentials.

## D-005 — Treat known working relationships as routing data

- Date: 2026-08-29
- Status: accepted
- Decision: Encode Andrea Durbin as Austin's default scheduling owner and Angie
  Mecham as a trusted close colleague in a single workflow-context module used
  by prompts, presentation, and mail queues.
- Reason: Free-form LLM inference is not reliable enough for stable delegation
  and trusted-sender behavior, especially when Andrea is included on Cc.
- Consequence: Routine low/normal-priority scheduling already routed to Andrea
  does not become Austin's action item or follow-up; high/urgent messages still
  surface, direct questions from Andrea remain Austin's responsibility, and
  future relationship changes should be made in the centralized workflow
  context rather than scattered prompt text.

## D-006 — Synchronization checkpoints represent complete work

- Date: 2026-08-30
- Status: accepted
- Decision: Serialize Gmail sync per account and advance a history or page
  checkpoint only after every item in its unit is resolved. Full sync owns a
  versioned baseline through scan and history replay; incremental and full
  completion use compare-and-swap as the final ownership guard.
- Reason: Partial batch results, swallowed message failures, or overlapping
  workers can otherwise move a checkpoint beyond mail that was never stored.
- Consequence: Missing batch results and poison messages fail the unit and pin
  its checkpoint for retry. Full sync refreshes existing messages and replays
  changes since its captured baseline before publishing completion. Future
  sync changes must preserve these invariants and add real-database
  interleaving coverage when they alter ownership or transaction boundaries.

## D-007 — Accepted mail actions are durable, ordered work

- Date: 2026-08-30
- Status: accepted
- Decision: Record one ordered outbox item per target email in the same
  transaction as its optimistic local projection. Gmail execution and sync use
  one shared account advisory lock; Redis may accelerate work but PostgreSQL is
  the recovery source of truth.
- Reason: Inline best-effort Gmail calls can partially succeed, be lost after a
  process failure, execute opposite actions out of order, and let sync erase
  user intent while still reporting success.
- Consequence: API acceptance is distinct from Gmail confirmation. Clients use
  request status for partial results, exact staged Undo is permitted only
  before execution, retries preserve per-email order, expired leases are
  reclaimable, and sync must overlay the newest active action state. Redis
  publication is bounded best effort, lost create responses are reconciled by
  owned idempotency-key lookup, and one-attempt Gmail mutations use a finite
  transport deadline before durable retry policy takes over.

## D-008 — Command discovery reflects executable state

- Date: 2026-08-30
- Status: accepted
- Decision: Build command discovery from the active shortcut catalog plus the
  currently registered page/component handlers. Surface live unavailable
  reasons, make command/help dialogs own focus and keyboard input, and exclude
  irreversible Send from the palette until send has a durable client-keyed
  idempotency contract.
- Reason: A palette that advertises no-op, stale, unavailable, or ambiguous
  irreversible actions is less trustworthy than direct shortcuts and can
  duplicate real-world side effects after lost responses.
- Consequence: Page handlers register synchronously with owned cleanup and may
  provide `isEnabled` and `disabledReason`; disabled commands remain
  discoverable but Enter-inert; async completion is scoped to its originating
  palette session and captured entity; and new irreversible palette commands
  require deterministic lost-response coverage before exposure.

## D-009 — Email search is composable inside an immutable ownership boundary

- Date: 2026-08-30
- Status: accepted
- Decision: Parse structured search into AND clauses and OR groups, compile all
  user values as bound parameters, and apply the resulting predicate only
  inside a separately enforced set of accounts owned by the current user.
  Browser search covers regular mail by default, preserves explicit account
  scope, suspends Focused/smart filters, and lets a positive `in:` clause own
  mailbox scope without broadening other OR branches into Spam or Trash.
- Reason: Modern-client search needs quotes, exclusions, fields, dates, and
  mailbox composition, but malformed syntax, foreign account IDs, interpolated
  JSONB values, or ambiguous filter inheritance must never broaden private-mail
  access or misrepresent result scope.
- Consequence: Unknown/foreign outer accounts fail closed; `account:` and
  `label:` only narrow owned mail; date boundaries use an explicit IANA zone;
  parser errors return stable 422 details; plain search retains complete
  literal fallbacks when full-text vectors are stale; and clearing browser
  search restores the unchanged mailbox and filter stores.

## D-010 — Canonical attachment caching is bounded and ID-derived

- Date: 2026-08-30
- Status: accepted
- Decision: Cache browser-downloaded received attachments only at canonical
  positive-ID-derived paths under a per-user namespace. Enforce a 512 MiB hard
  limit with a 384 MiB low-water target, 30-day idle retention, 24-hour orphan
  grace, and one-hour temporary-file grace using fixed sharded file locks,
  no-follow directory-descriptor operations, and duplicate-safe daily
  maintenance.
- Reason: Persisted `storage_path` values, unbounded filenames, path-based
  cleanup, and process-local coordination cannot prove cross-user isolation,
  quota compliance, or in-flight safety under concurrent workers and
  cancellation.
- Consequence: The browser download handler derives identity from owned
  database IDs, never trusts or mutates `Attachment.storage_path`, counts fresh
  temporary bytes before writes, and skips caching whenever a stable capacity
  proof or lease is unavailable while still returning verified downloaded
  bytes. Cleanup uses database ownership only when its snapshot succeeds and
  reports aggregates rather than cache paths. The separately owned legacy Chat
  attachment path is explicitly excluded until a coordinated migration brings
  it into this namespace and policy.

## D-011 — Attachment previews are typed derivatives, not trust proofs

- Date: 2026-08-30
- Status: accepted
- Decision: Expose received-attachment previews only through the same owned
  membership and canonical byte-loading boundary as downloads. Derive a
  bounded renderer kind from bytes, normalize raster/text output, require the
  client kind and content type to agree, and treat every preview as untrusted.
  PDF preview performs only basic checks and opens in a separate browser-native
  viewer; it is never described as structurally safe or malware-scanned.
- Reason: Sender filenames and MIME metadata are attacker-controlled, preview
  derivatives can be truncated or transformed, and raw PDF feature scans are
  bypassable. Reusing a derivative for Download can silently corrupt user data,
  while unbounded classification can exhaust process memory or CPU.
- Consequence: Preview and Download remain separate requests; Download always
  returns canonical original bytes. Active/archive/mismatched metadata and
  runtime type failures require confirmation, images/text use inert renderers,
  PDF bytes remain untrusted, and a process admission lease spans retrieval
  through classification. The AI-owned legacy Chat attachment path is outside
  this contract until separately coordinated.

## D-012 — Feature routes load behind a stale-safe shell boundary

- Date: 2026-08-30
- Status: accepted
- Decision: Keep authentication, global navigation, search, toasts, and route
  recovery in the eager shell while loading every feature screen through a
  literal allowlisted registry. Deduplicate concurrent imports, cache only the
  current successful request, discard superseded route results, and use real
  browser history with canonical per-route query parameters.
- Reason: A single 1.17 MB entry delays every mailbox visit, while ad hoc
  dynamic imports can expose stale screens, inert navigation, unrecoverable
  cached module failures, lost focus, and timing-dependent cross-screen intent.
- Consequence: New feature routes must register a stable key/label/import,
  expose accessible loading and error behavior, and pass cold, failed, stale,
  Back/Forward, focus, and narrow-screen QA. Shell controls may prefetch intent
  but must remain useful while chunks load. Route changes focus the named main
  region only when the previous focus was removed; Chromium module-load errors
  recover by preserving the canonical URL and reloading the document.
