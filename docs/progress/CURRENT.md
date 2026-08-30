# Current Status

Last updated: 2026-08-30

## Active Objective

Release the authenticated, fail-closed terminal firmware gateway and
catalog-only browser installer on top of the durable outbound baseline, then
continue secure serial enrollment and hardware qualification without enabling
any browser write or OTA path.

## Baseline

- GitHub `main` and production are clean at docs closeout
  `6d8e94584f21a6090b16cc697bd4579c3a3c0400`; the exact outbound runtime is
  `2a8dbecba7d590198cfe005062700d5e68624851`.
- Production Alembic is `d1e2f3a4b5c6 (head)`. The firmware gateway has no
  schema or dependency change and must not advance that head.
- All seven checked production services are active, public health is `ok`, the
  durable outbox remained empty through verification, and the 510-module
  outbound frontend is live.
- The private firmware repository is cleanly released at
  `1b5364e5d4b48666b3ecfd0cf8ba31ab7f4bd5c4`. GitHub Actions run
  `33322241770` reproducibly built and strictly verified all three model
  bundles; those artifacts remain explicitly unsigned, single-slot, and
  non-installable.
- The rebased Email gateway application commit is `0fe2ef7`. Full combined
  validation passed: 459 backend tests plus 13 opt-in PostgreSQL skips, 221
  frontend tests, and a 512-module production build. A final adversarial review
  found no P0-P2 issue.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Item

### P1 — Locked firmware gateway production release

- State: verified; ready to merge and deploy
- Scope: cookie-authenticated and rate-limited catalog/metadata/artifact
  delivery; signed catalog generation floor; exact bundle, partition, hash,
  model, hardware-revision, and protected-range verification; Admin
  catalog-only status; `serial=(self)` browser policy.
- Acceptance: production serves the new API through authentication, missing
  trust/catalog state fails closed without secrets, the browser page remains
  visibly locked and never requests a port, all seven services stay healthy,
  and Alembic remains `d1e2f3a4b5c6`.
- Next: merge the reviewed candidate, validate the tracked Caddyfile, deploy
  the exact commit, and run health/auth/catalog/Admin postflight checks.

## Near-Term Terminal Queue

- Complete the bounded `@RET1` Web Serial protocol using ephemeral P-256 ECDH,
  HKDF-SHA256, AES-GCM, signed one-time enrollment tickets, and power-loss-safe
  two-slot configuration.
- Add owner-scoped per-device credentials after a new migration based on exact
  `d1e2f3a4b5c6`; preserve legacy terminals while preventing enrolled devices
  from reappearing through spoofable MAC auto-registration.
- Run physical E1001/E1002 enrollment, interrupted-commit, preserve-config,
  ROM-recovery, and browser qualification. No compatible serial device is
  currently attached to the development host; E1004 remains blocked.
- Remove firmware `setInsecure()`, establish trusted time and CA validation,
  then design signed A/B OTA and automatic rollback as later milestones.

## Safety Constraints

- The shipped browser installer has no serial request, artifact download,
  erase, write, esptool, or dynamic flashing path. Its browser-signature,
  secure-provisioning, and HIL gates remain fixed false.
- Production defaults contain no trusted firmware public key, approved catalog,
  positive generation floor, or browser-flash enablement. Do not stage or
  enable a release as part of this deployment.
- Firmware signing private keys remain offline and separate from the future
  online enrollment-signing key. Never put either in Git, browser code, or the
  artifact tree.
- The partially implemented secure-enrollment firmware branch is preserved in
  its clean worktree after an agent capacity interruption; it is not reviewed,
  committed, merged, released, or eligible for hardware use.
- Real production mail and calendars remain read-only during automated QA.
