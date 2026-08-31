# Current Status

Last updated: 2026-08-30

## Active Objective

Ship safe account-scoped recipient autocomplete as the next bounded writing
acceleration milestone, then continue with inline snippet expansion. Operate
Personal Snippets, Universal Send & Archive, Focused/Split Inbox, and the
terminal track as durable, truthful workflows. Continue physical qualification
of the independently gated Web Serial installer and OTA control plane on exact
E1001/E1002 hardware. Keep real mail/calendar QA read-only except for generated
`.example.test` fixtures and preserve every independent terminal write gate.

## Baseline

- The deployed Personal Snippets application/runtime is
  `1397160c2318d4d48997e800dbda20c536d8b0d5`. Settings → Writing owns private
  revisioned CRUD, while Compose, reader, and Flow share one `Cmd/Ctrl+;`
  picker with search, caret-preserving sanitized rich/plain insertion, one-step
  Undo, narrow-screen support, and keyboard containment. Production started
  with zero snippet rows.
- The deployed Universal Send & Archive application/runtime is
  `c7171466d075fc74f12ccb47fb2ee2d27ec830a6`. Full Compose and inline replies
  expose the same Send options and `Cmd/Ctrl+Shift+Enter` contract, while new
  messages fail closed to ordinary Send. The server archives the exact owned
  conversation only after provider-confirmed delivery; Undo, cancellation,
  delivery failure, and a later-deleted source remain safe.
- The deployed Focused/Split Inbox application/runtime is
  `dea8117f5b5348d8c4d3f78e0e6af08273a6367d`. One coherent endpoint ranks,
  counts, and pages both visible sections over the authoritative owned-account
  conversation row, with exact totals, stable reasons, keyboard traversal, and
  no Gmail move, AI call, or migration.
- The deployed conversation-first Inbox application/runtime code boundary is
  `f5be5851ae7c5e628e490223c50deb0be1c9c9b2`; following closeout commits are
  documentation only. Inbox, ordinary mailboxes, labels, and search now use one
  authoritative owned-account conversation row with a chronological reader and
  durable conversation-scoped actions.
- The deployed terminal OTA control-plane application/runtime is
  `9253eb42d884868a18f280bbf4ab1aae6b474b5e`. It adds owner-idempotent exact
  offers, active-credential scoped artifacts, coherent source/target runtime
  checks, conservative power and deterministic cohort gates, and an append-only
  attempt/event ledger. Production remains disabled with an empty HIL map,
  zero-percent rollout, no eligible descriptor, and zero attempt/event rows.
- The deployed At a Glance terminal integration runtime is
  `739fe555d90dc9dd49ffdea28fc165ed2b0f7089`. One explicit user action can hold
  a selected Web Serial port and origin-wide Web Lock through exact
  preserve-config flash/readback, reset, RET1 configuration/result, and scoped
  activation polling. Safe pre-write cancellation, same-generation retry after
  fresh physical proof, and lost-result generation recovery avoid automatic
  encrypted-write replay. Production remains unreachable because it has no
  trusted release key, approved catalog/generation, online enrollment identity,
  qualified release/model HIL tuple, or enablement; no Wi-Fi inputs render and
  Connect is disabled.
- The deployed Pillow renderer now uses exact immutable design and palette
  registries with import-time catalog/device/web completeness checks. Existing
  Home Editorial/Swiss and Day Ahead Editorial pixels are unchanged; a missing
  future design implementation fails closed instead of silently rendering as
  Editorial.
- The deployed Gmail Labels & Move application/runtime commit is
  `a440801c18c8377b50a225af71f3937caa78c7af`. Existing synchronized user labels
  are account-safe, conversation-scoped durable actions across list, table,
  bulk, reader, `L`, and literal-Inbox-only `V`, with exact Undo/retry/replay
  behavior and responsive accessible UI.
- Universal Snooze application/runtime is
  `231173b2d18966b603ed2f824f68380f8087de2c`; production deployed it with the
  migration-free terminal candidate.5 integration as combined runtime
  `35e3700e8a22eabf49e701fb873d4662d5b7abdc`. One durable reminder owns the
  exact account/conversation across Inbox, reader, Flow, search, first-class
  Snoozed, `H`, reload, provider retry, and cron recovery.
- The deployed combined application/runtime commit is
  `35e3700e8a22eabf49e701fb873d4662d5b7abdc`. Its migration-free terminal slice
  excludes candidate.5 battery bursts marked invalid and understands exact
  RET1 status v2 runtime/build identity while retaining fail-closed candidate.4
  status-v1 compatibility. Browser firmware writes, device OTA transport, and
  the read-only OTA capability endpoint remain independently locked.
- The deployed Scheduled Send application/runtime commit is
  `8b0f1c974ecc3c52a0a5e48a0cbe3e61c5eb2ae6`; the following closeout is docs
  only. Compose, reader, and Flow share one durable future-delivery workflow,
  including reload-safe management and server-owned Flow archive follow-up.
- The deployed first-class At a Glance application/runtime commit is
  `945b71860e08d79e6ddeb5e3faccffe372418ff1`. The authenticated primary route,
  canonical 16:9/9:16 previews, terminal battery/charge overview, and
  credential-free experience API are live. The following closeout is docs only.
- The deployed Calendar scope-preservation runtime is
  `a9295b8fae1dee97f1f85be3530396bc5390dd80`. Gmail and Calendar now refresh
  their shared token with the same recorded data-scope set, so Gmail cannot
  strip Calendar access after a successful reauthorization. The three affected
  accounts require one final reconnect.
- The deployed Durable Replies application/documentation commit is
  `9aa93f61fe7031ce267b833930a84c5d0a2121c3`; the following closeout is docs
  only. Reader, Flow, Compose, and Drafts now share one exact-source durable
  reply identity, and production built 524 frontend modules.
- The deployed secure-enrollment application/runtime commit is
  `8ff01848a2be2818dfd9eb88b84be9aab4befb0a`; the following closeout is docs
  only. Production and GitHub were exact and clean at the runtime boundary.
- Production Alembic is `d7e8f9a0b1c2 (head)`, the additive Personal Snippets
  child of terminal OTA revision `c6d7e8f9a0b1`. The new owner-scoped table
  requires no backfill and began empty. Both OTA tables also remained empty at
  their release; all four existing terminals remain legacy.
- All seven checked production services are active, public health is `ok`, and
  the replacement API process has zero automatic restarts and no post-start
  warning-or-higher entries. Production has no secure-enrollment or OTA
  enablement, online key, approved catalog, qualified release/model pair,
  nonzero rollout, or device update offer.
- Private firmware `main` is exact at candidate.8
  `14f7046ae0253504f25972e9bc6ad952c1fa649f`. Exact-SHA run `33349001516`
  passed release tooling, keyed RET1 and OTA1 coordinator builds, every model,
  reproducibility, signed-manifest verification, and immutable candidate
  upload. A valid configured-device hello may extend the initial reset window
  once to a fixed 60-second-from-start ceiling; invalid or repeated hellos
  cannot keep the device awake.
- The offline promotion/signing workflow is integrated on that same private
  firmware `main`. It requires complete schema-2, revision-bound E1001 and E1002
  HIL records across 31 cases, preserves candidate bytes, emits the application
  gateway's exact signed catalog tree, and keeps E1004 plus all OTA eligibility
  false. It has not used a real key, qualified a device, or changed any
  production enablement.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Items

### P1 — Physical E1001/E1002 browser-install qualification

- State: candidate.8, the schema-2 HIL evidence harness, exact browser package
  preflight, real pinned Web Serial/RET1 same-port transport, recovery workflow,
  offline HIL-bound signing tool, and both OTA1 parsers are complete; production
  remains locked. No E1001/E1002 was attached during this release, and no
  chooser, device write, enrollment key, qualified catalog, or OTA offer was
  enabled.
- Scope: physical RET1 enrollment, interrupted serial/config write, three-slot
  selection, same-owner pending continuity, rollback grace, revocation,
  preserve-config, trusted-time/CA failure, A/B partition migration, inactive
  slot write, pending-image validation, power loss, automatic rollback, and ROM
  recovery on both models.
- Acceptance: repeatable recovery evidence proves a failed or interrupted
  enrollment, flash, or update cannot silently strand a terminal, disclose
  credentials, or replace the known-good slot. Only qualified exact
  release/model/hardware-revision tuples may enter either allowlist.
- Next: attach dedicated E1001/E1002 devices and execute the 31-case HIL record
  with bounded source evidence before enabling either browser or OTA transport
  for a real device.

### P2 — Durable device OTA control plane

- State: application runtime `9253eb4` and Alembic `c6d7e8f9a0b1` are deployed;
  all production gates remain closed and both new tables are empty. Firmware
  candidate.8 is on private `main` after its exact CI gate passed.
- Scope: one additive event-ledger migration descending from b5, authenticated
  device offer/artifact/event endpoints,
  idempotent attempt state, power gates, rollout cohorts, and rescue controls.
- Acceptance: a restart or repeated request cannot duplicate or lose update
  truth, only exact HIL-qualified evidence is offerable, and no single flag can
  enable a write.
- Next: attach dedicated hardware and complete physical A/B migration,
  interrupted-write, rollback, recovery, and USB-rescue evidence before
  installing any eligible descriptor or changing rollout from zero.

## Recipient Autocomplete Release Candidate

- One reusable accessible recipient field replaces delimiter-fragile Compose
  text boxes with canonical To/Cc/Bcc chips, quoted-comma-safe paste/manual
  parsing, cross-field duplicate protection, keyboard-first suggestions,
  removable 44-pixel targets, and responsive overflow containment.
- Suggestions use only a single 4,000-row recent metadata corpus from the
  selected active owned account, exclude all of the user's own addresses, and
  return no subject/body content. There is no Contacts scope, provider request,
  migration, or new dependency.
- Unfinished text remains local and blocks sender changes, draft save,
  navigation, and button/shortcut Send. Only committed chips enter durable
  autosave and outbound admission.
- Focused backend/frontend checks, generated `.example.test` audit, desktop and
  390×844 browser QA, one independent P0/P1 review, and independent user
  acceptance passed. The review's two P1 findings were fixed. The single
  consolidated post-freeze gate passed 734 backend tests with 66 expected
  skips, all 462 frontend tests, and a 598-module production build.
- Full behavior, validation, production, and rollback evidence is being
  recorded in `RECIPIENT_AUTOCOMPLETE_RELEASE_2026-08-30.md`.

## Recent Personal Snippets Release

- Every signed-in user can search and manage a private reusable writing library
  under Settings → Writing, then insert a rich or plain snapshot from Compose,
  reader, or Flow with `Cmd/Ctrl+;`.
- Stable client UUID creates, revision-checked full updates, non-disclosing
  deletes, owner/shortcut uniqueness, bounded content, and sanitized editor
  insertion keep retries, concurrent edits, and hostile markup safe.
- Final verification passed 727 backend tests with 66 expected skips, all 448
  frontend tests, a 595-module build, exact `c6 → d7 → c6 → d7` disposable
  migration coverage, generated-provider lifecycle/audit checks, desktop and
  narrow browser QA, and independent P0/P1 review. Full evidence is in
  `PERSONAL_SNIPPETS_RELEASE_2026-08-30.md`.

## Recent Universal Send & Archive Release

- Compose and reader replies now share one accessible Send options modal with
  immediate Send & Archive, scheduled archive-after-delivery, and
  `Cmd/Ctrl+Shift+Enter`; ordinary Send and new-message behavior are unchanged.
- The exact source and full reply provenance are validated at admission. One
  durable outbound stages one idempotent conversation-scoped mail action only
  after provider delivery confirmation. Undo/cancel/failure never archive.
- Final verification passed 715 backend tests with 56 expected skips, all 422
  frontend tests, a 588-module production build, generated `.example.test`
  provider/self-test and browser QA, and independent release review. Full
  evidence is in `UNIVERSAL_SEND_ARCHIVE_RELEASE_2026-08-30.md`. Production
  built the same 588 modules; all seven services and public health are healthy,
  Alembic remains `c6d7e8f9a0b1`, and anonymous outbound history is 401.

## Recent At a Glance Same-Port Browser Provisioning Release

- The first-class installer now retains the one selected port and exclusive Web
  Lock from exact four-segment flash/readback through reset, RET1 encrypted
  configuration/result, and activation polling. Raw Wi-Fi and device credential
  values remain browser-to-device; the API receives only hashes.
- Owner/same-origin pre-write cancellation supersedes only the exact attempt and
  candidate. A fresh old-generation handshake may safely retry; an observed
  target generation can reconcile one unique lost-result lineage without
  treating cable evidence as activation or replaying an uncertain write.
- Candidate.8 and its 31-case schema-2 HIL harness are exact on private firmware
  `main`; CI run `33349001516` passed. Application validation passed 716 backend
  tests with 65 expected skips, all 440 frontend tests, 29 disposable-PostgreSQL
  enrollment tests, and a 590-module build. Production remains locked with all
  enrollment/OTA tables empty and no serial chooser or device mutation. Full
  evidence is in
  `AT_A_GLANCE_RET1_BROWSER_PROVISIONING_RELEASE_2026-08-30.md`.

## Recent Focused/Split Inbox Release

- One PostgreSQL statement applies deterministic Focused/Other placement after
  exact conversation anchoring and before both section counts and pagination,
  preventing duplicate, missing, or drifting placement truth.
- The literal Inbox exposes visible Focused and Other sections, exact totals,
  stable reasons, responsive list/table presentation, persistent preference,
  and J/K, Shift+J/K, O, and Escape behavior. Generated Undo restores the exact
  row, selection, totals, and DOM focus.
- Final validation passed 696 backend tests with 56 expected skips, all 404
  frontend tests, fresh-c6 PostgreSQL placement/pagination checks, a 546-module
  build, independent review with no actionable P0–P2 findings, generated
  desktop/mobile browser QA, and authenticated aggregate-only production QA.
  Full evidence is in `FOCUSED_SPLIT_INBOX_RELEASE_2026-08-30.md`.

## Recent At a Glance Browser Transport & Owner Controls Release

- The browser installer now owns one user-selected Web Serial port under one
  exclusive Web Lock, probes exact ESP32-S3/flash/MAC identity, writes only the
  four signed preserve-config segments with erase-all disabled, reads every
  byte back, resets, and requires exact RET1 status-v2 identity on the same
  port. Existing signature, catalog, enrollment, revision, and HIL gates remain
  independent and default closed.
- Terminal Settings exposes read-only OTA capability blockers and per-device
  attempt history/detail plus owner-confirmed printed revision and cancellation
  only while an offer is still unstarted. It cannot create an offer, change
  rollout, fetch OTA artifacts, or write a device.
- Exact design/palette registries now validate every catalog declaration across
  Pillow, device, and browser rendering at import time. Existing output is
  pinned by exact pixel hashes; unknown values fail closed.
- Consolidated validation passed 101 focused backend checks, all 412 frontend
  tests, npm audit with zero vulnerabilities, and a 587-module build. Production
  remains at Alembic `c6d7e8f9a0b1`, with all seven services healthy, both OTA
  tables empty, and browser/OTA rollout gates false/empty. Full evidence is in
  `AT_A_GLANCE_BROWSER_TRANSPORT_RELEASE_2026-08-30.md`.

## Recent At a Glance OTA Control Plane Release

- Owner-idempotent attempts snapshot exact signed release, device, active
  credential, printed revision, source/target build and slot, fresh measured
  reserve, and deterministic cohort truth. Device lifecycle events append and
  project atomically; exact replay is safe and gaps remain non-promotion-quality.
- Candidate.7 adds the independently gated HTTPS/NVS coordinator, bounded
  content-addressed artifact verification, inactive-slot streaming, durable
  event replay, pending validation, and rollback/recovery reporting. All generic
  builds remain unkeyed and transport-disabled.
- Post-rebase validation passed 273 terminal/migration-head tests with 16
  expected skips; disposable PostgreSQL and `b5 → c6 → b5 → c6` passed. The
  protected production backup, deployment, empty-table/default-lock postflight,
  and remaining HIL gates are recorded in
  `AT_A_GLANCE_OTA_CONTROL_PLANE_RELEASE_2026-08-30.md`.

## Recent Conversation-First Inbox Release

- PostgreSQL now returns one exact owned-account conversation row after grouping
  and counting, with truthful totals, aggregate unread/star/attachment/label
  state, and active-Snooze exclusion in the ordinary Inbox query.
- The reader expands the full chronological account-scoped thread. List, table,
  bulk, reader, and keyboard actions use server-expanded durable conversation
  scope with Undo/retry/replay and later-intent-safe rollback.
- Final checks passed 684 backend tests with 51 intentional skips, all 392
  frontend tests, an eight-test disposable PostgreSQL gate, a 545-module build,
  and generated desktop/mobile browser QA with zero provider calls, rejected
  mutations, unknown routes, or console warnings/errors. Production built the
  same 545 modules; all services, health, authentication, and read-only row
  semantics passed with no post-start warning entries. Full evidence is in
  `CONVERSATION_FIRST_INBOX_RELEASE_2026-08-30.md`.

## Recent At a Glance Firmware Protocol & Installer Foundation Release

- Candidate.6 exposes a reset-only bounded RET1 status-v2 recovery window,
  recognizes a strict OTA1 offer without acting on it, and ships an executable
  E1001/E1002 qualification plan that requires bounded hashed evidence for all
  18 physical cases.
- The first-class At a Glance page now presents exact signed package/model/
  printed-revision gates, hashes all four preserve-config artifacts before any
  future connection, re-hashes prepared bytes at the write boundary, and
  distinguishes safe pre-write cancellation from recovery-required state.
- That foundation preceded the now-deployed gated Web Serial adapter; device
  access still cannot begin without signed, server-qualified, physically
  qualified release evidence. Consolidated terminal checks passed 261 backend
  tests with 12 expected skips, 59 frontend tests, a 541-module local build,
  and the exact firmware release gate. Full evidence is in
  `AT_A_GLANCE_FIRMWARE_PROTOCOL_INSTALLER_RELEASE_2026-08-30.md`.

## Recent Gmail Labels & Move Release

- Existing synchronized Gmail user labels are first-class across list, table,
  bulk, reader, `L`, and commands. Color chips use the owned account catalog;
  mixed-account and system-label mutations fail closed.
- Label actions expand across existing synchronized conversation messages.
  Literal-Inbox-only Move applies the destination and archives, active custom
  label removal drops the row, and accepted count, Undo, retry, focus, and lost
  response recovery stay durable.
- Consolidated validation passed 623 backend and 354 frontend tests, a
  539-module build, disposable PostgreSQL and migration gates, and generated
  desktop/mobile browser QA with zero provider calls. Full evidence is in
  `LABELS_AND_MOVE_RELEASE_2026-08-30.md`.

## Recent Universal Snooze Release

- Email exposes first-class **Snoozed** with one accessible picker across
  Inbox, reader, Flow, keyboard `H`, and commands. Explicit zoned quick/custom
  times, DST gap/fold handling, always/if-no-reply conditions, Undo,
  reschedule, Return now, Cancel, narrow layout, and focus recovery are live.
- Snooze is conversation-scoped and PostgreSQL-authoritative. Current Inbox
  siblings archive together, a later manual placement wins every return race,
  Cancel restores original placement, scheduled/explicit return adds Inbox,
  fresh sync gates the no-reply decision, and terminal provider failures
  release the active-conversation guard.
- Consolidated validation passed 603 backend and 335 frontend tests, a
  534-module build, 8 disposable-PostgreSQL lifecycle/race tests, the exact
  migration roundtrip, and generated desktop/mobile browser QA with zero
  provider calls. Full evidence and rollback boundaries are in
  `UNIVERSAL_SNOOZE_RELEASE_2026-08-30.md`.

## Recent First-Class At a Glance Release

- The primary `?page=at-a-glance` destination is live with catalog-driven
  view/design/profile selection, canonical previews, direct navigation, and
  terminal connection/battery/charge summaries.
- The everyday route consumes a credential-free, owner-scoped read API. Scoped
  HTML links and all terminal/firmware mutations remain in Settings.
- Consolidated checks passed 561 backend and 307 frontend tests; production
  built 526 modules. Full behavior, production, and rollback evidence is in
  `AT_A_GLANCE_FIRST_CLASS_RELEASE_2026-08-30.md`.

## Recent At a Glance Terminal Recovery-Evidence Release

- Firmware candidate.5 measures a bounded seven-sample battery burst, proves
  the complete runtime A/B table and source build identity, and validates or
  rolls back a pending image before enrollment, display, network, restart, or
  sleep work.
- The application rejects explicitly invalid battery bursts and parses strict
  RET1 status v2 identity. Candidate.4 status v1 stays compatible but cannot be
  treated as recovery-success evidence.
- Generic artifacts and every browser/OTA write path remain disabled and
  unkeyed pending physical E1001/E1002 qualification. Full evidence and
  rollback boundaries are in
  `AT_A_GLANCE_TERMINAL_RECOVERY_EVIDENCE_RELEASE_2026-08-30.md`.

## Recent Durable Replies Release

- Reader and Flow replies now commit locally before remote debounce, recover
  across close/reload/offline/cross-device use, and hand the same stable reply
  identity to full Compose.
- Drafts exposes a responsive metadata-only **Continue writing** surface.
  Navigation, mail actions, send, discard, and authentication transitions fail
  closed while reply durability or ownership is unresolved.
- The release was migration-free. Full checks, disposable PostgreSQL,
  generated-provider failure scenarios, and desktop/mobile browser QA passed;
  real production mail remained read-only.
- Complete behavior, code, verification, production, and rollback evidence is
  in `DURABLE_INLINE_REPLIES_RELEASE_2026-08-30.md`.

## Recent Scheduled Send Release

- Compose, reader replies, and Flow now share an accessible split Send control
  with explicit zoned quick choices and DST-safe custom times.
- Scheduled mail survives reload and device changes in a persistent manager
  with **Send now** and **Cancel & edit**. Cancel atomically restores the exact
  durable draft; Flow's archive-after-send intent is also server-durable.
- The release added no migration. Consolidated checks passed 563 backend and
  313 frontend tests; 13 disposable-PostgreSQL lifecycle tests and generated
  desktop/narrow browser QA also passed without real provider operations.
- Complete behavior, API, safety, verification, production, and rollback
  evidence is in `SCHEDULED_SEND_RELEASE_2026-08-30.md`.

## Recent Calendar Reliability Fix

- The recurring post-reauthorization Calendar failure was caused by Gmail
  narrowing the access token shared with Calendar during refresh.
- Runtime scopes are now centralized and derived from the account's recorded
  grant. Legacy Gmail-only accounts remain supported without inventing a
  Calendar grant.
- Remaining OAuth hardening is to validate a retained refresh grant explicitly
  and add compare-and-swap protection against stale token persistence; neither
  weakens the direct deployed recurrence fix.

## Historical Secure Terminal Enrollment Release

- The default-locked secure terminal enrollment foundation was introduced at
  runtime `8ff01848a2be2818dfd9eb88b84be9aab4befb0a`, with terminal revision
  `f3a4b5c6d7e8`.
- Full application checks, the exact migration cycle, deterministic PostgreSQL
  contention/lifecycle tests, Caddy validation, secret/diff review, and
  authenticated read-only production QA passed. The locked browser exposed no
  serial or write operation and left all enrollment state untouched.
- Full evidence and rollback boundaries are in
  `SECURE_TERMINAL_ENROLLMENT_FOUNDATION_RELEASE_2026-08-30.md`.

## Near-Term Terminal Queue

- Run the candidate.8 physical E1001/E1002 RET1, trusted TLS, A/B partition
  migration, interruption, pending-image validation, rollback, preserve-config,
  and ROM recovery HIL. E1004 remains blocked and single-slot.
- After complete HIL, use the offline promotion tool with a protected signing
  key, pin only its public key and positive catalog generation, and qualify the
  exact printed revisions before changing the browser gate.
- Keep RET1 provisioning and OTA rollout separately locked until their own
  interruption/recovery evidence is complete; browser-flash qualification must
  not imply OTA eligibility.

## Safety Constraints

- Production enrollment and OTA defaults are false/empty. Do not generate or
  stage the online P-256 private key, signed schema-2 release, positive catalog
  generation, browser trust key, or either HIL allowlist before qualification.
- Firmware release signing stays offline and independent from the future online
  enrollment key. Neither private key belongs in Git, browser code, artifacts,
  application logs, or progress documents.
- The shipped browser may request a port and fetch/hash firmware bytes only
  after exact
  signature, schema, model, printed-revision, preservation, and server-side
  qualification gates all pass. The current catalog cannot pass those gates,
  and production renders no Wi-Fi inputs or enabled Connect action. The build
  contains no erase-all path, trusted release key, or qualified catalog.
- Physical cable observation is not hardware attestation. MAC, model, chip
  revision, and firmware version are self-reported inventory fields.
- Real production mail and calendars remain read-only during terminal QA.
