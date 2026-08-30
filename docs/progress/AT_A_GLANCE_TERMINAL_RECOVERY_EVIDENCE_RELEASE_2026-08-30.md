# At a Glance terminal recovery-evidence release — 2026-08-30

## Outcome

At a Glance now understands firmware candidate.5's battery-quality and exact
runtime recovery evidence. The firmware validates or rolls back a pending A/B
image before normal device work, while the application rejects explicitly
invalid battery bursts and parses the new identity without weakening
candidate.4 compatibility.

Exact released application/runtime commit:
`35e3700e8a22eabf49e701fb873d4662d5b7abdc`.

Exact private firmware `main` commit:
`f23d6302ae4bc64326f385fe44593e2ec47febd0`
(`0.2.0-candidate.5`). Exact-main Actions run: `33338824057`.

## Delivered firmware evidence

- Samples battery voltage seven times, reports the median, spread, count, and
  explicit validity, and requires fresh valid evidence at the write boundary.
- Validates the complete six-entry E1001/E1002 `ab-v1` runtime table rather
  than relying only on compiled partition constants. E1004 remains exact
  single-slot and OTA-ineligible.
- Embeds and reports the exact source build ID, running partition, image state,
  boot count, validation result, and layout through strict RET1 status v2.
- Runs the pending-image gate before enrollment, display, networking, restart,
  or sleep. A pending image must prove enabled/keyed OTA policy, durable boot
  count, enrolled NVS configuration, read-only LittleFS, and two frame-sized
  PSRAM allocations before it is marked valid; failure invokes rollback.
- Rejects a bring-up build combined with enabled OTA. Generic bundles remain
  unkeyed, enrollment-disabled, OTA-disabled, and free of credentials.

## Delivered application boundary

- `X-Battery-Valid: 0` prevents an invalid candidate.5 percentage or voltage
  from entering the battery predictor. Older firmware without the header keeps
  the existing range-bounded behavior.
- Backend and browser codecs accept only the exact versioned RET1 status shape.
  Status v2 carries the candidate.5 runtime identity; extra, mixed-version, or
  malformed fields fail closed.
- Exact candidate.4 status v1 remains enrollment-compatible, but its unavailable
  runtime fields map to unknown/invalid and cannot prove a recovery boot.
- No migration, dependency, Caddy, systemd, firmware artifact, browser Serial,
  device write, OTA offer, artifact, or acknowledgement route was added.

## Locked boundary

Software evidence is not hardware qualification. Production still has no
browser signing key, online enrollment key, positive approved catalog,
release/model HIL allowlist, durable terminal OTA event ledger, or device OTA
transport. The browser cannot request a port, download firmware bytes, flash,
erase, provision Wi-Fi, or update a terminal. Candidate.5 has not been installed
on a physical terminal by this release.

## Verification

- The consolidated application gate passed 607 backend tests with 47 expected
  opt-in PostgreSQL/external skips, 336 frontend tests, and a 532-module local
  production build.
- Firmware tooling passed 23 tests; OTA host safety passed three tests; the
  enrollment host suite, keyed synthetic RET1/OTA compile and marker check, and
  clean E1001/E1002/E1004 builds passed. The locally packaged release bundle
  verified exact build identity and disabled/unkeyed generic artifacts.
- Exact-main Actions run `33338824057` passed keyed guards, cross-language and
  host safety, all-model reproducibility, manifest verification, and immutable
  bundle publication.
- Diff, secret, generated-artifact, and write-path review found no credential,
  enabled production flag, browser transport, or terminal schema allocation.

## Combined production evidence

- The terminal runtime was rebased onto Universal Snooze runtime
  `231173b2d18966b603ed2f824f68380f8087de2c` and released as exact application
  commit `35e3700e8a22eabf49e701fb873d4662d5b7abdc`.
- Before the coordinated migration, backup
  `/var/backups/mailapp/maildb-pre-universal-snooze-20260830T2224Z.dump` was
  validated with `pg_restore -l`; its size is 1,383,720,058 bytes and SHA-256 is
  `049ad0aae0b0cb3ee4cc3b2e34585cd5fe248b1654fbd2127d42a195b2a9ec16`.
- Production advanced from `f3a4b5c6d7e8` to Universal Snooze revision
  `a4b5c6d7e8f9 (head)`. Candidate.5 itself is migration-free. The aggregate
  `email_snoozes` count remained zero after deployment; no row content was
  inspected.
- Production built 534 frontend modules. All seven services are active, public
  health is `ok`, anonymous `GET /api/snoozes` returns 401, and warning-or-higher
  logs are empty after the replacement processes became active. The retired API
  hit its known stop timeout one second before that boundary.
- Authenticated read-only browser QA loaded the first-class empty Snoozed mailbox
  and the At a Glance 16:9 preview with battery guidance. No message was opened
  and no mail, calendar, display, terminal, enrollment, or firmware state was
  mutated.

## Rollback

Revert the application terminal commit to the Universal Snooze runtime, rebuild
the frontend, and restart only affected application services. Keep Alembic at
`a4b5c6d7e8f9`; the terminal slice has no database downgrade. Candidate.5 is not
installed on a device, so reverting private firmware source to candidate.4
changes only the future release source. Keep every enrollment/browser/OTA flag
false during rollback.

## Remaining work

1. Qualify dedicated E1001/E1002 hardware for RET1 enrollment, trusted TLS,
   the one-time USB A/B partition migration, interrupted writes, pending-image
   validation, automatic rollback, power loss, preserved configuration, and
   ROM recovery.
2. Only after that evidence passes, pin a reviewed browser public key and add
   Web Serial behind the existing independent policy and recovery gates.
3. Then allocate a durable terminal OTA event ledger from the current schema
   head and add device-authenticated offer, artifact, and acknowledgement
   transport. E1004 remains excluded.
