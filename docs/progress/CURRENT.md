# Current Status

Last updated: 2026-08-30

## Active Objective

Complete and release the migration-free conversation-first Inbox milestone from
the exact terminal protocol baseline, while the isolated terminal track builds
the reserved `c6d7e8f9a0b1` OTA attempt/event ledger. Keep real mail/calendar QA
read-only except for generated `.example.test` fixtures and preserve every
terminal write gate.

## Baseline

- The deployed At a Glance firmware protocol/installer runtime is
  `84a854a5527c342b85bb2884ef43b89fea95a954`. The first-class page can select a
  signed release and exact physical model/revision, but artifact preflight is
  still server-qualification-gated and production device transport is
  source-hard-disabled. The pure OTA1 application contract has no route,
  persistence, scheduler, or device write.
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
- Production Alembic is `b5c6d7e8f9a0 (head)`, the Labels & Move child of
  Universal Snooze revision `a4b5c6d7e8f9`. The release widened only the
  durable mail-action audit constraint; aggregate label-action rows remained
  zero at release. Terminal credential and attempt tables remain empty, all
  four existing terminals remain legacy, and the secure-MAC unique index is
  present.
- All seven checked production services are active, public health is `ok`, and
  the replacement API process has zero automatic restarts and no post-start
  warning-or-higher entries. Production has no secure-enrollment or OTA
  enablement, online key, approved catalog, qualified release/model pair,
  durable OTA event ledger, or device update route.
- Private firmware `main` is
  `5db28243f8dc56309492ae926c0b5186a5fffeb7`
  (`0.2.0-candidate.6`). Exact-SHA run `33341323506` passed the complete
  software/reproducibility gate; the identical main-ref provenance run is
  `33342394221`. Generic bundles remain unkeyed, enrollment-disabled,
  OTA-disabled, and physically unqualified.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Items

### P1 — Conversation-first Inbox triage

- State: verifying; the authoritative row, full thread reader, conversation-
  scoped actions, and generated browser acceptance are complete and the release
  is migration-free.
- Scope: one account-safe conversation row across Inbox, mailboxes, and search;
  aggregate counts/state; chronological reader rail; conversation-wide bulk and
  row actions; J/K focus, O open, and Escape restoration. Focused/split placement
  remains the next independent slice.
- Acceptance: grouping/counting occurs before pagination; blank thread IDs never
  merge; cross-account reads fail closed; active Snoozes do not corrupt Inbox
  totals; actions preserve durable idempotency, Undo, retry, and generated-only
  QA boundaries.
- Next: push the reviewed commits, deploy without a migration, run read-only
  production postflight, and close the exact release record.

### P1 — Physical E1001/E1002 browser-install qualification

- State: candidate.6, the executable HIL evidence harness, exact browser package
  preflight, recovery workflow, and both OTA1 parsers are complete; production
  remains locked. No E1001/E1002 was attached during this release, and no
  device write, enrollment key, qualified catalog, or OTA offer was enabled.
- Scope: physical RET1 enrollment, interrupted serial/config write, three-slot
  selection, same-owner pending continuity, rollback grace, revocation,
  preserve-config, trusted-time/CA failure, A/B partition migration, inactive
  slot write, pending-image validation, power loss, automatic rollback, and ROM
  recovery on both models.
- Acceptance: repeatable recovery evidence proves a failed or interrupted
  enrollment, flash, or update cannot silently strand a terminal, disclose
  credentials, or replace the known-good slot. Only qualified exact
  release/model/hardware-revision tuples may enter either allowlist.
- Next: attach dedicated E1001/E1002 devices and execute the 18-case HIL record
  with bounded source evidence before importing Web Serial or adding a device
  OTA transport.

### P2 — Durable device OTA control plane

- State: isolated implementation is active from the exact `93b9375` baseline.
  Terminal revision `c6d7e8f9a0b1`, the direct child of current production head
  `b5c6d7e8f9a0`, is reserved exclusively for its attempt/event ledger. No merge
  or deployment has occurred.
- Scope: one additive event-ledger migration descending from b5, authenticated
  device offer/artifact/event endpoints,
  idempotent attempt state, power gates, rollout cohorts, and rescue controls.
- Acceptance: a restart or repeated request cannot duplicate or lose update
  truth, only exact HIL-qualified evidence is offerable, and no single flag can
  enable a write.
- Next: keep the implementation isolated from Inbox files and shared docs until
  the conversation release provides its exact GitHub/production closeout SHA.

## Pending Conversation-First Inbox Release

- PostgreSQL now returns one exact owned-account conversation row after grouping
  and counting, with truthful totals, aggregate unread/star/attachment/label
  state, and active-Snooze exclusion in the ordinary Inbox query.
- The reader expands the full chronological account-scoped thread. List, table,
  bulk, reader, and keyboard actions use server-expanded durable conversation
  scope with Undo/retry/replay and later-intent-safe rollback.
- Final checks passed 684 backend tests with 51 intentional skips, all 392
  frontend tests, an eight-test disposable PostgreSQL gate, a 545-module build,
  and generated desktop/mobile browser QA with zero provider calls, rejected
  mutations, unknown routes, or console warnings/errors. Full evidence is in
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
- Real Web Serial/esptool and device OTA transports remain absent. Consolidated
  terminal checks passed 261 backend tests with 12 expected skips, 59 frontend
  tests, a 541-module local build, and the exact firmware release gate. Full
  evidence is in
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

- Run the candidate.6 physical E1001/E1002 RET1, trusted TLS, A/B partition
  migration, interruption, pending-image validation, rollback, preserve-config,
  and ROM recovery HIL. E1004 remains blocked and single-slot.
- Add production Web Serial only after HIL, with a source-pinned browser signing
  key and the existing serial/provisioning/recovery gates still independent.
- After HIL, add the durable OTA event ledger and device-authenticated
  offer/artifact/event transport before considering cohorts or enablement.

## Safety Constraints

- Production enrollment and OTA defaults are false/empty. Do not generate or
  stage the online P-256 private key, signed schema-2 release, positive catalog
  generation, browser trust key, or either HIL allowlist before qualification.
- Firmware release signing stays offline and independent from the future online
  enrollment key. Neither private key belongs in Git, browser code, artifacts,
  application logs, or progress documents.
- The shipped browser may fetch and hash firmware bytes only after exact
  signature, schema, model, printed-revision, preservation, and server-side
  qualification gates all pass. The current catalog cannot pass those gates,
  and the build contains no serial request, Wi-Fi/configuration write, erase,
  esptool, or dynamic flashing transport.
- Physical cable observation is not hardware attestation. MAC, model, chip
  revision, and firmware version are self-reported inventory fields.
- Real production mail and calendars remain read-only during terminal QA.
