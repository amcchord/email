# Current Status

Last updated: 2026-08-30

## Active Objective

Complete and review confidential serial enrollment, per-device credential
boundaries, and an E1001/E1002 hardware qualification plan on top of the now
deployed fail-closed firmware gateway. Keep every browser write and OTA path
disabled until physical recovery evidence exists.

## Baseline

- The exact reviewed/deployed Email application release is
  `61e0ad8f47bd12dff07b7c0e695ea3f5680af7a4`; its deployment record is
  `0c92e59bb47101f24a9c08afd692296cda8d47c0`. It includes the terminal gateway
  runtime `69a5622659d39709a07334b04aa8f517a8b12728` unchanged.
- Production Alembic is `e2f3a4b5c6d7 (head)`. Durable draft sessions own that
  additive revision; future terminal schema work must branch from this exact
  head rather than the prior `d1e2f3a4b5c6` baseline.
- All seven checked production services are active, public health is `ok`, the
  new frontend asset returns 200, and the replacement API and cron worker have
  no post-start warning-or-higher entries or automatic restarts. The retired
  API process required systemd's 90-second graceful-stop timeout before the
  reviewed replacement started successfully.
- Durable drafts passed 472 backend tests plus 21 opt-in PostgreSQL skips, 256
  frontend tests, eight focused PostgreSQL tests, the full `e2 → d1 → e2`
  migration cycle, generated-provider safety QA, and a 518-module production
  build. Read-only production Compose QA produced no browser error and left all
  three new draft tables empty.
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

- State: active; private firmware candidate.3 is merged at
  `fd8671bd9a3641ecf9af37491bb8a00607dec4d6`, while its exact-main keyed and
  reproducibility run remains the release gate. No Email enrollment/API slice
  or production enablement has started.
- Scope: bounded `@RET1` NDJSON, P-256/ES256, HKDF-SHA256, directional
  AES-256-GCM, transcript binding, monotonic generation, two-slot atomic
  configuration, one-time persisted server tickets, credential
  activation/rotation/revocation, and legacy-route isolation.
- Acceptance: deterministic cross-language vectors and fault injection pass;
  secrets never enter logs or persistence outside the device; power loss
  always selects a complete old or new configuration; current firmware boot
  behavior remains compatible; and no qualification flag changes.
- Next: confirm the exact-main firmware run, add strict schema-2 manifest
  support, then implement fail-closed server/browser RET1 enrollment from the
  exact Email baseline recorded above. Obtain a physical E1001/E1002 for HIL
  rather than claiming qualification from builds alone.

## Near-Term Terminal Queue

- Complete the bounded `@RET1` Web Serial protocol using ephemeral P-256 ECDH,
  HKDF-SHA256, AES-GCM, signed one-time enrollment tickets, and power-loss-safe
  two-slot configuration.
- Add owner-scoped per-device credentials after a new migration based on exact
  `e2f3a4b5c6d7`; preserve legacy terminals while preventing enrolled devices
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
- The merged private RET1 firmware candidate remains generic-bundle unkeyed,
  disabled, and ineligible for hardware use until its exact-main run and later
  physical qualification pass. It changed no Email production state, key,
  signed release, or device.
- Real production mail and calendars remain read-only during automated QA.
