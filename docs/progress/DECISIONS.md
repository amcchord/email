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
