# Current Status

Last updated: 2026-08-30

## Active Objective

Qualify physical E1001/E1002 enrollment and recovery before adding browser
Serial or any terminal write path. Then replace insecure device TLS and design
signed A/B OTA with pending-image validation and automatic rollback. At a
Glance is now a first-class application destination; keep the released daily
experience separate from destructive terminal management.

## Baseline

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
- Production Alembic is `f3a4b5c6d7e8 (head)`, the terminal-only additive
  child of `e2f3a4b5c6d7`. The new credential and attempt tables remain empty,
  all four existing terminals remain legacy, and the secure-MAC unique index is
  present.
- All seven checked production services are active, public health is `ok`, and
  the replacement API process has zero automatic restarts and no post-start
  warning-or-higher entries. Production has no secure-enrollment configuration,
  online key, approved catalog, qualified release/model pair, or credential.
- Private firmware `main` is
  `fd8671bd9a3641ecf9af37491bb8a00607dec4d6`
  (`0.2.0-candidate.3`). Exact-main run `33329094948` passed its software gates;
  generic bundles remain unkeyed, enrollment-disabled, and unqualified.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Items

### P1 — Physical E1001/E1002 browser-install qualification

- State: software foundations are complete and production remains locked. No
  device write or enrollment key has been enabled.
- Scope: physical RET1 enrollment, interrupted serial/config write, three-slot
  selection, same-owner pending continuity, rollback grace, revocation,
  preserve-config, CA failure, power loss, and ROM recovery on both models.
- Acceptance: repeatable recovery evidence proves a failed or interrupted
  operation cannot silently strand a terminal or disclose credentials. Only
  qualified exact release/model pairs may enter the allowlist.
- Next: identify dedicated E1001/E1002 HIL devices and execute the documented
  physical matrix before importing any Web Serial transport into production.

## Recent First-Class At a Glance Release

- The primary `?page=at-a-glance` destination is live with catalog-driven
  view/design/profile selection, canonical previews, direct navigation, and
  terminal connection/battery/charge summaries.
- The everyday route consumes a credential-free, owner-scoped read API. Scoped
  HTML links and all terminal/firmware mutations remain in Settings.
- Consolidated checks passed 561 backend and 307 frontend tests; production
  built 526 modules. Full behavior, production, and rollback evidence is in
  `AT_A_GLANCE_FIRST_CLASS_RELEASE_2026-08-30.md`.

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

## Recent Terminal Release

- The default-locked secure terminal enrollment foundation is deployed at
  runtime `8ff01848a2be2818dfd9eb88b84be9aab4befb0a`, with Alembic
  `f3a4b5c6d7e8 (head)`.
- Full application checks, the exact migration cycle, deterministic PostgreSQL
  contention/lifecycle tests, Caddy validation, secret/diff review, and
  authenticated read-only production QA passed. The locked browser exposed no
  serial or write operation and left all enrollment state untouched.
- Full evidence and rollback boundaries are in
  `SECURE_TERMINAL_ENROLLMENT_FOUNDATION_RELEASE_2026-08-30.md`.

## Near-Term Terminal Queue

- Run physical E1001/E1002 RET1 enrollment, interruption, three-slot selection,
  pending legacy continuity, rollback grace, revocation, CA failure,
  preserve-config, and ROM-recovery HIL. E1004 remains blocked.
- Add the production Web Serial transport only after HIL; keep the pure
  WebCrypto module outside the production import graph until then.
- Replace firmware `setInsecure()`, establish trusted time and CA validation,
  then design signed A/B OTA, pending-image validation, automatic rollback,
  power gates, acknowledgements, cohorts, and rescue.

## Safety Constraints

- Production enrollment defaults are false/empty. Do not generate or stage the
  online P-256 private key, signed schema-2 release, positive catalog generation,
  or release/model HIL allowlist during the locked foundation deployment.
- Firmware release signing stays offline and independent from the future online
  enrollment key. Neither private key belongs in Git, browser code, artifacts,
  application logs, or progress documents.
- The shipped browser contains no serial request, Wi-Fi form, configuration
  write, binary download, erase, esptool, or dynamic flashing path.
- Physical cable observation is not hardware attestation. MAC, model, chip
  revision, and firmware version are self-reported inventory fields.
- Real production mail and calendars remain read-only during terminal QA.
