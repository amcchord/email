# Trainable Focused/Other Rules Release — 2026-08-31

## Outcome

Split Inbox now lets a user explicitly teach one connected account that an
exact conversation, sender, or domain belongs in Focused or Other. The winning
instruction is visible on the row, can be edited, disabled, or deleted in the
Rules manager, and can be undone immediately after a save.

This is a private local display rule. It does not move, archive, label, send,
or otherwise mutate Gmail mail; it does not call AI, read or write Calendar,
enqueue a worker job, or change terminal state.

## Contract

- Candidate identity is derived by the server from a current authoritative
  synchronized Inbox anchor owned by the active user and exact account. Raw
  provider thread/message selectors never leave the server.
- Enabled precedence is exact conversation, exact normalized sender, exact
  domain, then the existing deterministic system placement. A domain never
  implies its subdomains.
- The winning rule is joined inside the authoritative conversation query before
  Focused/Other totals, ranking, windowing, and paging. The UI does not rearrange
  only the loaded rows.
- Create is client-idempotent; create, replace, delete, and Undo are guarded by
  exact revisions. A conflict reloads authoritative state rather than silently
  overwriting another session.
- The ledger is exact-account and capped at 500 rules per account. Disabled
  rules remain inspectable but do not affect placement.
- All rule routes require the authenticated browser session and return
  `Cache-Control: private, no-store`, including validation/authentication
  failures.

## Product surface

- Every Split Inbox placement reason is an explanatory, keyboard-accessible
  control that opens **Teach Split Inbox** for that conversation.
- The picker states the exact account, target placement, and future effect of
  conversation, sender, and domain scopes before Save.
- A first-class **Rules** control opens an account-filtered manager with target,
  placement, enabled state, revision conflicts, retry, and two-step delete.
- List and table modes show rule provenance. The narrow-screen list keeps the
  44-pixel explanatory control while hiding the redundant icon-only control;
  the picker becomes a contained 390-pixel bottom sheet.
- Command registration exposes Teach and Manage actions while preserving the
  existing Split Inbox keyboard and focus model.

## Data and API

Additive Alembic revision `c1d2e3f4a5b6`, direct child of
`b1c2d3e4f5a6`, creates `inbox_placement_rules`. The upgrade creates one empty
private rule table with account cascade, scope/placement/revision constraints,
client-create uniqueness, and exact account+scope+selector uniqueness. It does
no email backfill or provider operation. The downgrade drops user-created local
rules and is therefore data-lossy.

The private API adds:

```text
GET    /api/inbox-placement-rules
GET    /api/inbox-placement-rules/candidate
POST   /api/inbox-placement-rules
PUT    /api/inbox-placement-rules/{rule_uuid}
DELETE /api/inbox-placement-rules/{rule_uuid}
```

Conversation rows add safe source/scope/public-rule/revision provenance and
`user_rule_focused|user_rule_other` reasons. Existing system reasons remain
unchanged when no enabled rule wins.

## Verification

- One post-freeze `make check` passed 835 backend tests with 75 expected skips,
  all 538 frontend tests, and a 627-module production build.
- Backend finishing checks passed 20 focused service/router tests, two
  disposable-PostgreSQL query regressions, and exact
  `b1 -> c1 -> b1 -> c1` migration round trips.
- The browser-found narrow-screen density correction passed the focused 9-test
  frontend surface/rule/API set and a fresh 627-module build. Per D-041, it did
  not trigger another broad gate.
- Generated self-test covered two exact accounts, precedence, exact-domain
  versus subdomain, reload persistence, idempotent response-loss retry,
  revisions/conflicts, immediate Undo, and slow-session isolation.
- Generated desktop list, desktop table, rule picker, provenance, manager,
  390x844 split list, and 390x844 bottom-sheet browser QA passed with no browser
  warnings or errors.
- The final fixture audit recorded zero provider/Gmail reads or writes, email
  sends, mail/calendar mutations, AI calls, worker jobs, terminal operations,
  unexpected writes, unknown routes, or external-network calls.
- `git diff --check`, Python compile, Node syntax/self-test, migration review,
  secret-scope review, and the bounded P0/P1 review passed.

Privacy-safe generated evidence is outside the repository:

- `/Users/austinmcchord/Development/Email-release-evidence/trainable-focused-rules-2026-08-31/desktop-split-inbox.jpg`
- `/Users/austinmcchord/Development/Email-release-evidence/trainable-focused-rules-2026-08-31/desktop-rule-picker.jpg`
- `/Users/austinmcchord/Development/Email-release-evidence/trainable-focused-rules-2026-08-31/desktop-rule-provenance.jpg`
- `/Users/austinmcchord/Development/Email-release-evidence/trainable-focused-rules-2026-08-31/desktop-rule-manager.jpg`
- `/Users/austinmcchord/Development/Email-release-evidence/trainable-focused-rules-2026-08-31/desktop-table-inbox.jpg`
- `/Users/austinmcchord/Development/Email-release-evidence/trainable-focused-rules-2026-08-31/mobile-split-inbox.jpg`
- `/Users/austinmcchord/Development/Email-release-evidence/trainable-focused-rules-2026-08-31/mobile-rule-picker.jpg`

## Production

GitHub `main`, the feature branch, and production received exact application
runtime commit `060d4bca9db4b18ac4926679d2bbafe3f7b16736`.

Before migration, production created protected mode-0600 backup
`/var/backups/mailapp/maildb-pre-focused-rules-20260831T1921Z.dump`:
1,384,447,357 bytes, SHA-256
`f6dcf760986899bbd711a03e8f9b9b8e9b25f378daa02bd1b9f2399cab183dad`.
`pg_restore --list` passed before code or schema mutation.

Production upgraded exactly `b1c2d3e4f5a6 -> c1d2e3f4a5b6`, restarted only
`mailapp`, then built 627 frontend modules. The old API process exceeded its
graceful-stop timeout and systemd killed that old process; replacement PID
2184456 became healthy at 19:26:06 UTC with `NRestarts=0` and no warning-or-
higher entries after start. All seven checked services are active and public
health is `ok`.

Anonymous rule access is 401 with `private, no-store`. Aggregate-only
postflight confirmed the table exists and contains zero rules. Signed-in
read-only QA opened Email, the existing Split Inbox, one Teach picker, and the
empty Rules manager, then cancelled/closed them without opening a message or
saving a rule. A second aggregate check remained zero and browser logs were
clean.

## Rollback

Prefer a reviewed application roll-forward or Git revert plus selective API
restart/frontend rebuild. The new table is additive, so older application code
can ignore it. Do not downgrade after users create rules: `c1 -> b1` drops the
ledger and destroys explicit user instructions. The protected pre-c1 backup is
retained for disaster recovery, not routine application rollback.

## Follow-ons

- Observe real use before adding wildcard domains, cross-account rules,
  arbitrary selectors, provider labels, or AI-driven policy; each requires a
  separate ownership and mutation contract.
- Consider aggregate rule hit/unused indicators only if they can remain
  content-free, private, bounded, and genuinely useful.
- Continue the bounded physical terminal qualification independently; it does
  not share this table, API, or Inbox projection.
