# Terminal firmware management and qualification

This document describes the implemented, default-locked browser/OTA foundation
and the remaining qualification path to real device writes. The image wire
contract remains in [`server-protocol.md`](server-protocol.md), and panel
formats remain in [`firmware-variants.md`](firmware-variants.md).

Baselines verified on 2026-08-30:

- Email OTA control-plane runtime `9253eb4`, deployed on Conversation-first
  Inbox closeout `075a475`, with Alembic revision `c6d7e8f9a0b1` descending
  directly from prior production head `b5c6d7e8f9a0`;
- private `reterminal-color` `main` at
  `5db28243f8dc56309492ae926c0b5186a5fffeb7` (`0.2.0-candidate.6`), with the
  default-disabled transport coordinator isolated at `949bc87`; and
- exact candidate.6 Actions run `33341323506`, plus green host safety and
  generic E1001/E1002/E1004 and keyed E1002 transport builds for `949bc87`.

## Status today

| Capability | Implemented today | Important limit |
| --- | --- | --- |
| USB build and flash | PlatformIO environments, pinned dependencies/toolchain evidence, exact per-model partitions, deterministic build metadata, and immutable checksummed bundles exist for E1001, E1002, and E1004. | Current artifacts truthfully declare `signed=false`; no browser may install them. Command-line PlatformIO/esptool remains the only qualified write path. |
| Browser firmware gateway | Cookie-authenticated, rate-limited catalog/manifest/signature/artifact routes verify a signed approval catalog and every bundle byte from local immutable storage. The browser independently verifies exact manifest bytes with SHA-256 and detached Ed25519 against source-pinned contracts. | Production defaults contain no trusted key or approved catalog, and the browser key map is empty. The Admin surface is metadata-only; serial, artifact-download, provisioning, and write gates remain false. |
| Runtime configuration | Candidate.6 retains bounded RET1 and three-slot atomic NVS configuration while keeping generic release images unkeyed, enrollment-disabled, and free of credentials. Exact status v2 adds read-only partition, boot-state, and source-build identity while the v1 handshake transcript stays unchanged; the application remains compatible with candidate.4 status v1. | Production has no online enrollment key or qualified release/model allowlist, and the shipped browser does not import serial transport. Command-line `uploadfs` remains the only hardware workflow until HIL passes. |
| Application partitions | Candidate.6 validates the complete six-entry `ab-v1` table at runtime on E1001/E1002: the legacy NVS, `ota_0`, LittleFS, and coredump ranges are unchanged and `ota_1` is appended at `0x400000`. E1004 remains exact single-slot and OTA-ineligible. | Existing physical E1001/E1002 devices still need a qualified USB migration to install the new partition table. No production model/revision is HIL-qualified for OTA. |
| Device check-in | Active enrolled firmware reports bounded model, build, wake, battery, RSSI, memory, boot, image, exact source-build, and running-slot metadata. Candidate.6 summarizes a seven-sample battery burst with median, spread, count, and explicit validity; the server excludes explicitly invalid readings from its sparse 90-day predictor. | The legacy shared terminal URL is routing data, not OTA authentication. Current hardware has no direct external-power signal, so OTA uses a fresh measured 4000 mV/80% reserve and forecasts never gate a write. |
| TLS and OTA | The isolated coordinator at `949bc87` uses fresh bounded SNTP, CA/hostname validation, no redirects/downgrade, exact scoped offers, bounded artifact reads, Ed25519/content-address verification, inactive-slot streaming, a CRC-protected NVS attempt/event record, pending validation, and rollback/recovery reporting. The server persists idempotent attempts/events in PostgreSQL. | Generic E1001/E1002/E1004 artifacts remain transport-disabled, writer-disabled, and unkeyed. Server enablement, HIL map, and rollout default closed; no production offer or physical write is authorized. E1004 is hard-rejected. |
| E1004 | The firmware builds reproducibly and its full-refresh dual-controller implementation is present. | No hardware qualification exists; E1004 browser installation and OTA are explicitly ineligible. |

The personal checkout under `~/Development/reTerminalColor` remains dirty and
must not be used as a release source. Firmware work uses a separate clean
worktree and the private GitHub repository. Reproducibility and an A/B table do
not make the current unsigned, default-disabled output safe to install.

## Safety invariants

These are release blockers, not preferences:

1. A device never installs an artifact for a different model, panel, chip,
   flash size, hardware revision, or partition layout.
2. Download success is not install success. Bytes are SHA-256 checked and an
   asymmetric signature over the hash and release metadata is verified before
   the boot partition changes.
3. A newly booted image remains pending until it completes self-tests. A reset,
   watchdog, brownout, or deep sleep before validation causes bootloader
   rollback to the previous slot.
4. The previous known-good application slot is not erased during an OTA
   attempt.
5. Production HTTPS validates a public CA chain. There is no
   `setInsecure()` fallback and no automatic downgrade to HTTP.
6. Wi-Fi credentials entered in the installer stay between the browser and the
   attached device. They never enter a URL, application request, analytics,
   browser persistence, build artifact, or server log.
7. USB ROM-bootloader recovery remains documented and tested for every release.
8. OTA is deferred when power is unsafe. Predicted remaining life can inform
   the user, but a prediction alone is never the write-safety gate.

## Target architecture

```text
CI build per exact model
  -> immutable artifact bundle + hashes
  -> signed release manifest
       |                         |
       | first install/recovery  | normal managed update
       v                         v
browser + Web Serial        schedule offer -> device-authenticated manifest
  -> ESP ROM bootloader       -> write inactive slot
  -> A/B partition layout     -> verify -> reboot pending
  -> local serial config      -> self-test -> valid or rollback
       |                         |
       +----------- acknowledgement events ----------> server
```

The browser installer and OTA use the same CI artifacts and signed release
metadata. They differ only in transport and permitted flash regions.

## Authenticated gateway foundation

Production serves firmware bytes only from a local, operator-staged tree. It
does not fetch GitHub releases during a request:

```text
/opt/mail/data/terminal-firmware/
  catalog.json
  catalog.sig
  bundles/
    <sha256-of-manifest>/
      manifest.sig
      payload/
        manifest.json
        SHA256SUMS
        toolchain-evidence.txt
        reterminal_e1001/...
        reterminal_e1002/...
        reterminal_e1004/...
```

`catalog.sig` is a raw 64-byte Ed25519 signature over the exact `catalog.json`
bytes. The catalog has a positive, monotonically increasing generation and at
most one approved release. Each release ID is the manifest SHA-256; its
detached signature and payload live under that content-addressed directory.
The same configured trust set verifies the catalog and manifest. The service
rejects unlisted files, directories, symlinks, non-regular files, path races,
wrong hashes, partition drift, unsafe factory-image composition, and catalog
generations below the externally pinned floor.

Runtime configuration is deliberately fail-closed:

```text
TERMINAL_FIRMWARE_STORAGE_PATH=/opt/mail/data/terminal-firmware
TERMINAL_FIRMWARE_TRUSTED_SIGNING_KEYS={}
TERMINAL_FIRMWARE_MINIMUM_CATALOG_GENERATION=0
TERMINAL_FIRMWARE_BROWSER_FLASH_ENABLED=false
TERMINAL_OTA_ENABLED=false
TERMINAL_OTA_QUALIFIED_RELEASES={}
TERMINAL_OTA_ROLLOUT_PERCENTAGE=0
```

Do not put signing private keys in the application environment or artifact
tree. The trust-key value contains only key IDs and public Ed25519 keys. Before
any future enablement, stage the tree as root-owned/read-only, validate it
offline, assign a never-reused higher catalog generation, pin that positive
generation in configuration, and restart into a catalog-only verification
window. The browser flag alone is insufficient: a zero generation, unsigned or
unqualified model, missing hardware revisions, or any validation error keeps
downloads blocked.

The shipped Admin component requests catalog metadata, exact manifest/signature
evidence, and the read-only OTA capability lock state. It observes HTTPS, Web
Serial, and Web Locks support without requesting a port. There is no esptool
dependency, artifact download loop, erase command, serial write, or dynamic
flashing code in the production bundle.

## Browser installation and local provisioning

Use a small, same-origin, static installer backed by a pinned version of
`esptool-js`. Web Serial requires a secure browser context, an explicit user
gesture, and a supported Chromium-family desktop browser. Keep the existing
PlatformIO/esptool command-line flow as the fallback.

CI must publish a bundle for each exact firmware model. The bundle contains
only generated outputs, never source secrets:

- bootloader, partition-table, boot-selection/OTA-data initializer, application,
  and an optional blank LittleFS image;
- the generated flash address for every file rather than addresses copied into
  browser code;
- model, supported hardware revisions, ESP chip family, required flash bytes,
  application version, Git commit, toolchain lock, and partition-layout ID;
- byte length and SHA-256 for every file; and
- the release signature described below.

Before writing, the installer must identify the ESP chip and flash capacity,
download and hash every artifact, verify the signed metadata, and require the
operator to confirm the physical terminal model. USB VID/PID and ESP32-S3 chip
identity cannot distinguish E1001, E1002, and E1004. The installer must refuse
unknown hardware revisions and must never infer the panel from a MAC address or
schedule `variant` query.

The result page reports success only after the loader's flash verification and
after reconnecting to the rebooted firmware to read back its model, version,
and partition-layout ID. A failed or interrupted write returns the user to ROM
bootloader recovery instructions; it is not reported as a partial success.

### First-install partition migration

Candidate.6 builds E1001/E1002 with `ab-v1`, but a device running the prior
single-slot partition table cannot safely rewrite that table through OTA. The
first move is therefore a one-time USB/Web Serial migration:

1. Use the reviewed E1001/E1002 `ab-v1` table: NVS `0x9000/0x5000`, OTA data
   `0xe000/0x2000`, `ota_0` `0x10000/0x300000`, LittleFS
   `0x310000/0xE0000`, coredump `0x3F0000/0x10000`, and equal `ota_1`
   `0x400000/0x300000`. E1004 stays outside this migration.
2. Preserve the first application, NVS, LittleFS, and coredump byte ranges.
   Treat ROM bootloader recovery—not power-loss atomicity—as the partition-table
   migration safety net.
3. Flash only addresses from the CI-generated bundle. Do not run a whole-chip
   erase as part of the normal installer.
4. If LittleFS is preserved byte-for-byte, leave it untouched and verify a
   no-auto-format mount. If a model's filesystem must move or resize, install a
   known blank filesystem and require configuration again. Do not extract an
   existing Wi-Fi password into the browser.
5. Boot the new image, confirm `partition_layout=ab-v1`, both app partitions,
   filesystem health, and the exact firmware model, then provision the device.

Partition offsets and the filesystem offset remain stable after `ab-v1`; normal
OTA writes only the inactive application slot. A future partition change is
another explicitly named USB migration, not an ordinary OTA.

### Confidential, server-authorized serial enrollment

The implemented Email-side contract, state machine, and production enablement
checklist are maintained in [`secure-enrollment.md`](secure-enrollment.md).

After the generic image boots, the installer reopens the same CH340 serial
port and speaks bounded newline-delimited frames prefixed with `@RET1 `. Normal
diagnostic lines remain separate and must never contain credentials. The target
protocol uses ephemeral P-256 ECDH, HKDF-SHA256, directional AES-256-GCM keys,
strict message sequences, and an ES256 enrollment ticket signed by a dedicated
online application key. P-256 is supported by both the pinned ESP32 toolchain
and browser Web Crypto.

The signed ticket binds both ephemeral public keys and nonces, the exact boot
transcript, model, reported identifiers, approved firmware release, one-time
ticket ID, monotonically increasing configuration generation, credential ID,
and server-controlled terminal endpoint. The browser encrypts the Wi-Fi
configuration locally and sends only a hash/verifier needed for one-time,
transactional ticket consumption to the server. SSID/password values never
enter a URL, server log, artifact, analytics system, or browser persistence.

Firmware verifies the signed ticket before decrypting. It stages configuration
into one of three compact NVS slots, commits and reads it back, then publishes a
new marker only after full schema/hash validation. Three slots preserve the
active and immediate rollback records while a later transition is staged. Boot
selects the highest valid generation. An interrupted commit therefore yields a
complete retained record, never a partial configuration. A durable device-side
rollback still requires a fresh signed ticket with a higher anti-replay
generation; the server's old scoped URL is only a bounded recovery grace.

The ESP32 factory MAC, optional eFuse UID, chip revision, and flash ID are
inventory identifiers, not attestation. Current devices have no Secure Boot,
flash encryption, or protected per-device eFuse key, and the ROM downloader is
open. This milestone must be described as confidential, server-authorized
enrollment under physical-cable trust—not proof of genuine hardware or approved
firmware. Manufacturing-grade identity is a separate irreversible project.

The existing shared terminal code remains a legacy route credential. A pending
first enrollment preserves that route only for the same owner so an interrupted
serial write does not strand the device. Enrolled and revoked devices require a
distinct per-device credential and cannot be upserted or reassigned through a
spoofable MAC on the legacy path. Migration `f3a4b5c6d7e8` implements the
server state, activation, bounded one-generation rollback URL, and owner
revocation, but production enablement and browser transport remain blocked on
physical E1001/E1002 HIL.

## TLS and device-side update sequence

Candidate.6 implements the transport prerequisite: every wake requires a fresh
SNTP callback within 15 seconds and a plausible 2024–2041 clock, then validates
the hostname and chain against compiled ISRG Root X1/X2. Certificate, clock, or
handshake failure fails closed into the normal sleep/backoff path. Plain HTTP,
scheme-relative URLs, redirect following, and `setInsecure()` are absent. The
bundle must rotate before X2 expires in 2040 or before production changes CA.

Candidate.6 also implements the local signed writer and calls the pending-image
validation/rollback gate before enrollment, panel, network, restart, or sleep
work. A pending image must prove the enabled/keyed policy, durable boot counter,
preserved enrolled configuration, read-only LittleFS mount, and two frame-sized
PSRAM allocations. Firmware commit `949bc87` adds the separately gated HTTPS/NVS
coordinator and lifecycle transport. Generic artifacts still compile both
writer and transport out, so no enabled/keyed image may be distributed without
the exact physical qualification and release process below.

For each offered update, firmware performs this sequence:

1. Confirm exact model, hardware revision, chip, flash size, current layout,
   minimum source version, and battery/power gates before downloading.
2. Fetch the device-authenticated manifest over CA-validated HTTPS. Verify its
   signature before trusting its artifact URL or metadata.
3. Stream the application into the inactive OTA partition while computing
   SHA-256. Bound content length, time, retries, and awake duration.
4. Compare length and hash, verify the signature-covered release identity, call
   the ESP OTA finalization APIs, and only then select the new boot partition.
5. Persist the attempt/offer ID and emit `staged`; reboot without refreshing the
   panel.
6. On the new slot, run bounded self-tests for model/layout, NVS, LittleFS,
   memory, Wi-Fi, and CA-validated server connectivity. Normal mounts must not
   auto-format a damaged filesystem during this validation.
7. Mark the app valid before any deep sleep, then emit `succeeded`. If validation
   fails or the device resets first, ESP-IDF rollback returns to the prior slot;
   the prior image emits `rolled_back` with the retained attempt ID.

Do not burn Secure Boot, flash-encryption, or anti-rollback eFuses from a general
browser installer. Application-level signature verification protects the OTA
path. Secure Boot v2 can later protect physical/serial replacement too, but it
requires a separate factory policy, key custody, signed recovery images, and an
irreversibility review.

## Server contract

Keep the existing schedule schema backward compatible by adding an optional
`firmware` offer. Old firmware ignores it. Transport metadata is not trusted
artifact metadata; the content-addressed descriptor is verified separately.
Example:

```json
{
  "schema_version": 1,
  "next_checkin_sec": 900,
  "image": { "url": "image.bmp", "etag": "img-…", "format": "bmp4-spectra6-800x480" },
  "firmware": {
    "schema_version": 1,
    "offer_id": "11111111-1111-4111-8111-111111111111",
    "attempt_id": "22222222-2222-4222-8222-222222222222",
    "release_id": "<sha256-of-exact-ota-descriptor-bytes>",
    "version": "0.3.0",
    "manifest_url": "/terminal/device/…/firmware/…/manifest.json",
    "signature_url": "/terminal/device/…/firmware/…/manifest.sig",
    "application_url": "/terminal/device/…/firmware/…/application.bin",
    "event_url": "/terminal/device/…/firmware/events",
    "required": false
  }
}
```

Candidate.5 defines an exact six-field OTA descriptor. Its detached signature
is 64 raw Ed25519 bytes over the exact descriptor bytes; `release_id` is the
lowercase SHA-256 of those same bytes. The device verifies before trusting any
parsed field:

```json
{
  "firmware_sha256": "<64-lowercase-hex>",
  "firmware_size": 1234567,
  "layout": "ab-v1",
  "model": "E1002",
  "schema_version": 1,
  "version": "0.3.0"
}
```

The descriptor intentionally excludes URLs, rollout state, and power policy.
The server must link it to an independently verified signed parent bundle with
the same model, version, `ab-v1` layout, application length/hash, signing key,
positive catalog generation, and exact hardware-revision HIL evidence. Embed
only reviewed public verification keys in qualified firmware; private signing
keys belong in the offline signing boundary, never in this repository, the
application environment, browser, terminal, or database.

The authenticated `GET /api/terminal/firmware/ota/capabilities` surface exposes
these gates without enabling delivery. The application now includes the
attempt/event ledger and exact offer/artifact/event routes, but production has
no installed eligible descriptor, HIL allowlist, confirmed device revision,
nonzero rollout, or enablement. Effective OTA therefore remains locked.

Server-side records separate:

- **release:** immutable signed artifact metadata and lifecycle
  (`draft`, `approved`, `active`, `paused`, `revoked`);
- **offer:** one release/device eligibility decision and rollout cohort; and
- **event:** append-only, idempotent device acknowledgements from which the
  latest attempt state is projected.

The acknowledgement endpoint accepts a per-device-authenticated body such as:

```json
{
  "schema_version": 1,
  "event_id": "33333333-3333-4333-8333-333333333333",
  "attempt_id": "22222222-2222-4222-8222-222222222222",
  "offer_id": "11111111-1111-4111-8111-111111111111",
  "sequence": 2,
  "release_id": "<64-lowercase-hex-descriptor-sha256>",
  "state": "staged",
  "running_version": "0.1.0",
  "running_build_id": "0123456789abcdef0123456789abcdef01234567",
  "running_partition": "ota_0",
  "boot_count": 418,
  "reset_reason": null,
  "error_code": null
}
```

Allowed attempt states are:

```text
offered -> downloading -> staged -> booted_pending_validation -> succeeded
               |            |                    |
               +-> failed <-+                    +-> rolled_back
                                                     -> recovery_required
```

The server creates `offered`; devices create all later events. `event_id` makes
retries idempotent and `sequence` is monotonic per attempt. Received time is
server-owned; binding, state transition, source/target build, slot, and boot
identity are validated in the same transaction that appends the event and
updates the attempt projection. Firmware retains one canonical unsent event in
NVS so deep sleep or an outage does not erase the outcome. Never treat `staged`
or a version header as success; only a validated target build in the opposite
slot can emit `succeeded`.

Extend check-in telemetry with exact hardware model/revision, firmware build,
partition-layout ID, running slot, security counter, reset reason, OTA attempt
state, and power-source/charging state when hardware supports it. Continue
collecting the existing battery, RSSI, memory, boot, wake, and image fields.
Normalize and bound all device-supplied values. Predictions such as days to
empty are server-derived presentation data, not trusted device facts.

## Variant and power gates

- Publish separate application artifacts for E1001, E1002, and E1004 even when
  most source is shared. Gray is a render format, not a shipping firmware
  target.
- Require equality across the registered device model, running firmware model,
  signed manifest model, and installer selection. Any disagreement blocks the
  write and produces a bounded `variant_mismatch` event.
- Hardware revision allowlists are explicit. Unknown means blocked, not
  wildcard-compatible.
- Keep E1004 out of browser recommendations and OTA cohorts until its full and
  fallback refresh paths have passed physical panel, power, wake, and rollback
  tests and the stale stub documentation is reconciled.
- Gate OTA on conservative measured voltage, credible percentage, temperature
  if later available, and either external power or enough reserve for download,
  flash, verification, and two boots. If charging state cannot be measured,
  use a higher voltage floor and show “charge before updating.”
- Artifact fetch, verification, or write failure terminally fails that attempt.
  Only a previously persisted unsent event retries across wakes; the coordinator
  posts at most three lifecycle events per wake and requests a 300-second retry
  sleep. It never performs an awake-loop HTTP retry or panel refresh merely to
  report OTA progress.

## Staged rollout and recovery

Use deterministic cohorts derived from the device public UUID plus exact
descriptor `release_id`. A suggested
promotion is one physical lab unit, then canary, 10%, 25%, 50%, and 100%.
Promotion is manual at first and requires a minimum observation window plus
successful post-update check-ins; elapsed time alone is insufficient. Every
stage has pause/revoke controls and limits concurrent updates.

Before promotion, CI and hardware qualification must cover all three build
environments, signature/hash rejection, wrong-variant rejection, truncated
downloads, low battery, Wi-Fi loss, TLS/clock failure, power loss during each
write phase, watchdog during pending validation, successful rollback, and a
full browser rescue. E1004 remains a separate blocked cohort until qualified.

Recovery has three levels:

1. Automatic A/B rollback before validation.
2. A signed known-good release offered as a new, higher security-counter update
   when the currently valid app still checks in.
3. A browser “Rescue over USB” flow that uses the ESP ROM bootloader, exact
   model selection, and the last known-good full bundle. If configuration cannot
   be preserved safely, the user re-enters it locally.

A release is not complete until its rescue bundle is immutable and tested on a
device that has the immediately previous production partition layout.

## Milestones and exit gates

1. **Reproducible release discipline — complete:** a clean private repository,
   pinned toolchain, exact per-model layouts, deterministic double-build CI,
   checksums, strict manifest validation, and immutable artifacts exist. The
   resulting artifacts remain honestly unsigned and non-installable.
2. **Authenticated gateway and locked browser foundation — complete:** the
   application verifies a signed, generation-pinned, one-release catalog and
   exact bundle contents behind cookie auth and rate limits. The browser audits
   metadata only; it cannot request a port, download, erase, or write.
3. **Secure serial enrollment and HIL qualification — active:** the bounded
   `@RET1` P-256/AES-GCM protocol, three-slot configuration, schema-2 release
   claim, fail-closed server tickets, per-device activation, rollback grace,
   revocation, CA validation, and browser exact-byte Ed25519 preflight now have
   deterministic software tests. Production Web Serial transport and the
   repeatable physical E1001/E1002 interruption/recovery matrix remain. E1004
   stays locked.
4. **Browser first install:** add a pinned flashing implementation only after
   browser-side signature verification and milestone 3 pass. Flash exact
   preserve-config artifacts, verify ROM-loader output and rebooted identity,
   and keep a command-line rescue flow. The server and client write gates may
   then be changed through a separately reviewed release.
5. **A/B OTA canary — software-integrated, physically blocked:** authenticated
   offers/artifacts/events, the PostgreSQL ledger, signed descriptor/inactive-
   slot writer, durable NVS replay, and pending validation/rollback are wired
   behind independent default-closed gates. Before a one-device rollout,
   publish a signed/keyed transport-enabled release, physically migrate that
   E1001/E1002 to `ab-v1`, complete the exact HIL/rescue record, confirm its
   printed revision, install the migration/configuration, and enable only its
   bounded cohort. The conservative measured-power gate remains independent
   from the user-facing battery forecast.
6. **Managed rollout:** add cohort promotion, pause/revoke, key rotation,
   charging notices, dashboards, and recovery drills before wider release.

No milestone should be promoted merely because it builds. Its exit gate is a
repeatable artifact, device evidence for each eligible model, server-observed
acknowledgements, and a demonstrated recovery path.
