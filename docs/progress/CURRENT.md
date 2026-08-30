# Current Status

Last updated: 2026-08-30

## Active Objective

Release the default-locked secure terminal enrollment foundation, then add At a
Glance as a first-class application route after the coordinated Durable Replies
release clears the shared shell baseline. Keep browser Serial, device writes,
firmware flashing, and OTA disabled until physical E1001/E1002 recovery evidence
exists.

## Baseline

- GitHub `main` and clean production are exact
  `931cd50b042f008125e2b1eafb7f65ca325b2305`; deployed application runtime is
  `61e0ad8f47bd12dff07b7c0e695ea3f5680af7a4`, and the deployment record is
  `0c92e59bb47101f24a9c08afd692296cda8d47c0`.
- Production Alembic is `e2f3a4b5c6d7 (head)`. The terminal-only additive
  revision is allocated as direct child `f3a4b5c6d7e8`; no parallel task uses a
  migration.
- All seven checked production services are active, public health is `ok`, and
  production Git is clean. No secure-enrollment configuration, online key,
  qualified release, credential, or terminal row exists in production.
- Private firmware `main` is
  `fd8671bd9a3641ecf9af37491bb8a00607dec4d6`
  (`0.2.0-candidate.3`). Exact-main run `33329094948` passed its software gates;
  generic bundles remain unkeyed, enrollment-disabled, and unqualified.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Items

### P1 — Default-locked secure terminal enrollment release

- State: ready for release; implementation and independent review report no
  remaining P0/P1, and deterministic PostgreSQL contention/lifecycle coverage
  closes the final P2 test gap. The production migration/deployment has not run.
- Scope: signed schema-2 RET1 release claims, protected independent online
  P-256 identity, exact transcript/ticket validation, three-slot firmware
  configuration, owner-scoped attempts, hashed per-device credentials,
  device-check-in activation, same-owner pending legacy continuity, bounded
  rollback, full revocation, log suppression, and locked Admin policy UI.
- Acceptance: full application checks, exact migration cycle, deterministic
  PostgreSQL lock/race tests, Caddy validation, secret/diff review, and
  authenticated post-deploy read-only QA pass; production remains locked and
  all new enrollment tables remain empty.
- Next: commit/push the reviewed runtime, take and validate a production backup,
  advance Alembic to `f3a4b5c6d7e8`, deploy, verify, and publish the exact
  release record.

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
