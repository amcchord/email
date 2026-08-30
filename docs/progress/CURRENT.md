# Current Status

Last updated: 2026-08-30

## Active Objective

Add At a Glance as a first-class application route after the coordinated
Durable Replies release clears the shared shell baseline. Keep browser Serial,
device writes, firmware flashing, and OTA disabled until physical E1001/E1002
recovery evidence exists.

## Baseline

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

### P1 — First-class At a Glance application destination

- State: queued by explicit live-QA requirement; Settings currently owns only
  the management section and does not satisfy the product-navigation contract.
- Scope: authenticated app route, lazy route registration, primary desktop and
  narrow-screen navigation, daily view/design/display experience, session
  generation safety, and management links back to Settings.
- Acceptance: At a Glance is discoverable and directly navigable like Flow,
  Email, Calendar, and Todos; it uses the existing shared catalog/adapters and
  preserves responsive, loading, empty, and error behavior.
- Next: receive the exact Durable Replies GitHub/production SHA after this f3
  release, rebase onto that shared-shell baseline, and implement the route in a
  separate migration-free slice.

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
