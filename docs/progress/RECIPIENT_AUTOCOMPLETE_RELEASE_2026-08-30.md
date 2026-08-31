# Recipient Autocomplete Release — 2026-08-30

## Outcome

Recipient autocomplete is a migration-free Compose improvement prepared from
baseline `8b0aa873a1089093783b0bd08d5964b508e1b186`. To, Cc, and Bcc now use one
account-safe, keyboard-first chip workflow that preserves quoted display names,
manual entry, durable drafts, and exact outbound recipients.

## Product behavior

- Typing searches the selected sending account after a short debounce. Exact
  and prefix matches rank first, prior outgoing correspondents outrank incoming
  only, and recency/frequency resolve remaining ties.
- Arrow keys navigate, Enter or Tab selects, Escape dismisses, separators and
  paste commit complete mailboxes, and Backspace removes the last chip from an
  empty field. Quoted display-name commas remain intact.
- To/Cc/Bcc share case-insensitive duplicate protection. A duplicate stays out
  of the message and receives immediate inline feedback.
- Suggestions degrade to manual entry on delay or failure. Switching sender
  accounts clears pending query/results and aborts stale work.
- Chips expose 44-pixel remove targets and contain long addresses at desktop
  and 390-pixel widths without horizontal page overflow.

## Draft and send integrity

- Only canonical committed chips enter local persistence, server draft
  autosave, explicit Save Draft, and outbound admission.
- Incomplete or invalid text remains visible and local. While it exists,
  sender changes, Save Draft, back navigation, Send, Send & Archive, scheduled
  send, and their keyboard shortcuts fail closed instead of silently omitting
  the visible recipient.
- Existing array and legacy string draft payloads hydrate through the same
  quoted-comma-safe parser. A committed chip survives autosave and hard reload
  with its canonical mailbox identity.

## Privacy and service contract

- `GET /api/compose/recipients` requires the signed-in web session and an
  active account owned by that user. Missing, inactive, and foreign accounts
  share one non-disclosing 404 response.
- One account/date-index-compatible query reads at most the newest 4,000
  synchronized metadata rows. Python excludes drafts, Spam, Trash, and all
  addresses owned by the user before ranking at most 20 results.
- Responses contain only display name, normalized address, and formatted
  mailbox. The feature adds no Contacts scope, provider request, body/subject
  content, schema change, migration, package, worker, AI, or terminal change.

## Generated safety fixture

- The localhost-only fixture contains isolated generated users and accounts,
  quoted-comma names, duplicate history, legacy address representations,
  owned-address decoys, and correspondents visible only in another account.
- Delay, failure, and held-session scenarios prove manual fallback, account
  changes, logout/login generation changes, abort/stale-response containment,
  and content-free audit evidence.
- All mutable identities use `.example.test`. The acceptance run recorded zero
  provider sends, unexpected mutations, unknown routes, external network
  calls, or non-fixture recipient attempts.

## Review and verification

- Independent P0/P1 review found no P0. It identified two P1 issues: unfinished
  visible text could be omitted from a send, and two filtered history queries
  could scan too much account history. The released candidate blocks all
  actions while text is pending and uses one truly bounded recent corpus.
- Focused backend, frontend, and fixture checks passed during iteration.
- Generated browser QA passed suggestion selection, duplicate feedback,
  chip-to-draft-to-reload continuity, pending-input gates, modifier shortcut
  containment, alternate-account isolation, held stale-session rejection,
  manual fallback, desktop/narrow layout, touch targets, and console checks.
- Independent user acceptance found no P0/P1 blocker. It separately passed
  quoted-comma keyboard selection, pasted/manual `.example.test` chips,
  case-insensitive cross-field duplicate rejection, incomplete-Bcc action
  gates, shortcut containment, and 390-pixel layout without sending.
- The one final consolidated `make check` passed 734 backend tests with 66
  expected skips, all 462 frontend tests, and a 598-module production build.

## Deployment and rollback

Deployment requires an exact Git fast-forward, frontend production build, and
replacement of only `mailapp`. No dependency install, database backup,
migration, worker restart, Caddy change, or provider operation is required.
Rollback is the prior Git/frontend application release; the feature creates no
new schema or durable data to reverse. Existing drafts containing committed
recipient arrays remain compatible with both boundaries.

## Production result

Pending deployment. Production has not been mutated during development or
generated browser acceptance.
