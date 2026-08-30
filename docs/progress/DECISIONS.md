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

## D-006 — Select AI model and effort by workload

- Date: 2026-08-29
- Status: accepted
- Decision: Keep provider, model capability, compatible effort levels, and
  per-workload defaults in one registry. Use GPT-5.6 Terra/medium for planning,
  Luna/low for parallel and bulk work, Sol/high for final verification,
  Terra/medium for custom replies, and Claude Sonnet 5/medium for unsubscribe.
- Reason: Planning, parallel retrieval, final synthesis, bulk triage, and
  browser automation have different quality, latency, cost, and protocol needs.
- Consequence: New model families must declare their provider, effort support,
  and workload compatibility in the registry. Unsubscribe remains Claude-only
  until its Computer Use loop has an explicitly implemented provider adapter;
  retired or incompatible stored preferences fall back to the full default
  model/effort pair.
