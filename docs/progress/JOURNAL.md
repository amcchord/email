# Progress Journal

Newest entries go first. Keep entries concise and factual. Never include
secrets, email contents, OAuth tokens, or raw private production data.

## 2026-08-30 — At a Glance same-port browser provisioning

### Scope

Complete the previously locked browser installer from exact preserve-config
flash through RET1 enrollment and authenticated activation while keeping every
production trust and physical-HIL gate closed. Do not attach or mutate a
terminal, install keys/catalogs, qualify hardware, enable OTA, or allocate a
migration.

### Completed

- Kept one explicit user-selected Web Serial port and one origin-wide Web Lock
  across exact four-segment write/readback, reset, RET1 status/hello,
  browser-local encrypted configuration/result, and scoped activation polling.
- Added owner/same-origin pre-write cancellation, safe same-generation reuse
  only after fresh physical proof, and observed-target-generation recovery for
  one unique lost-result lineage. Uncertain encrypted writes never replay
  automatically, and cable evidence never activates a credential.
- Advanced private firmware `main` to candidate.8 at
  `14f7046ae0253504f25972e9bc6ad952c1fa649f`. Its bounded configured-device
  window and schema-2 31-case secret-free HIL harness passed exact Actions run
  `33349001516`; the offline promotion tool is integrated but unused.

### Verification

- The consolidated application gate passed 716 backend tests with 65 expected
  skips, all 440 frontend tests, 29 disposable-PostgreSQL enrollment tests, and
  a 590-module production build.
- Signed-in, read-only production QA confirmed the first-class At a Glance tab,
  Browser terminal installer, locked enrollment/OTA blockers, zero Wi-Fi inputs,
  a disabled Connect action, and zero browser warnings/errors. No serial chooser,
  artifact request, terminal mutation, or real mail/calendar mutation occurred.

### Production Actions

- Fast-forwarded GitHub and production to application/runtime
  `739fe555d90dc9dd49ffdea28fc165ed2b0f7089`, built 590 frontend modules, and
  replaced only `mailapp`. No migration, backup, worker, Caddy, key, catalog,
  firmware promotion, or terminal action was required.
- All seven checked services are active and public health is `ok`. Replacement
  mailapp PID 2135271 has zero automatic restarts and no warning-or-higher entry
  after 02:00:12 UTC. The retired process emitted only the host's three known
  systemd timeout/kill/result lines.
- Production is exact and clean at the runtime boundary; Alembic remains
  `c6d7e8f9a0b1 (head)`. Anonymous enrollment and OTA capability reads return
  401, and aggregate enrollment-attempt, device-credential, OTA-attempt, and
  OTA-event counts all remain zero.

### Next

Attach dedicated E1001/E1002 hardware and execute the 31-case schema-2 record
before any protected signing ceremony, catalog/key installation, release/model
qualification, browser enablement, or OTA canary.

## 2026-08-30 — Universal Send & Archive

### Scope

Extend the existing durable post-delivery archive intent from Flow to full
Compose and inline replies without changing ordinary Send, new-message
behavior, Gmail provider code, terminal work, or the database schema.

### Completed

- Added exact-source-gated Send & Archive, scheduled archive-after-delivery,
  `Cmd/Ctrl+Shift+Enter`, persistent scheduled status, truthful copy, modal
  focus/Escape handling, and one-shot recovery semantics.
- Made the post-delivery action conversation-scoped, deterministic, and safe
  when Gmail history removes the original source before scheduled delivery.
  Undo/cancel restores the original durable draft identity instead of creating
  a conflicting second reply.
- Extended the localhost-only `.example.test` fixture with current conversation
  APIs, exact provenance checks, archive audit counters, and undo/cancel/
  confirmed-delivery self-test coverage.

### Verification

- `make check`: 715 backend passed with 56 expected skips; 422 frontend passed;
  production build transformed 588 modules.
- Generated provider self-test proved zero archives for Undo/cancel, one archive
  only after generated delivery, zero external network calls, and no unexpected
  mutations. Browser QA verified new-message fail-closed behavior, reply modal
  focus/Escape, visible Send & Archive/scheduled intent, and generated Undo.
- Independent review found no P0 and its conversation scope, deleted-source,
  inline error, and stale assertion findings were closed before the final gate.

### Production Actions

- Fast-forwarded GitHub `main` and production through the release docs with
  exact application/runtime commit
  `c7171466d075fc74f12ccb47fb2ee2d27ec830a6`. Restarted only `mailapp`, then
  built 588 frontend modules. No migration, backup, dependency install, worker,
  Caddy, terminal, or provider action was required.
- The retired API process hit the host's known graceful-stop timeout; the
  replacement is active with PID 2134395 and zero automatic restarts. The only
  warning-priority entries were the three systemd timeout/kill/result lines;
  there were no application warning identifiers.
- All seven checked services are active, public health is `ok`, production Git
  is exact and clean, Alembic remains `c6d7e8f9a0b1 (head)`, and anonymous
  outbound history returns 401.

### Next

Begin Personal Snippets from the final terminal baseline instead of reopening
this frozen release for additional polish.

## 2026-08-30 — At a Glance browser transport, owner controls, and design registry

### Scope

Promote the existing signed-package and OTA foundations into real, still
independently locked operator software: a pinned browser transport, owner OTA
inspection/rescue controls, fail-loud design registration, and an offline
HIL-bound signing path. Do not qualify hardware, install a key/catalog, enable a
write, allocate a migration, or mutate a terminal.

### Completed

- Added pinned `esptool-js@0.6.1` behind the existing source-signature,
  enrollment, catalog, printed-revision, and HIL gates. One explicit click
  selects the port; one exclusive Web Lock covers ROM and application phases;
  only the four signed preserve-config segments are written with erase-all
  disabled; byte-for-byte readback, hard reset, and exact same-port RET1
  status-v2 identity are required before success.
- Added terminal-owner Settings controls for read-only OTA capability blockers,
  printed-revision confirm/clear, attempt history/detail, and cancellation only
  for `offered` sequence-zero attempts. The surface cannot create offers, change
  enablement/rollout, fetch OTA artifacts, or access a device transport.
- Replaced implicit Editorial/palette fallbacks with immutable exact Pillow
  registries and catalog/device/web completeness checks. Unknown or incomplete
  designs now fail closed; exact pixel hashes preserve existing Home
  Editorial/Swiss and Day Ahead Editorial output.
- Added private firmware branch `codex/firmware-promotion-tool` at
  `aadac9d6dbb0afc0e115db3528251691a93c6fc5`. Its offline tool consumes the
  immutable candidate plus complete revision-bound E1001/E1002 HIL records,
  preserves firmware bytes, signs the exact schema-2 manifest/schema-1 catalog
  tree, and keeps E1004 and all OTA eligibility false. No real key or evidence
  was used and firmware `main` remains candidate.7 `ea3547b`.

### Verification

- Rebased the three migration-free application slices onto exact Focused/Split
  closeout `e2fdffd562f125c341703042620e09e9b96c8aa5` with no shared-shell
  conflict. Focused backend gate: 101 passed. Full frontend: 412 passed.
- `npm ci` and audit reported zero vulnerabilities; the exact production build
  transformed 587 modules. `git diff --check` passed. The isolated design gate
  had passed 133 checks and the offline promotion tool had passed 20 safety
  checks before integration.
- No E1001/E1002 serial port was attached. No browser chooser, device write,
  enrollment, signing ceremony, release qualification, OTA attempt, provider
  call, or real mail/calendar mutation was performed.

### Production Actions

- Fast-forwarded GitHub `main`, the integration branch, and production from
  exact Focused closeout `e2fdffd` to application/runtime
  `fdc766c234c02e5cd7d59df453691e8bc39eadbc`. Installed the locked frontend
  dependency, built 587 modules, and restarted only `mailapp`; Alembic remained
  exactly `c6d7e8f9a0b1` and no backup, migration, worker, Caddy, or database
  write was required.
- The retired API process reached the host's known graceful-drain timeout. The
  replacement became active at 01:14:33 UTC as PID 2133109 with zero automatic
  restarts and no warning-or-higher entries after 01:14:34. All seven checked
  services are active and public health is `ok`.
- Production remains exact and clean. Browser flashing is false, trusted
  release-key count is zero, OTA enablement is false, rollout is zero, and both
  OTA tables remain empty. Anonymous firmware catalog, OTA capability, and RET1
  enrollment reads remain 401. The production bundle contains the new owner
  control and gated transport surfaces, but no gate can currently authorize a
  port or write.

### Next

Attach dedicated E1001 and E1002 devices, record their exact printed revisions,
execute the complete browser/RET1/A-B/OTA interruption and recovery matrix, and
only then perform the protected offline signing ceremony and separately review
browser enrollment and OTA canary enablement.

## 2026-08-30 — Focused/Split Inbox implementation

### Scope

Turn the former message-level ignored-category toggle into one truthful,
explainable Focused/Other projection over the authoritative owned-account
conversation row, without a migration, AI-provider call, or Gmail move.

### Completed

- Added post-anchor, pre-count/pagination server placement with stable reasons,
  account/thread-scoped later-reply suppression, trusted-contact and delegated-
  scheduling alignment, and a fail-visible unclassified default.
- Added exact independent section totals/pages, disjoint-response validation,
  responsive list/table sections, reason chips, truthful empty states, a
  stateful accessible Split control, and Shift+J/K section navigation while
  preserving J/K/O/Escape behavior.
- Preserved optimistic conversation actions, section counts, Undo/retry/replay,
  split preference across reload, and explicit DOM-focus restoration after an
  Undo removes its toast control.

### Verification

- Consolidated backend: 696 passed with 56 expected skips. Consolidated
  frontend: 404 passed. Production frontend build: 546 modules.
- Focused backend: 43 passed. Fresh disposable PostgreSQL at exact Alembic
  `c6d7e8f9a0b1`: 2 passed for newest-anchor precedence, disjoint totals,
  trusted/delegated/subscription/unclassified policy, and sent-reply scope.
- Generated `.example.test` self-test passed seven exact conversations split
  4 Focused/3 Other, full union/disjointness, Undo, and zero provider calls.
  Desktop list/table and 390-by-844 browser QA passed exact counts, visible
  reasons, J/K/Shift+J/Shift+K/O/Escape, responsive overflow, Split reload
  persistence, and generated archive/Undo. Browser warnings/errors, rejected
  mutations, and unknown routes were zero.
- Independent release review closed the two-request classifier race, stale
  delegated needs-reply contradiction, cross-page reclassification duplicate,
  same-section removal/Undo focus loss, empty-page total drift, and table-header
  semantics. Final review reported no remaining actionable P0–P2 findings.

### Production Actions

- Fast-forwarded GitHub `main`, the feature branch, and production to exact
  reviewed application/runtime `dea8117f5b5348d8c4d3f78e0e6af08273a6367d`.
  Production built 546 frontend modules; Alembic remained exactly
  `c6d7e8f9a0b1` and no backup, migration, dependency, worker, Caddy, or terminal
  change was required.
- The retired API process exhausted its graceful-drain timeout at the
  replacement boundary. Replacement PID 2132116 is active with zero automatic
  restarts and no warning-or-higher entries after its 01:03:15 UTC start. All
  seven checked services are active, public health is `ok`, and anonymous split
  access is 401.
- Authenticated aggregate-only production QA showed both sections, exact
  nonzero totals, 25 visible reason-labelled rows in each, and zero browser
  warning/error entries. No real message was opened or mutated.

### Next

Monitor the released projection and continue product work from the exact docs
closeout while preserving the terminal OTA owner-UI rebase boundary.

## 2026-08-30 — At a Glance OTA control plane and firmware coordinator

### Scope

Add the durable, idempotent, independently gated OTA offer/artifact/event path
and a real default-disabled firmware HTTPS/NVS coordinator without authorizing
a physical write.

### Completed

- Added Alembic `c6d7e8f9a0b1` with explicit terminal hardware-revision and
  coherent OTA telemetry fields, one-active-attempt enforcement, immutable
  release/source/cohort snapshots, and append-only device events.
- Added owner-idempotent create/read/cancel, active-credential schedule offers,
  exact descriptor/signature/application delivery, bounded duplicate-free
  event ingestion, runtime slot/build/boot validation, gap tracking, and
  schedule ETags that include offer identity.
- Added firmware commit `949bc87` with an independent transport compile gate,
  strict scoped HTTPS fetches, signed/content-addressed inactive-slot writes,
  fresh 4000 mV/80% measured reserve at the write boundary, CRC-protected NVS
  attempt/event replay, pending validation, and rollback/recovery reporting.
  Advanced the isolated branch to candidate.7 at `ea3547b`.

### Verification

- Focused server gate: 158 passed with 16 expected skips. Fresh disposable
  PostgreSQL OTA gate: 4 passed. Migration round-trip `b5 → c6 → b5 → c6`
  passed.
- Exact post-Conversation-rebase gate: 273 passed with 16 expected skips;
  formatting, compilation, and `git diff --check` passed.
- Firmware host safety, generic E1001/E1002/E1004 builds, and keyed E1002
  coordinator build passed at `949bc87`. Candidate.7 exact-SHA Actions run
  `33344430605` subsequently passed and private `main` was promoted to exact
  `ea3547b8bdb96cd27a4b14f4ed0ce662445944b4`.

### Production Actions

- Retained validated pre-migration backup
  `/var/backups/mailapp/maildb-pre-terminal-ota-20260831T0019Z.dump`, 1,383,737,691
  bytes, mode `0600`, SHA-256
  `5d05849d9197b3a2ad513cee0c4263b7efe9869bc8e20dc430f0ffb83a13b80e`.
- Fast-forwarded production from Conversation closeout `075a475` to exact app
  runtime `9253eb4`, applied only `b5 → c6`, and replaced only `mailapp`.
- The retired API process exhausted graceful drain; replacement PID 2130573 is
  active with zero restarts and no warning+ entries after its start boundary.
  All seven services and public health are healthy; anonymous OTA reads are
  401; both OTA tables are empty; enablement is false, rollout is zero, and
  qualified-release count is zero.

### Next

Require the physical E1001/E1002 18-case migration/interruption/rollback/
recovery/rescue record before installing an eligible descriptor, confirming a
revision, or enabling one canary cohort.

## 2026-08-30 — Conversation-first Inbox implementation

### Scope

Replace message-duplicated Inbox presentation with one authoritative owned-
account conversation row, full chronological thread reading, and durable
conversation-scoped actions without a schema change or real-mail mutation.

### Completed

- Added server-side grouping/counting before pagination, typed fallback identity
  for blank thread IDs, aggregate unread/star/attachment/label state, exact
  account ownership, and server-side active-Snooze exclusion for Inbox totals.
- Added the account-scoped full-thread reader and one conversation row across
  normal mailboxes and search. Drafts, Snoozed, and Needs Reply retain their
  specialized existing projections.
- Added additive `scope=conversations` durable mail actions that expand and lock
  every current exact conversation member while preserving default message-
  scope payload hashes, idempotent replay, retry, Undo, and later-intent-safe
  optimistic rollback.
- Added J/K focus, O open, Escape close/focus restoration, aggregate labels and
  counts, stale-append invalidation after row removal, and responsive 44-pixel
  reader controls.

### Verification

- Consolidated `make check`: 684 backend passed with 51 intentional skips; 392
  frontend passed; production build transformed 545 modules.
- Focused backend: 104 passed. Focused frontend: 36 passed. Disposable
  PostgreSQL conversation and mail-action gate: 8 passed.
- Generated `.example.test` self-test and desktop/390-by-844 browser QA passed
  the seven-row projection, two-message chronological expansion, J/K/O/Escape,
  generated star plus Undo, focus restoration, and narrow reader. Browser logs
  contained only Vite connection debug messages; provider calls, rejected
  mutations, and unknown routes were zero.
- Independent release review reported one P1 and two P2 issues; whitespace-only
  thread expansion, page-local Snooze totals, and stale append/removal races were
  all corrected before this record.

### Production Actions

- Pushed the feature branch and fast-forwarded GitHub `main`, then production,
  from exact terminal docs baseline `93b9375b04dde8687421272a987c7590a89a8d47`.
  Exact application/runtime code boundary is
  `f5be5851ae7c5e628e490223c50deb0be1c9c9b2`; production first received the
  release-record commit `e4f2ac249d9d6a18c7a20fafedc7f7265db26bc1`.
- Restarted only `mailapp`, then built the frontend after the replacement API
  was active. The retired API again reached the host's known graceful-drain
  timeout; the replacement became active at 00:11:15 UTC with `NRestarts=0`.
  The API and workers have no warning-or-higher entries after 00:11:16 UTC.
- Production remained at Alembic `b5c6d7e8f9a0 (head)`; no migration, database
  backup/restore, dependency install, worker restart, Caddy change, or real-mail
  mutation occurred. All seven services are active, public health is `ok`, and
  anonymous conversation-list access returns 401.
- Authenticated read-only browser QA loaded 50 visible Inbox rows and confirmed
  all 50 expose conversation semantics. No row was opened and no mail action was
  submitted; browser warnings/errors were zero.

### Next

Build focused/split Inbox placement as policy over the shipped conversation row.
Preserve the terminal team's exclusive `c6d7e8f9a0b1` migration and coordinate
shared Inbox/docs files before the next release.

## 2026-08-30 — At a Glance firmware protocol and installer foundation

### Scope

Advance browser-install and OTA implementation to exact executable protocol,
package, recovery, and physical-evidence boundaries without enabling a real
device write.

### Completed

- Released private firmware candidate.6 at
  `5db28243f8dc56309492ae926c0b5186a5fffeb7` with a strict reset-only bounded
  RET1 status-request window, pure OTA1 offer/event/replay parsing, and no OTA
  transport or persistent update action.
- Added an executable E1001/E1002-only HIL planner/validator for the exact
  preserve-config four-segment bundle and complete 18-case evidence record.
  Every passing case must reference a real bounded file under the evidence root
  whose SHA-256 is revalidated.
- Added pure application OTA1 contracts and an exact browser install workflow.
  The first-class At a Glance page now exposes signed release/model/printed-
  revision selection, four-artifact byte/hash preflight, immutable prepared
  package revalidation, workflow/recovery state, and explicit cleanup.
- Kept device transport source-hard-disabled. No Web Serial request, esptool,
  firmware write, OTA route, durable ledger, migration, online key, approved
  catalog, or HIL allowlist was added.

### Verification

- The consolidated app gate passed 261 terminal backend tests with 12 expected
  opt-in skips, 59 terminal frontend tests, a 541-module local production
  build, and `git diff --check`.
- Firmware passed 29 tooling tests, enrollment/RET1 and OTA1 host suites,
  E1001/E1002/E1004 builds, two clean all-model reproducible release builds,
  and exact manifest SHA-256
  `fb1e7fb35a077356a6e36ed3a790e60ace2d5d5573ae3d23822d697e7b385ef7`.
- Exact-SHA Actions run `33341323506` passed keyed protocol compiles, all-model
  reproducibility, manifest verification, and immutable bundle publication.
  Identical main-ref provenance run `33342394221` was queued after promotion.

### Production Actions

- Pushed and deployed exact application/runtime
  `84a854a5527c342b85bb2884ef43b89fea95a954` and promoted private firmware
  `main` to exact candidate.6 SHA
  `5db28243f8dc56309492ae926c0b5186a5fffeb7`.
- Production fast-forwarded cleanly from the Labels docs baseline, built 543
  frontend modules, and remained at Alembic `b5c6d7e8f9a0 (head)`. No service
  restart, dependency install, migration, database write, Caddy change, or
  physical firmware installation occurred.
- All seven services remained active, public health returned `ok`, and the
  post-deploy warning-or-higher service log was empty. Read-only authenticated
  browser QA showed first-class Terminal firmware, `Transport locked`, and
  disabled Verify/Connect controls with zero console warnings/errors and no
  download, serial prompt, mail action, or terminal mutation.

### Next

Attach dedicated E1001/E1002 devices and execute the candidate.6 18-case HIL
record. Only exact passing release/model/revision tuples may unlock a future
source-pinned Web Serial adapter or inform the post-b5 durable OTA ledger.

## 2026-08-30 — Gmail Labels & Move release

### Scope

Promote existing synchronized Gmail user labels into durable, account-safe,
conversation-wide Label and literal-Inbox-only Move workflows without mutating
real mail during QA.

### Completed

- Added direct a4 child revision `b5c6d7e8f9a0`, durable `add_label`,
  `remove_label`, and `move_to_label` audit names, owned user-label validation,
  conversation expansion, exact stored provider deltas, replay-stable
  idempotency, and authoritative validated catalog pruning.
- Added shared list/table/bulk/reader label controls, `L`/`V`, searchable
  account-aware picker, safe color chips, active-mailbox projection, accepted
  counts, Undo/retry/reconciliation, modal keyboard ownership, focus recovery,
  and responsive reader/bottom-sheet layouts.
- Constrained Move to the literal Inbox UI and explicit Inbox anchors. Sent or
  archived conversation siblings remain valid and receive the same exact
  destination/removal delta.
- Extended the generated `.example.test` mail-action fixture and exact boundary
  self-test; no real Gmail or calendar mutation was used.

### Verification

- Final consolidated gate passed 623 backend tests with 49 intentional skips,
  all 354 frontend tests, and a 539-module production build.
- Focused backend passed 60 tests; disposable PostgreSQL and exact migration
  roundtrip/downgrade-delta gates passed. Final focused frontend gate passed 37
  tests.
- Generated desktop/mobile browser QA passed conversation apply/remove/Move,
  active-label row removal, Undo, mixed-account refusal, modal shortcut
  isolation, focus, responsive UI, zero console warnings/errors, zero provider
  calls, and zero unknown routes.

### Production Actions

- Pushed and deployed exact application/runtime
  `a440801c18c8377b50a225af71f3937caa78c7af`.
- Validated the 1,383,741,356-byte pre-b5 backup
  `/var/backups/mailapp/maildb-pre-labels-move-20260830T232001Z.dump` with
  SHA-256
  `9c5cd5876d242b78aae394c5f563beaa1e35d398f8015f24d1bb770555bd004c`.
- Upgraded exactly `a4 → b5`, restarted only the API and two workers, and built
  539 frontend modules. The retired API hit the known graceful-stop timeout;
  the replacement and both workers have zero restarts and no warning-or-higher
  entries after their replacement boundary.
- Production Git is exact/clean, Alembic is b5, all seven services and public
  health are healthy, anonymous label-catalog access is 401, aggregate label
  actions remain zero, and authenticated browser QA confirmed the two command
  entries without opening or mutating real mail.

### Next

Build the smallest conversation-first Inbox row and split/focused placement
slice on this durable label/account foundation; coordinate before allocating a
child of b5 or editing terminal-owned files.

## 2026-08-30 — At a Glance terminal recovery evidence

### Scope

Advance candidate.5 battery and A/B recovery evidence on the coordinated
Universal Snooze baseline without enabling a browser or device write path.

### Completed

- Released private firmware candidate.5 at
  `f23d6302ae4bc64326f385fe44593e2ec47febd0` with a bounded seven-sample battery
  quality burst, full `ab-v1` runtime-table proof, source build identity, strict
  RET1 status v2, and an early pending-image validate-or-rollback gate.
- Taught the application to exclude explicitly invalid battery readings and
  accept exact status v1/v2 shapes without treating legacy v1 as recovery
  identity evidence.
- Kept generic firmware unkeyed and disabled. Browser Serial, artifact writes,
  OTA offers/events, production trust keys, HIL allowlists, and E1004 OTA remain
  absent.

### Verification

- The consolidated application gate passed 607 backend tests with 47 expected
  skips, 336 frontend tests, and a 532-module local production build.
- Firmware tooling, OTA host safety, enrollment, keyed synthetic compile/marker,
  clean all-model build, packaging, manifest, and disabled/unkeyed artifact
  checks passed. Exact-main Actions run `33338824057` passed the complete
  candidate.5 software gate.
- Authenticated production browser QA loaded the empty first-class Snoozed
  mailbox and At a Glance read-only. No message or real mutation was used.

### Production Actions

- Deployed exact combined runtime
  `35e3700e8a22eabf49e701fb873d4662d5b7abdc` after validating the coordinated
  pre-Snooze database backup.
- Applied only Universal Snooze migration `a4b5c6d7e8f9`, built 534 frontend
  modules, and restarted the API and workers. The terminal slice is
  migration-free.
- Exact clean Git, Alembic head, all seven services, public health, zero
  post-start warning-or-higher logs, anonymous Snooze 401, and aggregate-empty
  Snooze state passed. The retired API stop timeout occurred before the new
  process boundary.

### Next

Run the physical E1001/E1002 enrollment, TLS, A/B migration, interruption,
rollback, power, preserved-configuration, and ROM-recovery matrix before adding
Web Serial or the durable OTA ledger and transport.

## 2026-08-30 — Universal Snooze release

### Scope

Deliver a durable, first-class Snooze/Remind Later workflow across Email and
Flow using only generated `.example.test` browser mutations during QA.

### Completed

- Added the direct `f3a4b5c6d7e8` child migration `a4b5c6d7e8f9`, one active
  reminder per owned account/conversation, durable leases/retry, exact
  idempotency recovery, fresh-sync no-reply gating, and ordered bulk
  archive/Inbox-return work through the existing mail-action outbox.
- Added first-class Snoozed navigation, shared accessible zoned/DST-safe
  picker, always/if-no-reply conditions, `H`, commands, Flow support,
  conversation-level optimistic projection, ten-second Cancel-backed Undo,
  reschedule, Return now, error reconciliation, focus recovery, and responsive
  management states.
- Extended the local generated-mail fixture with sibling conversations, fake
  time, active-thread conflict, original-placement Cancel, Sent-only Return
  now, reply suppression, protected mailboxes, provider counters, and an exact
  boundary self-test.

### Verification

- Consolidated validation passed 603 backend tests with 47 intentional skips,
  all 335 frontend tests, and a 534-module production build. Focused backend
  and mail-action coverage passed 53 tests; the final Snooze-focused frontend
  pass completed 22 tests.
- Eight disposable-PostgreSQL tests passed conversation, race ordering,
  placement, partial-failure, terminal-failure, and fresh-sync behavior. The
  exact `f3 → a4 → f3 → a4` migration roundtrip passed.
- Generated desktop and 390-by-844 browser QA passed full-conversation hide and
  Undo restoration, first-class Snoozed, reschedule/Return now, `H`, focus,
  dialog, and console checks. Provider calls, rejected mutations, and unknown
  fixture routes were zero; no real mailbox or calendar data was mutated.

### Production Actions

- Pushed exact Snooze application/runtime
  `231173b2d18966b603ed2f824f68380f8087de2c`. A migration-free terminal
  integration produced combined runtime
  `35e3700e8a22eabf49e701fb873d4662d5b7abdc` for one coordinated deployment.
- Created and validated the 1,383,720,058-byte pre-a4 backup
  `/var/backups/mailapp/maildb-pre-universal-snooze-20260830T2224Z.dump`
  (SHA-256
  `049ad0aae0b0cb3ee4cc3b2e34585cd5fe248b1654fbd2127d42a195b2a9ec16`).
  Production upgraded exactly `f3 → a4`, restarted the API and both workers,
  and built 534 frontend modules.
- All seven checked services and public health are healthy; affected services
  have no warning-or-higher entries after the replacement boundary, anonymous
  Snooze access is 401, and the aggregate Snooze row count is zero.
  Authenticated read-only QA loaded empty first-class Snoozed and At a Glance
  without opening mail or causing a mutation.

### Next

Continue from the combined a4 baseline. Reuse the one durable conversation
lifecycle for future auto-reminders or reminder defaults; do not add browser-
only or AI-only timers.

## 2026-08-30 — At a Glance firmware and battery safety release

### Scope

Advance terminal reliability, battery guidance, trusted firmware verification,
and OTA architecture without enabling browser Serial, device writes, firmware
artifact downloads, OTA offers, or a schema change.

### Completed

- Released private firmware `0.2.0-candidate.4` with fresh bounded SNTP,
  ISRG X1/X2 CA and hostname validation, no plaintext/redirect downgrade,
  exact E1001/E1002 `ab-v1` partitions, an inactive-slot-only Ed25519 OTA
  writer, and pending-image valid/rollback primitives. The OTA path remains
  compile-time disabled and is not invoked by the device loop.
- Replaced naive battery extrapolation with bounded six-hour medians and a
  robust discharge slope, 90-day history, direction/error guards, one-year
  horizon suppression, coarse confidence copy, and honest
  `possible_charging` behavior without an external-power signal.
- Added exact browser SHA-256/Ed25519 verification of manifest/signature bytes
  against pinned toolchain/model/partition contracts. The production key map is
  empty, and the browser still contains no firmware-artifact or serial write
  path.
- Added a fail-closed OTA policy core and authenticated read-only capability
  endpoint. Independent enablement, exact descriptor/parent evidence, physical
  HIL allowlist, positive catalog generation, model eligibility, and durable
  event persistence are all required; no offer, artifact, or event route exists.

### Verification

- Application validation passed 591 backend tests with 35 expected skips. The
  frontend run passed 320 tests and exposed one stale source-surface assertion;
  its exact read-only endpoint contract was corrected and re-run green. The
  local production build transformed 528 modules.
- Firmware validation passed 22 host tests plus enrollment/TLS/layout checks,
  PlatformIO builds for E1001/E1002/E1004, exact-commit run `33335099281`, and
  exact-main run `33336177159`, including keyed RET1, all-model,
  reproducibility, manifest, and immutable-bundle gates.
- Diff/secret/write-path review passed. No signing key, credential, device
  artifact, enabled flag, serial request, migration, dependency, Caddy, or
  systemd change was introduced.

### Production Actions

- Rebased onto Scheduled Send closeout
  `584e3e0c52f209c6e93e6a7abdaf93727548fbba`, pushed GitHub `main`, and
  deployed exact runtime `92d22a54c49ec9b4ba74042ece01a1c6d527ea07`.
- Restarted only `mailapp` and built a 530-module frontend. The retired API hit
  its known bounded graceful-stop timeout; the replacement has zero restarts
  and no post-start warning-or-higher entries. All seven services and public
  health are healthy, anonymous OTA capability access is 401, production Git
  is clean, and Alembic remains `f3a4b5c6d7e8 (head)`.
- Authenticated read-only QA verified honest learning/stale battery copy and the
  locked OTA/browser installer blockers. No terminal, firmware, display,
  enrollment, mail, calendar, or database state was mutated.

### Next

Run the physical E1001/E1002 enrollment, TLS, A/B migration, update,
interruption, rollback, power, and ROM-recovery matrix. Only after that evidence
exists should Web Serial or a durable device OTA control plane be implemented.

## 2026-08-30 — Durable Scheduled Send release

### Scope

Deliver future email scheduling as one durable outbound workflow across
Compose, the message reader, and Flow, without a schema change or real-mail QA.

### Completed

- Added explicit zoned quick choices, DST-safe custom scheduling, accessible
  desktop/mobile split-send controls, sparse status polling, and a persistent
  reload/cross-device Scheduled mail manager with Send now and Cancel & edit.
- Extended the PostgreSQL outbox with exact deferred delivery, idempotent
  cancellation, due-time row-lock ownership, draft restoration/reuse, Send-now
  advancement, and prompt sent-draft discard.
- Made Flow's default archive-after-send intent a deterministic durable mail
  action staged after provider confirmation and before terminal outbound truth,
  so browser reload cannot drop it.
- Expanded the localhost-only `.example.test` provider fixture with fake time,
  scheduled lifecycle routes, provider-call counters, and a deterministic
  exact-boundary/cancel/recovery/Send-now self-test.

### Verification

- The corrected consolidated gate passed 563 backend tests with 39 intentional
  opt-in skips, all 313 frontend tests, and a 529-module local production build.
- All 13 disposable-PostgreSQL outbound tests passed, including cancel-edit-
  resend, due-time, early Send now, terminal preflight recovery, and idempotent
  post-send archive coverage.
- Generated desktop and 390-by-844 browser QA scheduled, navigated/reloaded,
  cancelled, and recovered the exact draft with zero provider lookups/sends,
  unknown routes, unexpected mutations, or external fixture calls. No real
  mailbox, calendar, provider draft, or email send was used.

### Production Actions

- Pushed and deployed exact application/runtime
  `8b0f1c974ecc3c52a0a5e48a0cbe3e61c5eb2ae6` from clean baseline
  `f0f80919b63cc18bc98e47f3bab05df3f29a327c`.
- Restarted `mailapp`, `mailworker`, and `mailworker-cron`, then built the exact
  529-module frontend. The retired API exceeded its graceful-stop deadline;
  replacement API/workers are active with zero restarts and no post-start
  warning-or-higher entries.
- Exact clean Git, all seven services, public health `ok`, anonymous scheduled
  endpoint 401, and unchanged Alembic `f3a4b5c6d7e8 (head)` were verified.

### Next

Resume product improvements from this shared-shell baseline. Preserve the
terminal-owned follow-on files while its isolated battery/firmware work lands.

## 2026-08-30 — First-class At a Glance release

### Scope

Promote At a Glance from a Settings-only management section to a discoverable,
authenticated primary application destination while keeping terminal
credentials, firmware, Serial, and destructive actions out of the daily route.

### Completed

- Added the `at-a-glance` lazy route, direct primary tab, tablet/mobile label
  behavior, command-palette registration, and unique `g g` shortcut.
- Added a catalog-driven 16:9/9:16 experience with canonical previews, current
  Editorial/Swiss/Day Ahead/Clock designs, explicit loading/error/empty states,
  session/request generation guards, and Settings handoff for scoped HTML
  display links.
- Added owner-scoped connection, battery, runtime, charge, learning, stale,
  pending, review, and revoked summaries without raw identifiers or credentials.
- Added credential-free authenticated experience/preview endpoints. The read
  path neither exposes nor mints shared codes, display tokens/URLs, HA values,
  firmware artifacts, or terminal credentials.

### Verification

- Consolidated validation passed 561 backend tests with 35 skips and all 307
  frontend tests. Local build transformed 524 modules; production transformed
  526 and emitted the At a Glance lazy chunk.
- Authenticated read-only production QA loaded the direct route, primary tab,
  view/design/profile controls, canonical preview, management handoff, and
  charge notice. Anonymous experience access returned 401. No real state was
  mutated.

### Production Actions

- Rebased onto exact Calendar docs-closeout
  `e4da24a37dcfcea02fa0d888315cbe4e96b89111`, then pushed and deployed exact
  application/runtime `945b71860e08d79e6ddeb5e3faccffe372418ff1`.
- Restarted only `mailapp`. The retired process exceeded its graceful-stop
  window; the replacement is active with zero automatic restarts. All seven
  services and public health are healthy; Git is clean and Alembic remains
  `f3a4b5c6d7e8 (head)`.
- Recorded the complete release in
  `AT_A_GLANCE_FIRST_CLASS_RELEASE_2026-08-30.md`.

### Next

Move to physical E1001/E1002 enrollment/recovery HIL. Keep browser Serial,
device writes, enrollment keys, firmware flashing, and OTA locked until that
matrix passes; then address trusted device TLS and signed A/B OTA.

## 2026-08-30 — Preserve Calendar scope across Gmail refresh

### Scope

Stop successful Google Calendar reauthorization from failing again after the
next Gmail token refresh, without changing account data, calendar data, mail,
AI, terminal behavior, or the frontend.

### Completed

- Confirmed Gmail and Calendar persist one shared account access token, while
  Gmail requested only its four Gmail scopes during refresh. That deterministic
  narrowing caused Calendar `insufficient_scope`, local scope removal, and the
  recurring reconnect prompt.
- Centralized runtime data scopes. Gmail and Calendar now request the identical
  recorded grant; Calendar is included only when the account records it, so
  legacy Gmail-only accounts continue to refresh safely.
- Kept token-expiry behavior unchanged after review found that adding a stored
  aware expiry without atomic refreshed-expiry persistence would create churn
  and datetime compatibility risk.

### Verification

- Focused OAuth/runtime coverage passed 28 tests. The single release gate
  passed 552 backend tests with 35 intentional PostgreSQL/external skips.
- Two independent read-only audits confirmed the recurrence mechanism and the
  direct fix. No P0 was found; retained-refresh proof and stale-token
  compare-and-swap remain separate hardening work.

### Production Actions

- Pushed and deployed exact runtime
  `a9295b8fae1dee97f1f85be3530396bc5390dd80` from clean shared-shell closeout
  `9dc908173d180be13a0b73a74b7ad3088fc6ac4a`.
- Restarted only `mailapp`. Exact clean Git, all seven services active, public
  health `ok`, zero automatic restarts, and unchanged Alembic
  `f3a4b5c6d7e8 (head)` were verified. No schema, dependency, frontend, Caddy,
  worker, database, mail, calendar, AI, or terminal mutation occurred.

### Next

Reconnect the three affected Google accounts once so they receive a broad
token under the corrected refresh behavior. Continue the first-class At a
Glance route from this exact backend baseline.

## 2026-08-30 — Durable inline replies release

### Scope

Extend durable draft ownership and recovery into Reader and Flow replies, add a
cross-device metadata-only Continue Writing surface, preserve the secure
terminal f3 baseline, and exercise mutations only against generated
`.example.test` fixtures.

### Completed

- Unified Reader, Flow, full Compose, and Drafts under one exact
  account/source reply identity with immediate auth-scoped IndexedDB writes,
  cross-device lookup, Reply/Reply All envelope rebase, safe send/discard
  handoff, focus restoration, and guarded navigation/mail actions.
- Added exact-source server lookup, concurrent first-save convergence with
  stable `draft_source_exists`, and a recent-draft query that projects metadata
  without loading draft content, provider IDs, or attachment bytes.
- Added responsive **Continue writing**, server-revision comparison, generated
  provider exact-source scenarios, comprehensive tests, API documentation,
  decision D-028, and
  `DURABLE_INLINE_REPLIES_RELEASE_2026-08-30.md`.

### Verification

- After rebase onto terminal closeout `2fd5e4c`, 550 backend tests passed with
  35 intentional PostgreSQL/external skips; ten focused PostgreSQL draft tests
  passed; all 295 frontend tests passed; production build transformed 524
  modules.
- Generated-provider scenarios passed with normal paths reporting zero
  unexpected mutations, unknown routes, non-fixture recipients, or external
  calls. Desktop and 390×844 browser QA proved save, close/focus, reopen,
  hard-reload recovery, full-Compose handoff, and Continue Writing.
- Backend, frontend, and generated-QA reviews reported no remaining P0–P2
  issue after their transition, conflict, revision, teardown, and focus
  findings were corrected. `git diff --check` passed.

### Production Actions

- Fast-forwarded GitHub `main` and clean production from `2fd5e4c` to exact
  application/documentation commit
  `9aa93f61fe7031ce267b833930a84c5d0a2121c3`.
- Restarted only `mailapp` before publishing the new frontend. One old process
  held a connection through the 90-second stop window and was killed by
  systemd; the replacement started with zero automatic restarts and no
  post-start warning-or-higher entries.
- Installed the unchanged frontend lock with zero audit vulnerabilities and
  built 524 modules. No migration, backup, dependency change, Caddy reload, AI
  change, worker restart, mail send, mail mutation, calendar mutation, or
  terminal mutation occurred.
- Verified exact clean Git, Alembic `f3a4b5c6d7e8 (head)`, all seven services
  active, public health `ok`, new asset 200, anonymous exact-source lookup 401,
  and a visible authenticated production Continue Writing region without
  opening a real message or draft.

### Next

Hand the exact docs-closeout GitHub/production SHA to the terminal milestone,
then rebase and implement At a Glance as a first-class migration-free
application route while keeping all serial, enrollment, flashing, and OTA
controls locked.

## 2026-08-30 — Secure terminal enrollment foundation release

### Scope

Release a default-locked, owner-scoped RET1 server foundation without shipping
or enabling browser Serial, Wi-Fi submission, device writes, firmware flashing,
erase, or OTA. Preserve all existing legacy terminals and coordinate the shared
frontend shell with Durable Replies.

### Completed

- Added signed schema-2 release claims, exact RET1 ticket validation,
  owner-scoped intent/completion/status/revocation APIs, hashed per-device
  credentials, device-check-in activation, same-owner pending legacy
  continuity, bounded one-generation rollback, and full revocation.
- Added canonical row/advisory locking, a partial unique secure-MAC index,
  Caddy access-log suppression, outer ASGI path redaction, and a truthful locked
  Admin policy surface. The browser imports no serial transport and exposes no
  write action.
- Published the complete architecture, threat boundary, enablement checklist,
  operator recovery contract, and release evidence in `docs/terminal/` and
  `docs/progress/SECURE_TERMINAL_ENROLLMENT_FOUNDATION_RELEASE_2026-08-30.md`.

### Verification

- `make check` passed 548 backend tests with 33 skips, 274 frontend tests, and a
  518-module local build. Production built 520 modules.
- Disposable PostgreSQL 17 passed the exact f3→e2→f3 migration cycle and all 12
  focused lock/race/lifecycle regressions. Caddy validation, diff/secret scans,
  and independent security review reported no remaining P0/P1 issue.
- Authenticated production At a Glance QA reported both firmware and enrollment
  locked, exposed no serial/write action, and left both enrollment tables empty
  with every existing terminal still legacy.

### Production Actions

- Validated a protected 1,383,638,606-byte pre-migration backup, fast-forwarded
  the application to `8ff01848a2be2818dfd9eb88b84be9aab4befb0a`, and advanced
  Alembic from `e2f3a4b5c6d7` to `f3a4b5c6d7e8 (head)`.
- Restarted only `mailapp`; the retired process exceeded its graceful-stop
  window, while the replacement started cleanly with zero automatic restarts
  and no post-start warning-or-higher entries. Caddy reloaded its validated
  tracked configuration without a restart.
- Verified all seven services active, public health `ok`, clean exact Git, the
  production asset, anonymous 401 behavior, empty secure-enrollment state, and
  the secure-MAC index.

### Next

Send the exact f3 release SHA to Durable Replies. After that release establishes
the next shared-shell baseline, add At a Glance as a first-class migration-free
application route. Keep Web Serial and OTA blocked pending physical E1001/E1002
HIL and the later signed A/B design.

## 2026-08-30 — Durable draft sessions release

### Scope

Make full Compose a durable, versioned writing session across hard reloads,
attachments, offline work, provider ambiguity, conflicts, discard/Undo, and
send recovery. Keep real production mail read-only and preserve the concurrent
AI and terminal workstreams.

### Completed

- Added user/account-owned PostgreSQL draft sessions, attachments, mutation
  receipts, stable provider identity, bounded quotas, leases, Gmail
  create-at-most-once reconciliation, provider updates, and content-free
  discard tombstones.
- Added auth-scoped IndexedDB recovery, stable Compose URL identity, truthful
  lifecycle copy, explicit conflict resolution, accessible dialog focus
  management, attachment-byte recovery, app-managed Gmail Draft reopening, and
  exact durable-draft linkage into the outbound outbox.
- Retained a send-owned browser snapshot until terminal truth: sent removes it;
  failed or cancelled recovery creates a fresh durable Compose identity before
  removing the source. Provider-draft cleanup begins after the authoritative
  Undo deadline independently of outbound reconciliation.
- Added a localhost-only generated provider fixture restricted to reserved
  `.example.test` recipients. Its immutable per-draft email identities prevent
  one fixture deletion from retargeting another draft.

### Verification

- Backend passed 472 tests with 21 opt-in PostgreSQL skips. Frontend passed
  256/256 tests and built 518 modules locally and on production.
- Disposable PostgreSQL passed eight focused tests, concurrency and scrub
  checks, and an actual `e2f3a4b5c6d7 → d1e2f3a4b5c6 → e2f3a4b5c6d7`
  migration cycle.
- Generated-provider scenarios produced zero unexpected mutations, unknown
  routes, or external calls. The guard intentionally attempted and rejected one
  forbidden Todo mutation and two non-reserved recipients without creating a
  provider draft.
- Local browser QA at 1280×720 and 390×844 proved stable URL, hard-reload text
  and attachment recovery, truthful saved status, and a clean console. Three
  independent architecture, competitive-UX, and generated-provider reviews
  found no remaining P0/P1 issue after their findings were fixed.

### Production Actions

- Pushed application `61e0ad8f47bd12dff07b7c0e695ea3f5680af7a4`
  to the feature branch and GitHub `main`, then fast-forwarded clean production
  from `8fed5d1c9cd356c3222891251e692dfbe932a8eb`.
- Captured and validated
  `/var/backups/mailapp/maildb-pre-durable-drafts-20260830T1859Z.dump`:
  1,383,545,000 bytes, mode `0600`, owner `postgres:postgres`, and 273 readable
  archive entries. Advanced Alembic from `d1e2f3a4b5c6` to
  `e2f3a4b5c6d7 (head)`.
- Restarted only `mailapp` and `mailworker-cron`. The retired API process
  exceeded its 90-second graceful-stop window and was killed; the reviewed
  replacement and cron worker started successfully with zero automatic
  restarts or post-start warning-or-higher entries.
- Verified exact clean Git, public health, all seven services, anonymous draft
  API 401, exact frontend asset 200, and zero rows in all three draft tables.
  Signed-in read-only Compose QA entered no content, invoked no draft action,
  emitted no browser warning/error, and left those tables empty.
- Recorded the complete release and rollback evidence in
  `docs/progress/DURABLE_DRAFT_SESSIONS_RELEASE_2026-08-30.md` at
  `0c92e59bb47101f24a9c08afd692296cda8d47c0`.

### Next

Rebase the terminal enrollment slice onto the new exact `e2f3a4b5c6d7` Email
baseline. For the email client, extend the same durable controller into inline
reader/Flow replies and add a cross-device Recent Drafts surface without
weakening the released ownership, ambiguity, or recovery contract.

## 2026-08-30 — Fail-closed terminal firmware gateway release

### Scope

Publish the reproducible private firmware baseline and add an authenticated,
locally staged firmware catalog to At a Glance without exposing any browser
write, erase, unsigned-install, or OTA path. Preserve the durable outbound
release and its migration head.

### Completed

- Merged private firmware release `1b5364e5` after GitHub Actions run
  `33322241770` built all three models twice, proved byte identity, strictly
  verified the manifest/checksums, and uploaded the immutable bundle.
- Added a cookie-authenticated, rate-limited application gateway for one signed
  approval catalog, detached manifests/signatures, and exact per-model
  artifacts from local content-addressed storage.
- Enforced signed catalog generations, public-key allowlists, exact manifest
  and partition contracts, closed file sets, hashes, protected NVS/LittleFS
  ranges, hardware revision qualification, E1004 lockout, safe filesystem
  traversal, and non-disclosing errors.
- Added an Admin catalog inspection surface that reports browser prerequisites
  but contains no port request, flashing dependency, binary download, erase,
  or write operation. Browser signature verification, secure provisioning, and
  HIL gates remain fixed false.
- Corrected the operations runbook to identify the systemd-overridden tracked
  `/opt/mail/Caddyfile` as the live Caddy source.

### Verification

- Post-outbound rebase `make check`: 459 backend tests passed with 13 opt-in
  PostgreSQL tests skipped; 221 frontend tests passed; 512 frontend modules
  built. Focused firmware gateway tests passed 37/37; compilation and
  `git diff --check` passed.
- A final independent adversarial review reported no P0-P2 finding after
  rollback-generation, bounded-catalog, filesystem-error, rate-limit, auth,
  header, partition, and browser-policy fixes.
- The exact firmware artifact downloaded from the successful main run passed
  strict manifest verification and every `SHA256SUMS` check. Its manifest still
  truthfully declares unsigned, single-slot, non-OTA, and unqualified state.

### Production Actions

- Pushed rebased application `0fe2ef7` and release documentation `69a5622` to
  the feature branch and GitHub `main`, then fast-forwarded clean production
  from outbound closeout `6d8e945` to exact `69a5622`.
- Confirmed no dependency or Alembic diff, validated the exact tracked
  `/opt/mail/Caddyfile`, installed the unchanged frontend lock as `mailapp`
  with zero audit vulnerabilities, built 514 production modules, restarted
  only `mailapp`, and reloaded Caddy. No database backup was required because
  no schema or data mutation occurred.
- Postflight passed: exact clean Git, public health, all seven services, zero
  mailapp/Caddy warning-or-higher log entries or automatic restarts, exact
  frontend asset 200, anonymous catalog 401, `serial=(self)` policy, and
  unchanged Alembic `d1e2f3a4b5c6`.
- Signed-in read-only Admin QA showed the locked installer, all three unmet
  safety gates, safe catalog-unavailable copy, no controls inside the installer
  section, and zero browser warnings/errors. No serial permission, artifact
  download, flash, erase, terminal mutation, mail mutation, or calendar
  mutation occurred.
- Production retained empty/default firmware trust configuration. No signing
  key, approved catalog, artifact tree, generation floor, or enablement flag
  was staged.

### Next

Resume the preserved secure-enrollment branch by auditing its partial files,
completing deterministic crypto/protocol/power-loss tests, and obtaining real
E1001/E1002 hardware evidence. Do not treat that branch as releasable or enable
browser writes.

## 2026-08-30 — Safe outbound delivery and More anchoring

### Scope

Eliminate duplicate-send risk and false delivery confirmation across Compose,
reader replies, and Flow; add Undo Send and durable recovery; correct the More
dropdown position reported on Calendar; preserve concurrent AI and terminal
work; and exercise mutations only against generated `.example.test` fixtures.

### Completed

- Shipped the isolated More positioning fix first at
  `9d0d4754a3c1ba3817f1c20244810231b4f8894d`. The menu now uses the trigger as
  its positioning context while retaining the fixed mobile sheet and
  transparent Safari backdrop.
- Added a user/account-owned PostgreSQL outbound outbox, immutable idempotency
  contract, ten-second Undo window, stable RFC Message-ID, leases, bounded
  pre-attempt retries, lookup-only post-attempt reconciliation, payload
  scrubbing, safe errors, Redis wakeup, and cron recovery.
- Required exact owned source-message/account/thread/header proof for replies
  and moved Compose, reader, and Flow to one session-scoped frontend controller.
- Added global reconciling/failure status, reload-aware Undo, truthful terminal
  notifications, queued distinct-draft recovery, and sent-confirmed Flow
  archive ordering with read-only lost-response reconciliation. Removed the
  ambiguous one-click failure Retry so the recovered editor is the only resend
  surface.
- Restored Compose and Flow Send in the command palette after making execution
  idempotent. Added the session-only API contract, durable design decision, and
  complete release record.

### Verification

- More focused tests and production frontend build passed. Signed-in read-only
  production QA measured exact menu/button alignment on Flow and Calendar at
  1280×720 with no real-data mutation.
- Final `make check` passed 422 backend tests with 13 opt-in PostgreSQL skips;
  all 208 frontend tests and the 510-module production build passed.
- A disposable PostgreSQL 17 full upgrade, four outbound concurrency/race
  tests, downgrade with table-removal proof, and re-upgrade passed. Generated
  browser QA then passed lost-response Undo, exact recovery, active-draft
  non-clobber, explicit review, preserved newer autosave, and durable failure
  dismissal. Its fake provider audit recorded the exact intentional attempt
  count with no external calls, unexpected mutations, or unknown routes.
- Independent UX/backend reviews found no remaining P0. Their final P1 findings
  led to content-conditional local-draft deletion, user-invoked failure review,
  safe release ordering/roll-forward guidance, bounded ingress, queue quotas,
  SQL parameter redaction, immediate non-retryable scrubbing, and a one-hour
  cron/admission expiry for the only server-authorized retry payloads.

### Production Actions

- Pushed the More-only commit to the feature branch and GitHub `main`,
  fast-forwarded clean production, and rebuilt only the frontend. No migration,
  dependency change, service restart, or data mutation was required. All seven
  services and public health remained healthy.
- Pushed the reviewed outbound runtime commit
  `2a8dbecba7d590198cfe005062700d5e68624851` to the feature branch and GitHub
  `main`, then fast-forwarded clean production from `9d0d475`.
- Captured and validated the 1,383,543,906-byte custom-format backup
  `/var/backups/mailapp/maildb-pre-outbound-20260830T1718Z.dump`, mode `0600`,
  owner `postgres:postgres`, with 252 readable archive entries.
- Advanced Alembic from `c0d1e2f3a4b5` to `d1e2f3a4b5c6`, verified the empty
  outbox and its 12 indexes, and restarted only `mailapp` and
  `mailworker-cron`. The old API process exceeded its 90-second graceful-stop
  deadline and was killed by systemd; the replacement and cron worker started
  successfully.
- Verified public health, all checked services, unauthenticated `401`
  boundaries for the new APIs, and a still-empty outbox before publishing the
  510-module `index-BU6KBgki.js` frontend.
- Signed-in read-only production browser QA loaded blank Compose with all
  expected controls and zero console errors. More was exactly left-aligned to
  its trigger with an 8 px gap. No real send, Undo, retry, archive, calendar,
  Sync, Todo, or other mailbox mutation ran.

### Next

User-test real Send and Undo deliberately from the production UI. Treat any
post-acceptance rollback as roll-forward-only, and continue the next product
cycle with generated fixtures while the terminal task rebases onto the final
docs-closeout SHA.

## 2026-08-30 — Session ownership and shell reliability candidate

### Scope

Make account switching a complete browser privacy boundary, enforce Todo source
ownership, fix the Safari More/Sync blank-page regression, and preserve drafts
during fast navigation while keeping all generated QA read-only with respect to
real mail and calendars.

### Completed

- Added one central authentication generation and synchronous reset for all
  user-derived stores; guarded requests, refreshes, raw streams, realtime,
  polling, timers, delayed continuations, navigation handoffs, and toasts.
- Ordered logout behind in-flight refresh and kept login unavailable until the
  final cookie clear; coalesced duplicate logout attempts.
- Scoped Compose draft and sender storage by user/intent, purged unsafe legacy
  keys, and persisted the latest edit before teardown.
- Made generic Todo creation manual-only, scoped email and analysis lookup
  through account ownership, normalized AI action items, added uniform 404s,
  and added PostgreSQL cleanup/enforcement revision `c0d1e2f3a4b5`.
- Fixed the transparent More/Sync fullscreen close targets in Safari and made
  cancel/failure stop remaining browser-assisted unsubscribe work.
- Added generated two-user, popover, auth-cookie, Todo, request, stream, action,
  draft, realtime, reset, and migration regressions.

### Verification

- Final `make check`: 399 backend passed, 4 opt-in PostgreSQL tests skipped;
  183 frontend passed; 507-module build completed.
- Disposable PostgreSQL 17 upgrade/downgrade/re-upgrade and trigger checks
  passed. Production aggregate preflight found zero Todo rows.
- Generated 1280×720 and exact-375 browser QA passed with delayed User A Todo
  responses released after User B login, no A data/draft in B, transparent
  shell backdrops, no overflow, zero fixture mutations/unknown routes, and zero
  browser warnings/errors.
- Independent backend, generated-QA, and competitive UX reviews approved the
  final candidate after all P0/P1 findings were fixed.

### Production Actions

- At the user's explicit request, promoted exact active
  `austin@mcchord.net` to administrator, initially added the two requested
  external addresses, then widened only trusted organization domains
  `@mcchord.net`, `@casanacare.com`, and `@outsidersfund.com`. Consumer domains
  remain exact-address only. Aggregate verification passed; no restart was
  required and no allowlist value was printed.
- Pushed exact application commit
  `18e80fdd9247c52825b225e55b85aabc240e76d3` to the feature branch and GitHub
  `main`, then fast-forwarded clean production from `2d20f6a`.
- Captured and validated the 1,383,527,167-byte custom-format backup
  `/var/backups/mailapp/maildb-pre-session-ownership-20260830T1559Z.dump`, mode
  `0600`, owner `postgres:postgres`.
- A mistyped expected full SHA stopped the first preflight before mutation. A
  later command stopped after Git/frontend deployment but before migration or
  restart because it referenced `.venv`; after reconfirming clean exact Git,
  the documented `/opt/mail/venv` applied Alembic `c0d1e2f3a4b5` and restarted
  only `mailapp`.
- Post-deploy checks passed: exact clean Git, public health, `/`, exact frontend
  asset, all seven services, new `mailapp` process/logs, unauthenticated Todo
  boundary, migration head, ownership trigger/function, zero Todo/mismatch
  rows, and aggregate trusted-domain/admin state.
- Signed-in production QA opened More at 1280x720 with a transparent full-page
  close target while the menu and main remained visible. No browser errors or
  real mail, calendar, Sync, unsubscribe, send, or Todo mutations occurred.

### Next

User-test More and trusted-domain reauthorization, then continue the next
generated-fixture product cycle. The coordinating At a Glance task may rebase
after receiving the exact docs-closeout SHA.

## 2026-08-30 — At a Glance platform release

### Scope

Promote e-ink terminals into an extensible At a Glance platform with 16:9 and
9:16 browser delivery, robust battery guidance, isolated display credentials,
and a safe firmware-management path while preserving the concurrent Calendar
release.

### Completed

- Centralized view, design, profile, device-renderer, and web-renderer
  registration; added exact-size fullscreen HTML/PNG adapters alongside the
  existing BMP protocol.
- Added individually rotatable browser credentials bound to one catalog
  combination, leaving the firmware code and other display links unchanged.
- Added bounded sparse battery history, stale/partial telemetry handling,
  conservative runtime prediction, charge notices, and Admin presentation.
- Promoted the Admin section and documentation to At a Glance, including
  ready-to-open browser display cards and scoped link rotation.
- Documented the inspected firmware baseline and gated path through Web Serial,
  local provisioning, CA validation, per-device trust, signed A/B OTA, staged
  rollout, rollback, and rescue. The dirty firmware checkout was not modified.
- Coordinated with and rebased twice after the Calendar task; both Calendar and
  terminal additions remain present in `docs/api.md`.

### Verification

- Post-final-rebase `make check`: 387 backend passed, 4 opt-in PostgreSQL tests
  skipped, 156 frontend passed, and the 504-module production build completed.
- Focused terminal/display/battery tests: 91 passed. Compile/import lint and
  `git diff --check` passed.
- Disposable PostgreSQL 17 upgrade/downgrade/re-upgrade rehearsal passed for
  both new revisions and verified their tables and indexes.
- Generated browser QA confirmed exact no-overflow 1280×720 and 720×1280
  delivery. Existing artwork was preserved without cropping or distortion.

### Production Actions

- Pushed application `4c5a1fe`, firmware roadmap `1359a24`, and release record
  `c76cb5e` to the feature branch and GitHub `main`, then fast-forwarded clean
  production from Calendar closeout `a2c02bf` to exact `c76cb5e`.
- Created and validated a 1,383,479,646-byte PostgreSQL custom-format backup at
  `/var/backups/mailapp/maildb-pre-at-a-glance-20260830T1503Z.dump`, mode
  `0600`, owner `postgres:postgres`.
- The initial deploy precondition stopped before mutation when root Git lacked
  the required safe-directory flag. The corrected gate reconfirmed the exact
  prior commit and clean tree, then applied both additive Alembic revisions,
  built 506 frontend modules as `mailapp`, and restarted only `mailapp`.
- Post-deploy verification passed: Git is exact and clean, Alembic is
  `b9c0d1e2f3a4 (head)`, both tables and scoped-token indexes exist, public
  health is `ok`, all seven services are active, `mailapp` reports zero
  restarts and zero warning-or-higher entries, and expected public auth/404
  boundaries respond correctly.
- Signed-in production QA showed five individually rotatable browser cards and
  live battery collection/stale states. A 1280×720 Clock page had exact image,
  stage, viewport, and overflow geometry; a query view override could not
  change its token-bound content. No display URL was rotated.

### Next

Close out the docs-only release evidence, then begin the clean firmware
artifact and browser-installer milestone. OTA remains gated on A/B layout,
trusted transport, device authentication, signed manifests, and rollback.

## 2026-08-30 — Calendar state-integrity candidate

### Scope

Remove false-empty, stale-response, account-authority, date-boundary, and
responsive/accessibility ambiguity from Calendar while leaving real mail and
calendars read-only and preserving separately owned terminal/e-ink and AI work.

### Completed

- Added immutable range/account/timezone request identity, cancellation,
  same-key cache refresh, explicit loading/error/retry states, and stale modal
  closure.
- Centralized generation-scoped account authority across polling,
  login/logout, retry, and same-document re-login; removed Sidebar’s competing
  account writer.
- Separated cached Reload from Google Sync, captured submitted sync scope, and
  required all targets to finish or produce honest unconfirmed timeout copy.
- Added connection/freshness coverage states and limited verified-empty claims
  to ranges inside every visible account’s successful full-sync window.
- Corrected API DST/half-open range selection, Google all-day exclusive ends,
  cross-midnight display/geometry, merged counts, event-detail dates, focus
  behavior, mobile views/controls, timezone disclosure, and accessible labels.
- Expanded the generated localhost Calendar harness with immutable accounts,
  events, statuses, boundary/DST/failure/overlap/disconnected cases, a local
  reauthorization sink, and exact read/mutation auditing.

### Verification

- `make check`: 341 backend passed, 4 opt-in PostgreSQL tests skipped, 156
  frontend passed, and the 506-module production build completed.
- Harness syntax, secret scan, and `git diff --check` passed.
- Generated desktop/exact-375 browser QA passed for loading, populated,
  verified and unverified empty, error/retry, slow overlap, disconnected,
  status failure, event dialog, and DST boundary paths. Audit: zero accepted
  mutations and zero unknown routes.
- Independent architecture, competitive UX, and QA rereviews found and then
  verified closure of midnight geometry, account ABA, loading authority,
  coverage-window, and timeout-truthfulness blockers.

### Production Actions

- Pushed application commit `bbf96b3` and release record `b6cfd98` to GitHub
  `main` and `codex/calendar-state-integrity`, then fast-forwarded the clean
  production checkout from `aa91430` to exact `b6cfd98`.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 506-module frontend as `mailapp`, and restarted only `mailapp`.
  The prior process held a long-lived connection during shutdown and the
  restart completed after the initial command window; the replacement process
  is active and clean.
- Post-deploy verification passed: production Git was clean, public health,
  `/`, and the exact Calendar asset returned 200, the Calendar route returned
  the expected unauthenticated 401, all seven services were active, five
  application-edge restart counters were zero, Alembic remained at head, and
  the new `mailapp` process had zero warning-or-higher entries.
- No schema, dependency lock, worker, terminal/e-ink, AI-provider, Caddy/systemd
  configuration, Google grant, production allowlist, mailbox, or calendar data
  changed.

### Next

User-test read-only Calendar navigation, Reload, and event details with real
accounts. Keep Sync and real calendar/mail mutations outside automated QA.

## 2026-08-30 — Google OAuth callback fail-safe candidate

### Scope

Confirm the reported Calendar reauthorization Internal Server Error, protect
all adjacent Google callback exception paths, and preserve the concurrent AI
worktree and real-mail read-only boundary.

### Completed

- Correlated the supplied legacy state window with a redacted production
  `Missing code verifier` traceback that preceded the deployed PKCE release.
- Added typed signed-state validation, complete account/login callback
  exception boundaries, best-effort rollback, class-only redacted logging, and
  cookie-before-commit transaction ordering.
- Added safe handling for known legacy callback query parameters and more
  actionable account/login recovery copy.
- Added an exact legacy-state regression plus generated setup, malformed
  profile, database read, commit, cookie, rollback, and redaction coverage.
- Read-only allowlist matching confirmed the two newly reported external
  addresses are absent; no production configuration changed pending explicit
  confirmation of the exact-address additions.

### Verification

- `make check`: 336 backend passed, 4 opt-in PostgreSQL tests skipped, 135
  frontend passed, and the 504-module production build completed.
- Focused OAuth: 26 passed. `git diff --check`: passed.
- Independent architecture, competitive UX, and QA reviews found and verified
  closure of database/setup and cookie-before-commit blockers.
- Generated exact-375 in-app browser QA passed with an accessible recovery
  notice, cleaned URL, no overflow, zero mutation attempts, zero accepted
  mutations, and zero unknown routes.

### Production Actions

- Pushed application commit `a499d9d` and release record `2877a28` to GitHub
  `main` and `codex/oauth-callback-reliability`, then fast-forwarded the clean
  production checkout from `bf8062b` to exact `2877a28`.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 504-module frontend, and restarted only `mailapp`. The old
  process retained a long-lived connection through its stop timeout and was
  killed by systemd; the replacement started immediately and cleanly.
- Production Git is clean and exact; public health and `/` return 200; an empty
  generated callback returns the sanitized Profile & Accounts 303; all seven
  services are active with zero reported restarts; Alembic remains at head;
  and the new mailapp process has zero warning-or-higher entries, callback
  tracebacks, or missing-verifier traces. A read-only browser shell check also
  passed without inspecting mail content.
- No mail, Google grant, allowlist, schema, dependency lock, worker, TUI,
  Caddy/systemd configuration, or AI file/service changed.

### Next

Add only the two exact requested allowlist entries if confirmed, then use fresh
one-time Google authorization flows.

## 2026-08-30 — Reply-envelope integrity candidate

### Scope

Remove wrong-account and recipient-envelope ambiguity from Inbox and Flow
without touching the concurrent AI-provider worktree or mutating real mail.

### Completed

- Added authoritative account identity and References state to details/thread
  members, plus optional owned-account thread scoping.
- Centralized fail-closed Reply/Reply All derivation, removed first-account
  fallbacks, preserved RFC recipient/threading semantics, and made visible
  From/To/Cc values identical to send/full-compose payloads.
- Added explicit Inbox Reply All, truthful Flow action labels, generation-
  guarded delayed completion, stable hydrated draft keys, unavailable-editor
  suppression, accessible icon controls, and an exact-375 Flow layout repair.
- Added generated second-account/decoy, unknown-source, and Active Thread
  fixtures plus a browser-readable read/mutation audit. Three independent
  reviewers found sender, stale-state, thread-scope, parser, accessibility, and
  mobile blockers; each was fixed before final gating.

### Verification

- `make check` passed: 325 backend tests, 4 opt-in PostgreSQL skips, 132
  frontend tests, and a successful 504-module production build.
- Generated in-app browser desktop/exact-375 QA passed for Inbox, Flow,
  unavailable source, and Active Threads. Audit: zero mutation attempts, zero
  accepted mutations, and zero unknown routes.
- Final architecture, competitive UX, and QA rereviews found no release
  blockers.

### Production Actions

- Committed application release
  `70c67a3b1cde9266c6d6d87e15695d778c198bca`, pushed it to GitHub `main` and
  `codex/reply-envelope-integrity`, and fast-forwarded the clean `/opt/mail`
  checkout to that exact commit.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 504-module frontend as `mailapp`, and restarted only `mailapp`.
  No dependency lock, migration, database data, configuration, Google grant,
  worker, Caddy/systemd, real mailbox, or AI-provider file/service was changed.
- Post-deploy verification passed: production Git was clean and exact, public
  health was `ok`, `/` returned 200, all seven checked services were active,
  five application-edge services reported zero restarts, Alembic remained at
  `z7a8b9c0d1e2 (head)`, the five-minute mailapp warning-or-higher count was
  zero, and a read-only in-app browser shell check loaded `Mail` with one main
  landmark.

### Next

User-test with an explicitly generated multi-recipient conversation; do not
send or mutate real mail. Then continue with the next isolated product slice.

## 2026-08-30 — Google OAuth callback reliability candidate

### Scope

Diagnose and fix the raw Internal Server Error reported after Calendar Google
reauthorization, while preserving the separate AI worktree and using only
redacted production evidence and generated OAuth/browser fixtures.

### Completed

- Redacted production traceback inspection identified a missing PKCE verifier
  at token exchange; no code, token, credential, mail, or raw private log was
  retained.
- Added an explicit shared PKCE flow, encrypted verifier handoff, one-time
  browser nonce, access-cookie-independent callback identity, target-account
  binding, actual-scope and durable-refresh validation, allowlist enforcement,
  sanitized 303 outcomes, and safe Google-login parity.
- Returned Calendar initiators to Calendar, centralized accurate result/error
  notifications and URL cleanup, fixed the nonexistent callback Settings tab,
  and normalized legacy/unknown Settings tabs.
- Added `OAUTH_REAUTHORIZATION_RELEASE_2026-08-30.md`, 15 backend regressions,
  four frontend regressions, and an exact-375 generated browser wrapper.

### Verification

- `make setup` and `make check` passed: 318 backend tests passed, 4 isolated
  PostgreSQL tests skipped, 117 frontend tests passed, and the 503-module
  production frontend built successfully. Npm reported zero vulnerabilities.
- Harness syntax and `git diff --check` passed.
- Generated in-app browser desktop/exact-375 QA showed accurate success and
  account-mismatch notifications on visible Calendar/Profile landings, cleaned
  result parameters, no horizontal overflow, zero mailbox mutations, and zero
  unknown routes.

### Production Actions

- Committed application release `1ded3ccba22b0d300123a080fe25adae77dcc8df`,
  pushed it to GitHub `main` and `codex/oauth-reauthorization`, and
  fast-forwarded the clean `/opt/mail` checkout to that exact commit.
- Reinstalled locked frontend packages with zero reported vulnerabilities,
  rebuilt the 503-module frontend as `mailapp`, and restarted only `mailapp`.
  No dependency lock, migration, database data, Google grant, configuration,
  Caddy, systemd, worker, mailbox, or AI file/service was changed.
- Post-deploy checks passed: Git was clean and exact, all seven checked services
  were active, five application-edge services reported zero restarts, public
  health was `ok`, `/` returned 200, an empty generated callback returned a
  sanitized 303 landing, and the post-deploy mailapp warning-or-higher count was
  zero.

### Next

Use a fresh Google reauthorization for user testing. Confirm the Calendar
landing and green reconnection notice; do not reuse the failed one-time
authorization code.

## 2026-08-30 — Remote-content privacy controls

### Scope

Block sender-controlled email resources by default across every reader and
quoted Compose path, provide a truthful one-message direct-load control, and
deploy the generated-only validated frontend release for user testing without
touching the separately owned AI worktree.

### Completed

- Added a shared CSP-isolated email frame for Inbox, standalone/subscription,
  and Flow with no-referrer requests, safe parent link handoff, System-aware
  theme updates, scoped approval reset, and accessible privacy announcements.
- Parsed sender HTML inside a CSP-locked detached template before DOMPurify,
  then blocked remote images/media/CSS, pings, stylesheets, same-host resources,
  and broad SVG/MathML references. Direct permission restores only absolute
  external-host HTTP(S) image/media values; CSS, fonts, pings, SVG references,
  active content, and authenticated app requests remain blocked.
- Added deliberate accessible placeholders for blocked/unavailable images and
  hardened Forward/Compose plus both basic and rich editor ingestion.
- Added a deterministic generated mailbox/resource beacon covering mixed,
  embedded, permanently blocked, permission-reset, same-host, Inbox, Flow,
  Forward/Compose, theme, desktop, dark, and exact-375 states. Three parallel
  reviewers handled architecture/security, competitive UX, and final QA; all
  release blockers were fixed before deployment.
- Added `REMOTE_CONTENT_PRIVACY_RELEASE_2026-08-30.md`, three screenshot
  artifacts, a captured request audit, and durable decision D-016.

### Verification

- `make check`: 303 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  113 frontend tests passed, and the 502-module production build completed.
- Harness syntax, audit JSON parsing, and `git diff --check` passed.
- Generated browser QA recorded zero requests before permission; exactly seven
  approved external-host image/media requests afterward, all without referrer;
  and zero mailbox mutations or unknown routes. CSS/SVG/ping/same-host vectors
  stayed blocked, theme changes did not re-request, and A → B → A cleared
  permission.
- Safe embedded raster and permanently-blocked-only states were truthful;
  desktop, exact 375×812, and dark Flow visual reviews passed with 44 px mobile
  controls and no overflow. No real mail was opened or changed.

### Production Actions

- Pushed `9b9730a` to `origin/codex/remote-content-controls` and fast-forwarded
  GitHub `main` from `ee93396` without rewriting history.
- Fast-forwarded clean production `/opt/mail` to exact full commit
  `9b9730a68c65de2b7ee9910c0d2c3bd70939e273` as `mailapp`, ran only the locked
  frontend install and build, and observed zero npm vulnerabilities.
- No database migration/write/backup, Python install, service restart, or
  Caddy/systemd change occurred. Public health, seven active services with zero
  restarts, representative static assets, recent error-level logs, and clean
  Git state all passed. The concurrent AI worktree remained untouched.

### Next

Pause for production user testing. When work resumes, coordinate the existing
AI Markdown-image SSRF follow-up with its owner, then design the owned
remote-resource proxy/manifest and CID mapping as a separate security release.

## 2026-08-30 — Frontend dependency security candidate

### Scope

Refresh the compatible frontend dependency graph in isolation, address
regressions exposed by the upgrades, and prove security-critical rendering,
mobile Chat, editor, and PDF paths using generated data only.

### Completed

- Cleared 11 npm production advisories without force or declared-range changes;
  DOMPurify is 3.4.14, jsPDF 4.2.1, Svelte 5.57.0, Vite 6.4.3, and Rollup
  4.63.1.
- Made email/AI renderers explicitly display-only, fixed duplicate Tiptap Link
  and Underline registration, rebuilt Chat's narrow-screen sidebar/download
  controls, and made PDF cleanup exception-safe.
- Replaced fixed PDF raster cuts with structured heading/block boundaries plus
  whitespace and pixel-inspection fallbacks. Iterative Poppler rendering caught
  and eliminated text, heading, and blockquote page-boundary defects.
- Extended the immutable localhost harness with generated hostile email HTML,
  hostile Chat Markdown, long Unicode PDF content, exact 375 px wrappers, and
  dedicated read/mutation/unknown-route evidence.
- Three parallel agents handled compatible lock implementation, dependency
  reachability/risk review, and generated user testing. Their DOMPurify,
  jsPDF, Linux Node floor, and Tiptap warning findings were resolved.

### Verification

- `make check`: 303 backend passed, 4 opt-in PostgreSQL skipped, 108 frontend
  passed, and the 500-module build completed.
- Clean Linux x86_64 Node 20.20.2 passed `npm ci`, zero-vulnerability audit,
  all frontend tests, and `vite build --manifest`.
- Generated in-app browser desktop/exact-375 QA retained safe content, removed
  all active tags/events/JavaScript URLs, mounted one enhanced editor, met 44
  px Chat controls, and recorded no mutation or unknown-route attempts.
- Final generated PDF: sanitized filename, `%PDF-`, 1,041,576 bytes, four
  letter pages. Poppler page renders passed visual inspection without clipping,
  splitting, overlap, or unreadable Unicode. Harness syntax and
  `git diff --check` passed.

### Production Actions

- Pushed `3f9e743` to `origin/codex/frontend-dependency-security` and
  fast-forwarded GitHub `main` from `413d763` without rewriting history.
- Fast-forwarded clean production `/opt/mail` to exact full commit
  `3f9e743a4027a1c66b8e416bd3b6291a2c0b084b` as `mailapp`, then ran only the
  locked frontend install and 500-module build. The production audit is zero.
- No database backup/migration, Python install, service restart, Caddy/systemd
  change, real-message open, or mailbox mutation occurred. Post-deploy health,
  seven service states, zero restart counts, five representative static assets,
  recent error-level logs, and clean Git state all passed. The concurrent AI
  worktree remains untouched.

### Next

Pause for production user testing. Next, design a deliberate remote-content
and tracking-control policy before changing email image or stylesheet behavior.

## 2026-08-30 — Consolidated product release and deployment

### Scope

Freeze the product-polish work, preserve the separately completed AI-provider
baseline through a normal Git merge, close final editor/reply review blockers,
create a complete change record, and prepare the explicitly authorized
production deployment without reading or mutating real mail.

### Completed

- Merged `origin/main` at `41d2898` into the product branch without rebasing or
  editing the clean AI worktree; code merged automatically and both progress
  histories were preserved through documentation-only conflict resolution.
- Fixed Tiptap content feedback so user edits no longer trigger external
  `setContent` caret resets, while true external changes use the Tiptap v3
  no-update contract.
- Scoped Flow thread, custom-reply, Full Compose, and delayed send behavior to
  captured message/thread/source identity; restored reply drafts; selected the
  newest thread message by display order; and prevented delayed completion
  from clearing or navigating away from newer work.
- Kept editor-load failures in a fully usable, focused basic editor rather than
  reloading and stranding reply context.
- Preserved reply `In-Reply-To`, `References`, and Gmail `threadId` through
  saved Gmail drafts with route and decoded-MIME tests.
- Created `PRODUCT_POLISH_RELEASE_2026-08-30.md` as the complete release,
  safety, validation, deployment, and rollback record.

### Verification

- `make check`: 303 backend tests passed, 4 opt-in PostgreSQL tests skipped,
  108 frontend tests passed, and the 498-module production build completed.
- The final entry is 258.42 kB / 78.51 kB gzip; DeferredRichEditor is 4.83 kB /
  2.23 kB gzip; RichEditor/Tiptap remains a separate 371.52 kB / 117.42 kB
  gzip dynamic asset.
- Generated in-app browser QA verified zero editor requests while reading Flow,
  exact editor JS/CSS loading after writing intent, focused draft continuity,
  typing during a slow enhancement, fully editable fail-once fallback, and a
  375px composer with no horizontal overflow and ten 44x44 toolbar controls.
- Final generated audits recorded zero mutation attempts and zero unknown
  routes. All fixtures used `.example.test` data; no real message was opened or
  changed. `git diff --check` and harness syntax passed.

### Production Actions

- Pushed candidate `834eade` to the product branch and fast-forwarded GitHub
  `main` from `41d2898` without rewriting history.
- Created and validated a 1.38 GB PostgreSQL custom-format backup at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`, mode
  `0600`, owned by `postgres`. The dump was moved out of the checkout after
  verification caught the untracked backup directory; production Git is clean.
- Fast-forwarded `/opt/mail` as `mailapp`, ran the locked frontend install and
  498-module production build, upgraded Alembic transactionally to
  `z7a8b9c0d1e2`, and restarted only `mailapp`, `mailworker`, and
  `mailworker-cron`. Requirements, Caddy, systemd, and TUI were unchanged.
- Verified exact local/origin revision, schema objects, public health `ok`, all
  seven services active, zero service restarts, zero error-level application/
  worker log lines, and HTTP 200 for the eager, deferred-editor, and rich-editor
  assets. No production message was opened or mailbox mutation performed.
- The unchanged npm lockfile reports 11 compatible-fix advisories (4 moderate,
  6 high, 1 critical); record a separate dependency-update cycle rather than
  mixing unverified framework and PDF-library upgrades into this release.

### Next

Pause feature work for user testing. Next, clear the npm audit in an isolated
dependency update with full browser regression, then resume the product queue.

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
## 2026-08-29 — OpenAI GPT-5.6 and Anthropic Claude 5 support

### Scope

Add provider-neutral model selection and reasoning-effort controls using the
project credentials available through AustinLand, with workload-specific
defaults for quality, speed, and cost.

### Completed

- Registered GPT-5.6 Sol, Terra, and Luna plus Claude Fable 5, Opus 5, and
  Sonnet 5 with provider, effort, label, and workload-compatibility metadata.
- Set balanced defaults: Terra/medium planning, Luna/low parallel execution and
  email processing, Sol/high final verification, Terra/medium custom replies,
  and Sonnet 5/medium Computer Use unsubscribe.
- Added OpenAI Responses API support for text, structured tools, and the
  plan/execute/verify loop; upgraded Claude 5 calls to adaptive
  `output_config.effort` and retained Claude-only Computer Use routing.
- Carried model and effort through routers, worker jobs, bundles, briefings,
  dashboard snippets, and user preferences, including retired-model fallback
  and model/effort validation.
- Added model and effort controls to Settings, OpenAI setup/configuration,
  provider-neutral documentation, the OpenAI SDK dependency, and a regenerated
  Python 3.13 lockfile.
- Added focused provider-registry, validation, fallback, OpenAI request-shape,
  and Anthropic request-shape tests.

### Verification

- `make check`: 136 tests passed and the frontend production build completed;
  the existing large JavaScript chunk advisory remains.
- Python bytecode compilation and `git diff --check`: passed.
- AustinLand created the idempotent `Email-openai` project-scoped entry and
  recorded the shared `Email-anthropic` assignment. No secret value was
  printed, persisted in this checkout, or recorded in the workbook.
- Live provider catalog retrieval found all six requested model IDs. Minimal
  smoke calls returned the requested response from GPT-5.6 Luna with `none`
  effort and Claude Sonnet 5 with `low` effort. Both provider adapters passed a
  forced structured-tool call, and the OpenAI stateless tool-result
  continuation used by the chat executor also passed.

### Production Actions

- Committed and pushed application release `40bbc48`, then fast-forwarded the
  clean production checkout from `0500d1a` to that exact commit as `mailapp`.
- Provisioned the scoped AustinLand entries into `/opt/mail/.env` through an
  in-memory transfer, after creating protected backup
  `/opt/mail/.env.pre-ai-models-20260830T025842Z`; the resulting file remained
  mode `0600`. No key value appeared in Git, command output, logs, or docs.
- Installed `requirements.lock` (adding OpenAI 2.54.0), ran `npm ci`, rebuilt
  the frontend, and restarted only `mailapp`, `mailworker`, and
  `mailworker-cron`. The API restart spent about one minute draining the prior
  long-lived connection and then completed successfully.
- No Alembic revision, database backup or migration, Caddy/systemd change,
  TUI restart, or mailbox-data mutation was required.
- Verified the production application adapter directly against GPT-5.6
  Terra/medium, Luna/low, and Sol/high; all three returned the expected
  response. Public health was `ok`, all seven services were active, the new
  frontend model controls were present, and the post-restart API/worker
  error-level journal count was zero.

### Next

The requested provider expansion is complete in production. Resume the
separately scoped Google OAuth publishing-status work when authorized.

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
