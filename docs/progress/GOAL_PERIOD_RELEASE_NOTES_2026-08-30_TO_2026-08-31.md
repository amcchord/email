# Modern Mail Client Goal-period Release Notes — 2026-08-30 to 2026-08-31

## Release outcome

The first sustained modern-mail-client improvement cycle is now frozen for
user testing. The product moved from a capable mailbox into a substantially
more complete daily email workspace: durable and recoverable mail actions,
conversation-first reading, Focused/Other splits, trainable rules, touch and
bulk triage, scheduled delivery and Undo Send, durable drafts and replies,
Snooze, labels and Move, Saved Views, Contacts, Attachments, writing tools,
truthful calendar availability sharing, and a first-class At a Glance terminal
workspace.

The cycle intentionally kept real-mail and Calendar acceptance read-only.
Mutation testing used loopback-only generated `.example.test` fixtures; device
writes remained behind independent enrollment, artifact, hardware, and rollout
gates. Work from the separate AI track is not attributed in these notes.

### Exact release boundary

- Starting source boundary:
  `7ddad16276416a6faa2e08c72aaea637927f644e` (2026-08-29,
  “Record lossless sync safety contract”)
- Final application/runtime:
  `c7b9960653f48c0a7ab47f79a295d6fedd19695a`
- Final pre-freeze GitHub/production documentation boundary:
  `ee48d598fb662f4564cc1c0224b790e0196db7e1`
- Production database schema: `c1d2e3f4a5b6 (head)`
- Cycle size before this release-notes closeout: 151 commits, 511 changed-file
  entries, 140,788 insertions, and 3,603 deletions

## What changed for users

### Inbox, reading, and triage

- **Conversation-first mail.** Inbox, ordinary mailboxes, labels, and search
  now share one account-owned conversation row. Opening a row shows the full
  chronological conversation, while conversation-scoped actions retain exact
  ownership and durable recovery.
- **Focused and Other.** A deterministic split ranks, counts, and pages both
  sections over the same authoritative Inbox dataset. Reasons are visible and
  the split never moves or relabels mail at Gmail.
- **Trainable split rules.** A user can teach a conversation, exact sender, or
  exact domain to appear in Focused or Other, inspect the resulting rule,
  edit/disable/delete it, and immediately Undo. Rule precedence and account
  scope are explicit; production began with an empty private rule ledger.
- **Touch-first triage.** Primary-touch swipes default to Archive left and
  Snooze right, with cross-device choices for read, star, or no action.
  Protected mailboxes, vertical/multi-touch/cancelled gestures, stale datasets,
  and failed preference hydration perform no gesture write.
- **One selection model.** Checkboxes, long press, `X`, Shift-range, Select
  loaded, and Clear now behave consistently across list and table views. A
  responsive bulk bar exposes only the actions appropriate to the current
  mailbox.
- **Universal Snooze.** Inbox, reader, Flow, search, keyboard `H`, reload, cron
  recovery, and the first-class Snoozed mailbox share one durable return-time
  contract.
- **Labels and Move.** Account-safe synchronized Gmail labels are available in
  rows, tables, reader, bulk actions, `L`, and literal-Inbox-only `V`, with the
  same exact Undo/retry/replay behavior as other durable mail actions.
- **Fast navigation.** The command palette, keyboard shortcuts, lazy feature
  routes, resilient navigation, composable structured search, and truthful
  result summaries make more of the app reachable without pointer travel.

### Writing, sending, and follow-up

- **Durable ordered outbox and Undo Send.** Outbound work is stored before
  provider delivery, ordered per account, retry-aware, and recoverable across
  process restarts and lost responses.
- **Durable drafts and replies.** Compose, reader reply, Flow, and Drafts share
  exact-source draft identities, revision-safe saves, visible recovery, and
  structured reply envelopes. A refresh or transient failure no longer turns
  an in-progress reply into an anonymous local editor state.
- **Scheduled Send.** Compose, reader, and Flow share one future-delivery
  workflow with reload-safe management, cancellation boundaries, and
  server-owned archive follow-up.
- **Send & Archive.** Full Compose and inline reply use one visible action and
  `Cmd/Ctrl+Shift+Enter`. The source conversation is archived only after
  provider-confirmed delivery; ordinary new messages fail closed to Send.
- **Recipient autocomplete and safe chips.** To/Cc/Bcc suggestions come from
  account-scoped synchronized metadata. Quoted commas, duplicate recipients,
  cross-field conflicts, and unresolved typed text are handled explicitly;
  pending text blocks save/send rather than being silently dropped.
- **Personal snippets.** Settings → Writing owns revisioned private snippets.
  Compose, reader, and Flow share a keyboard-accessible picker, sanitized
  caret-preserving rich/plain insertion, narrow-screen behavior, and one-step
  Undo.
- **Inline snippet expansion.** Typing a boundary-safe `;shortcut` opens a
  caret-local menu; Enter, Tab, or pointer selection replaces only the verified
  trigger. Escape leaves authored text untouched.
- **Per-account signatures.** Default-off rich/plain signatures are frozen as
  sanitized content-hashed sidecars per durable intent. Remove/Restore is
  message-local and authored body/quote boundaries remain intact.
- **Automatic follow-up reminders.** Default-off per-account policies and
  per-message overrides create an Inbox-safe, reply-aware Snooze only after
  provider-confirmed delivery maps to one synchronized Sent row.
- **Share availability.** Compose, reader reply, and Flow can insert selected
  times from recent, complete, stable synchronized primary-calendar snapshots.
  It is explicitly a proposal—not a hold, booking link, live guarantee, event,
  or provider write.
- **Deferred rich editor loading.** Heavy writing code is loaded only when a
  writing surface is needed, reducing ordinary reading/navigation cost without
  removing rich-text controls.

### Organization and first-class workspaces

- **Saved Views / Custom Splits.** Up to twelve validated structured searches
  can be saved, optionally scoped to an exact owned account, opened from Email
  navigation or the command palette, reordered, edited, and deleted. Search
  terms remain out of URLs and results are always computed from current mail.
- **Contacts.** More → Contacts provides an exact-account relationship
  projection over synchronized metadata with responsive list/profile views and
  exact Compose/Inbox handoffs. It requests no new provider scope and is not a
  writable address book.
- **Attachments.** More → Attachments offers literal search, type/direction
  filters, signed keyset pagination, responsive keyboard navigation, safe
  preview/download, and exact parent-message handoff over a local metadata
  index. Ordinary browsing performs no provider fetch or cache write.
- **Safe attachment previews.** Message attachments gained bounded previews
  and gallery navigation while preserving explicit download and content-type
  safety.
- **More-menu reliability.** The More menu now remains anchored below its
  trigger instead of rendering at the page edge or causing the shell to appear
  blank.

### Accounts, Calendar, privacy, and session correctness

- **Reliable Google reauthorization.** OAuth uses an explicit PKCE verifier,
  signed/nonce-bound state, sanitized callback redirects, actual granted-scope
  validation, and fail-safe exception handling. The callback no longer exposes
  a raw JSON internal-server-error page for expected authorization failures.
- **Calendar scope preservation.** Gmail and Calendar token refreshes now
  retain the same recorded data-scope set, so a Gmail refresh cannot silently
  remove Calendar access after successful reauthorization.
- **Race-safe Calendar state.** Connection, synchronization, reauthorization,
  and error state are published consistently. Availability fails closed during
  stale, incomplete, changing, or failed coverage.
- **Session isolation and ownership.** Session-scoped frontend state is cleared
  at account/session boundaries, and Todo/session data is explicitly owned
  rather than leaking through singleton stores.
- **Administrator and trusted-account policy.** The explicitly requested active
  account was promoted to administrator. The OAuth policy was widened only to
  the requested trusted organization domains while consumer accounts remain
  exact-address entries; aggregate verification passed without exposing the
  private address list.
- **Remote-content privacy.** Remote email content is blocked by default with
  an explicit reveal path, reducing tracking and unexpected network access.
- **Actionable privacy-safe errors.** Account-policy and OAuth failures are
  surfaced as user-facing outcomes instead of internal details. Private
  account addresses and authorization state remain out of user-facing errors.

### At a Glance and e-ink terminals

- **First-class At a Glance tab.** Terminal status moved beyond Settings into
  a primary authenticated route with canonical 16:9/9:16 previews, battery and
  charge summaries, firmware state, and credential-free display experiences.
- **Deterministic display registry.** Exact design/palette catalogs and
  import-time completeness checks prevent an unknown future design from
  silently rendering as an existing one.
- **Battery history and conservative predictions.** Sparse telemetry, invalid
  burst filtering, and cautious charge wording improve operational visibility
  without using a forecast as authorization for a device write.
- **Fail-closed firmware gateway.** Signed schema-2 artifact/catalog parsing,
  immutable package verification, exact-model policy, and browser
  cryptographic preflight exist without granting flash authority.
- **Secure RET1 enrollment foundation.** Owner-scoped pending/candidate/active
  identities, bounded activation/recovery, revision control, and legacy
  continuity prevent a partial enrollment from silently transferring or
  stranding a device.
- **Browser install and recovery workflow.** Pinned Web Serial/Web Locks code
  supports one explicit preserve-config flash/readback/reset/RET1 sequence with
  same-port verification and lost-result recovery. Production still renders
  the action locked unless every independent policy gate is satisfied.
- **OTA control plane.** Exact offers, private artifacts, conservative power
  admission, deterministic cohorts, an append-only attempt/event ledger, and
  owner history/revision controls are implemented. Enablement and rollout
  remain closed.
- **Legacy signed OTA transport.** The legacy `/config.json` path can serve an
  owner- and device-scoped, Ed25519-verified immutable update only when an
  explicit current pointer, exact E1001/E1002 identity, fresh high battery,
  and differing running version all agree. Invalid or absent release state
  produces no offer. The Email server boundary is runtime `91c903c`; pointers
  are per-device operations rather than a generic rollout.
- **Two-model legacy OTA evidence.** One explicitly attached E1001 and one
  explicitly attached E1002 were USB-bootstrapped to candidate.15, accepted the
  signed/model-bound candidate.16 feature-branch release
  `3e75d1048e4388ae0e81e78e3c028e20111fd019`, wrote inactive `ota_1`, rebooted
  on candidate.16, retained file-based configuration, and resumed normal
  schedule/render operation. Server telemetry observed candidate.16/`ota_1`
  for both. This is bounded physical evidence, not promotion of that branch to
  private firmware `main` or completion of generic rollout qualification.
- **Physical E1002 evidence and DIO correction.** Candidate.8 exposed a real
  QIO boot failure on one E1002. The same device recovered under DIO, and
  immutable candidate.9 now enforces DIO packaging, completed trusted-HTTPS
  fetch/render/check-in/sleep, and remains the exact private firmware main.

## Reliability and platform work

- Mail mutations now use one optimistic UI and durable action vocabulary with
  actionable toasts, exact Undo, idempotency, lost-response reconciliation,
  retry/replay, and accessible recovery instead of isolated per-view handlers.
- Generated acceptance environments cover two accounts and deterministic
  mail, draft, Calendar, search, rules, and writing scenarios while rejecting
  provider calls, real recipients, unexpected writes, and external network
  access.
- APIs added during the cycle are authenticated, account-owned, bounded, and
  generally private/no-store. Opaque identities are used where raw provider
  identifiers are unnecessary.
- Keyset pagination, authoritative totals, server-derived selectors, and
  revisioned local policies reduce client-side drift and ambiguous conflict
  handling.
- Routes and heavy feature modules load lazily; the final production frontend
  build transformed 634 modules.
- Production deployments used exact Git commits, selective service restarts,
  validated backups before migrations, health/log postflight, and explicit
  rollback boundaries. A recurring 90-second graceful-stop overrun affected
  retired API processes; replacements became healthy with zero automatic
  restarts.

## Database evolution

All schema changes were additive and reviewed as one linear Alembic chain:

| Revision | Capability |
| --- | --- |
| `z7a8b9c0d1e2` | Durable mail-action outbox |
| `a8b9c0d1e2f3` | Terminal battery history |
| `b9c0d1e2f3a4` | Terminal web-display catalog/state |
| `c0d1e2f3a4b5` | Todo/session ownership |
| `d1e2f3a4b5c6` | Durable outbound messages and Undo Send |
| `e2f3a4b5c6d7` | Durable draft sessions |
| `f3a4b5c6d7e8` | Secure terminal enrollment |
| `a4b5c6d7e8f9` | Universal Snooze |
| `b5c6d7e8f9a0` | Gmail label and Move actions |
| `c6d7e8f9a0b1` | Terminal OTA attempt/event ledger |
| `d7e8f9a0b1c2` | Personal snippets |
| `e8f9a0b1c2d3` | Automatic follow-up reminders |
| `f9a0b1c2d3e4` | Per-account signatures |
| `a0b1c2d3e4f5` | Saved Views |
| `b1c2d3e4f5a6` | Attachment metadata index |
| `c1d2e3f4a5b6` | User-owned Inbox placement rules |

Production is at exact head `c1d2e3f4a5b6`. The final touch-triage release was
migration-free.

## Milestone index

These records contain exact runtime commits, verification, deployment, safety,
and rollback detail. They are grouped by product area rather than commit order.

### Core mail and organization

- [Product polish and modern-client foundation](PRODUCT_POLISH_RELEASE_2026-08-30.md)
- [Safe outbound delivery and Undo Send](SAFE_OUTBOUND_DELIVERY_RELEASE_2026-08-30.md)
- [Durable draft sessions](DURABLE_DRAFT_SESSIONS_RELEASE_2026-08-30.md)
- [Durable inline replies](DURABLE_INLINE_REPLIES_RELEASE_2026-08-30.md)
- [Conversation-first Inbox](CONVERSATION_FIRST_INBOX_RELEASE_2026-08-30.md)
- [Focused/Split Inbox](FOCUSED_SPLIT_INBOX_RELEASE_2026-08-30.md)
- [User-trainable Focused/Other rules](TRAINABLE_FOCUSED_RULES_RELEASE_2026-08-31.md)
- [Touch-first Inbox triage](TOUCH_FIRST_TRIAGE_RELEASE_2026-08-31.md)
- [Universal Snooze](UNIVERSAL_SNOOZE_RELEASE_2026-08-30.md)
- [Gmail Labels & Move](LABELS_AND_MOVE_RELEASE_2026-08-30.md)
- [Scheduled Send](SCHEDULED_SEND_RELEASE_2026-08-30.md)
- [Universal Send & Archive](UNIVERSAL_SEND_ARCHIVE_RELEASE_2026-08-30.md)
- [Saved Views / Custom Splits](SAVED_VIEWS_RELEASE_2026-08-31.md)
- [First-class Contacts](CONTACT_PROFILES_RELEASE_2026-08-31.md)
- [Attachments workspace](ATTACHMENTS_WORKSPACE_RELEASE_2026-08-31.md)

### Writing and follow-up

- [Recipient autocomplete and safe chips](RECIPIENT_AUTOCOMPLETE_RELEASE_2026-08-30.md)
- [Personal snippets](PERSONAL_SNIPPETS_RELEASE_2026-08-30.md)
- [Inline snippet expansion](INLINE_SNIPPET_EXPANSION_RELEASE_2026-08-31.md)
- [Per-account signatures](ACCOUNT_SIGNATURES_RELEASE_2026-08-31.md)
- [Automatic follow-up reminders](AUTOMATIC_FOLLOW_UP_REMINDERS_RELEASE_2026-08-31.md)
- [Share Availability](SHARE_AVAILABILITY_RELEASE_2026-08-31.md)

### Account, privacy, and Calendar correctness

- [OAuth reauthorization with PKCE](OAUTH_REAUTHORIZATION_RELEASE_2026-08-30.md)
- [OAuth callback fail-safe](OAUTH_CALLBACK_FAILSAFE_RELEASE_2026-08-30.md)
- [Reply-envelope integrity](REPLY_ENVELOPE_INTEGRITY_RELEASE_2026-08-30.md)
- [Calendar state integrity](CALENDAR_STATE_INTEGRITY_RELEASE_2026-08-30.md)
- [Session ownership and shell reliability](SESSION_OWNERSHIP_AND_SHELL_RELEASE_2026-08-30.md)
- [Remote-content privacy](REMOTE_CONTENT_PRIVACY_RELEASE_2026-08-30.md)

### At a Glance and terminal platform

- [At a Glance display platform](AT_A_GLANCE_RELEASE_2026-08-30.md)
- [Firmware gateway](TERMINAL_FIRMWARE_GATEWAY_RELEASE_2026-08-30.md)
- [Secure enrollment foundation](SECURE_TERMINAL_ENROLLMENT_FOUNDATION_RELEASE_2026-08-30.md)
- [First-class At a Glance](AT_A_GLANCE_FIRST_CLASS_RELEASE_2026-08-30.md)
- [Firmware safety and battery](AT_A_GLANCE_FIRMWARE_SAFETY_RELEASE_2026-08-30.md)
- [Firmware protocol and installer foundation](AT_A_GLANCE_FIRMWARE_PROTOCOL_INSTALLER_RELEASE_2026-08-30.md)
- [OTA control plane](AT_A_GLANCE_OTA_CONTROL_PLANE_RELEASE_2026-08-30.md)
- [Browser transport and owner controls](AT_A_GLANCE_BROWSER_TRANSPORT_RELEASE_2026-08-30.md)
- [RET1 browser provisioning](AT_A_GLANCE_RET1_BROWSER_PROVISIONING_RELEASE_2026-08-30.md)
- [Terminal recovery evidence](AT_A_GLANCE_TERMINAL_RECOVERY_EVIDENCE_RELEASE_2026-08-30.md)
- [Physical E1002 candidate.9 milestone](AT_A_GLANCE_E1002_CANDIDATE9_HIL_MILESTONE_2026-08-31.md)

## Verification and safety evidence

The cycle used focused iteration checks, one bounded P0/P1 review at release
freeze, and one consolidated gate for each coherent milestone. The most recent
full gate passed:

- 841 backend tests, with 75 expected skips for intentionally unavailable
  external/disposable environments;
- all 554 frontend tests;
- the 634-module production frontend build; and
- generated browser/self-test acceptance for exact Archive/Undo,
  lost-response reconciliation, explicit-time-only Snooze, protected dataset
  guards, responsive selection/bulk UI, and touch settings.

Generated browser acceptance used only `.example.test` identities and recorded
zero provider/Gmail/send/Calendar/AI/worker/terminal/external-network
operations for touch triage. The final touch-triage signed-in production
acceptance stayed read-only: no real message was opened or mutated, no draft
was saved or sent, no Calendar or provider write occurred, and no terminal
chooser/write was invoked.

Privacy-safe screenshots and detailed browser evidence remain outside the Git
repository under `/Users/austinmcchord/Development/Email-release-evidence/`.
Every milestone record links its applicable evidence and exact verification
boundary.

## Current production state

- GitHub and production documentation boundary before this docs-only closeout:
  `ee48d598fb662f4564cc1c0224b790e0196db7e1`
- Running application/runtime:
  `c7b9960653f48c0a7ab47f79a295d6fedd19695a`
- Alembic: `c1d2e3f4a5b6 (head)`
- Public health: `ok`
- Checked services: `mailapp`, `mailworker`, `mailworker-cron`, `mailtui`,
  `caddy`, `postgresql`, and `redis-server` all active
- Replacement API at the runtime boundary: PID 2188272, zero automatic
  restarts, with no warning-or-higher entries after activation
- Private firmware `main`: candidate.9
  `52ba6c58ca7f17741d0d74c225f8d942b6119241`, with exact green runs
  `33412815120` and `33414658605`
- Terminal state: generic browser enrollment and OTA rollout remain locked.
  The two explicitly attached legacy devices report feature-branch
  candidate.16 on `ota_1`; no claim of generic or complete cross-model
  qualification is made

## Suggested user-testing pass

This pause should emphasize ordinary workflows and observation, not another
broad automated-test cycle.

1. **Navigate and read:** move among Inbox, Focused/Other, labels, Saved Views,
   Snoozed, Contacts, Attachments, Calendar, Flow, and At a Glance. Confirm
   back/forward, More-menu placement, responsive layout, counts, and keyboard
   focus feel natural.
2. **Triage deliberately:** on disposable/generated mail, try row actions,
   selection, bulk actions, keyboard shortcuts, touch swipes, Snooze, Labels,
   Move, and Undo. Confirm protected mailboxes expose the right recovery action.
3. **Write safely:** use a generated test recipient to exercise autocomplete,
   chips, snippets, inline expansion, signatures, draft recovery, Schedule Send,
   Send & Archive, and optional follow-up. Cancel or Undo where appropriate.
4. **Train the split:** teach one generated conversation/sender/domain, inspect
   its reason and rule ledger, Undo it, and confirm totals/paging remain stable.
5. **Share availability:** open the picker, inspect freshness/error language,
   insert a proposal into a generated draft, and confirm the copy does not imply
   a reservation.
6. **Inspect first-class workspaces:** search Contacts and Attachments, preview a
   safe generated attachment, and follow its parent-message handoff.
7. **Observe At a Glance:** inspect preview, battery, firmware, enrollment, and
   OTA state. Do not invoke Web Serial or alter gates during this user-testing
   pause.

Report workflow-impacting regressions with the route, account context (without
mail content), viewport, action, and expected/observed result. P0/P1 issues can
receive a focused reproduction and patch; P2 polish should be batched rather
than reopening the entire release gate.

## Intentional limits and deferred work

- Real-mail and Calendar acceptance remained read-only. Generated test mail is
  the approved mutation surface for follow-up QA.
- Share Availability is a synchronized proposal, not a booking link, hold,
  event, or promise of live availability.
- Contacts is a bounded metadata projection, not a writable/synchronized
  address book.
- Saved Views store definitions, not cached message membership or provider
  labels.
- Attachments browsing is metadata-first; provider/cache access remains an
  explicit Preview/Download action.
- Signatures and automatic follow-ups default off until a user saves a policy.
- Terminal enrollment, browser flashing, and OTA have independent gates. One
  physical E1002 DIO installation and the later bounded E1001/E1002 legacy OTA
  runs are meaningful evidence but do not complete the full interruption,
  rollback, recovery, and cross-revision HIL matrix. Candidate.16's superseded
  CI run was cancelled and must not be called green; legacy boot state was
  reported conservatively as recovery-required even though serial/runtime
  evidence proved both devices healthy. Follow-up commit `e45f3d9` corrects
  that classification but remains uninstalled and unreleased.
- E1004 remains ineligible for browser installation and OTA.
- Separate AI-track changes were developed concurrently and are intentionally
  outside this release's attribution and acceptance claims.
- Minor visual polish and speculative follow-ons are paused. The next work
  cycle should start from user-observed friction, batch related fixes, and run
  one proportional release gate instead of recursively retesting every nit.

## Pause

Feature development is paused at this boundary for user testing. The safe next
action is to collect real workflow feedback, rank issues by user impact, and
open one bounded follow-up release only when there is a coherent set of changes
to ship.
