# Current Status

Last updated: 2026-08-30

## Active Objective

Complete and review confidential serial enrollment, per-device credential
boundaries, and an E1001/E1002 hardware qualification plan on top of the now
deployed fail-closed firmware gateway. Keep every browser write and OTA path
disabled until physical recovery evidence exists.

## Baseline

- The exact reviewed/deployed terminal gateway release is
  `69a5622659d39709a07334b04aa8f517a8b12728`, built on outbound docs closeout
  `6d8e94584f21a6090b16cc697bd4579c3a3c0400`. A subsequent docs-only closeout
  records postflight without changing runtime behavior.
- Production Alembic is `d1e2f3a4b5c6 (head)`. The firmware gateway has no
  schema or dependency change and must not advance that head.
- All seven checked production services are active, public health is `ok`, the
  new frontend asset returns 200, and mailapp/Caddy have no new
  warning-or-higher entries or automatic restarts.
- The private firmware repository is cleanly released at
  `1b5364e5d4b48666b3ecfd0cf8ba31ab7f4bd5c4`. GitHub Actions run
  `33322241770` reproducibly built and strictly verified all three model
  bundles; those artifacts remain explicitly unsigned, single-slot, and
  non-installable.
- The gateway application commit is `0fe2ef7`. Full combined validation passed:
  459 backend tests plus 13 opt-in PostgreSQL skips, 221 frontend tests, and a
  512-module local production build; the clean host build contained 514
  modules. A final adversarial review found no P0-P2 issue.
- Anonymous firmware catalog access returns 401. Signed-in Admin reports the
  absent trust/catalog as unavailable, visibly lists all three unmet safety
  gates, contains no installer buttons, and produced no browser warning/error
  or permission prompt. The live policy includes `serial=(self)`.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Active Work Item

### P1 — Secure serial enrollment implementation audit

- State: active; partial firmware work preserved after agent capacity failure
- Scope: bounded `@RET1` NDJSON, P-256/ES256, HKDF-SHA256, directional
  AES-256-GCM, transcript binding, monotonic generation, two-slot atomic
  configuration, one-time persisted server tickets, credential
  activation/rotation/revocation, and legacy-route isolation.
- Acceptance: deterministic cross-language vectors and fault injection pass;
  secrets never enter logs or persistence outside the device; power loss
  always selects a complete old or new configuration; current firmware boot
  behavior remains compatible; and no qualification flag changes.
- Next: audit every partial firmware file before continuing it, complete safe
  host/CI tests, then obtain a physical E1001/E1002 for HIL rather than claiming
  qualification from builds alone.

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
