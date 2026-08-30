# At a Glance firmware safety release — 2026-08-30

## Outcome

At a Glance now has robust, bounded battery guidance and a production-visible
firmware/OTA safety posture. Private firmware candidate.4 removes insecure TLS
and provides the disabled A/B update primitives needed for physical
qualification. The application can verify exact signed metadata in the browser
and explain OTA blockers, but it cannot request a serial port, download firmware
artifacts, write or erase a terminal, offer an OTA release, or record an update
event.

Exact released application/runtime commit:
`92d22a54c49ec9b4ba74042ece01a1c6d527ea07`.

Exact private firmware `main` commit:
`2e835543dfe7095fe65a4f62b0da9e3c91ca47d1`
(`0.2.0-candidate.4`).

## Delivered firmware boundary

- Every HTTPS request requires a fresh bounded SNTP result and a plausible
  2024–2041 UTC clock before hostname and CA verification against the compiled
  ISRG Root X1/X2 bundle. Plaintext, scheme-relative URLs, redirects, downgrade,
  and `setInsecure()` are absent.
- E1001/E1002 use exact `ab-v1`: existing NVS, `ota_0`, LittleFS, and coredump
  offsets remain fixed and an equal `ota_1` is appended. E1004 retains its exact
  single-slot table and is hard-ineligible for OTA.
- The disabled OTA writer verifies a raw Ed25519 signature over the exact
  six-field `OTA1` descriptor, requires its SHA-256 content address, checks the
  exact model/layout/version/size/hash, enforces at least 3700 mV, streams only
  into the inactive slot, and exposes pending-image valid/rollback APIs.
- The writer is unkeyed, compile-time disabled, and not called by the normal
  device loop. Schedule offers, OTA artifact transport, event reporting, boot
  self-test integration, and physical qualification do not exist yet.

## Delivered application boundary

### Battery guidance

- Retains sparse history for 90 days and predicts only from percentage-bearing
  samples, so a newer voltage-only row cannot make old percentage data fresh.
- Collapses noisy readings into bounded six-hour medians and uses a robust
  pairwise discharge slope with direction and residual guards.
- Resets a discharge segment only after a corroborated rise. Without an
  external-power signal it reports `possible_charging`, never active charging.
- Suppresses inconsistent and greater-than-one-year projections, keeps
  low-charge warnings authoritative, and presents coarse day-level confidence.

### Browser verification

- Fetches only authenticated exact manifest and detached signature bytes.
- Recomputes the content-addressed release ID and verifies raw Ed25519 with Web
  Crypto before comparing strict duplicate-free JSON against source-pinned
  toolchain, model, partition, artifact, and qualification contracts.
- The production source-pinned key map is intentionally empty. There is no
  artifact download, `requestPort`, esptool, erase, flash, Wi-Fi, or configuration
  write implementation in the shipped browser.

### OTA control-plane foundation

- Parses and verifies the same exact six-field descriptor as candidate.4 and
  links it to signed parent release/model evidence.
- Requires independent server enablement, a positive catalog floor, an exact
  release/model/key/hardware-revision HIL allowlist, parent OTA eligibility, and
  durable idempotent event persistence before policy can become ready.
- Exposes only authenticated `GET /api/terminal/firmware/ota/capabilities`.
  Release evidence and event persistence are deliberately unwired, so the
  endpoint cannot become ready and no offer/artifact/event route exists.

## Verification

- Application: 591 backend tests passed with 35 expected skips. The frontend
  run passed 320 tests and identified one stale read-only surface assertion;
  after correcting that exact endpoint expectation, the focused test passed and
  the 528-module production build completed.
- Firmware: 22 Python host tests, enrollment host tests, TLS host tests,
  partition-layout tests, and PlatformIO E1001/E1002/E1004 builds passed.
  Exact-commit run `33335099281` and exact-main run `33336177159` passed keyed
  RET1, all-model builds, reproducibility, manifest verification, and immutable
  bundle publication.
- Release review: `git diff --check`, secret scanning, and explicit serial/write
  path scanning passed. No dependency, migration, Caddy, systemd, or production
  configuration change was required.

## Production evidence

- GitHub `main`, the feature branch, and production first reached exact runtime
  `92d22a54c49ec9b4ba74042ece01a1c6d527ea07` from Scheduled Send closeout
  `584e3e0c52f209c6e93e6a7abdaf93727548fbba`.
- Only `mailapp` restarted. Its retired process reached the existing bounded
  graceful-stop timeout; the replacement is active with zero restarts and no
  post-start warning-or-higher entries.
- Production built 530 modules. All seven services are active, public health is
  `ok`, anonymous OTA capability access returns 401, Git is clean, and Alembic
  remains `f3a4b5c6d7e8 (head)`.
- Authenticated read-only QA showed honest learning/stale battery copy and the
  four default OTA blockers. The installer remained explicitly incapable of
  requesting Serial, downloading an artifact, writing, erasing, or updating a
  device. No application or terminal state was mutated.

## Rollback

Revert the application runtime commit, rebuild the frontend, and restart only
`mailapp`. No database downgrade, dependency rollback, worker restart, or Caddy
change is involved. Candidate.4 has not been installed on a physical terminal;
reverting its private-repository commit changes only the future release source,
not a deployed device. Keep all browser and OTA flags false during rollback.

## Remaining work

1. Qualify E1001/E1002 RET1, trusted TLS, USB A/B partition migration,
   interrupted writes, pending-image validation, automatic rollback, power
   gates, preserve-config behavior, and ROM recovery on dedicated hardware.
2. Only then pin a reviewed browser public key and introduce the Web Serial
   transport behind all existing gates.
3. Design the durable OTA event ledger from observed HIL evidence, then add
   device-authenticated offer, artifact, and acknowledgement endpoints as a
   separate additive release. E1004 remains excluded.
