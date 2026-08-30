# Terminal firmware management roadmap

This document defines the safe path from the current USB-flashed prototype to
browser installation and managed over-the-air (OTA) releases. It is a roadmap,
not a description of capabilities already available in production. The image
wire contract remains in [`server-protocol.md`](server-protocol.md), and panel
formats remain in [`firmware-variants.md`](firmware-variants.md).

Baselines verified on 2026-08-30:

- Email application release `61e0ad8` as the production baseline before the
  additive secure-enrollment foundation;
- private `reterminal-color` `main` at
  `fd8671bd9a3641ecf9af37491bb8a00607dec4d6` (`0.2.0-candidate.3`); and
- exact-main GitHub Actions run `33329094948`, which passed the candidate's
  keyed RET1, cross-language, power-loss, reproducibility, manifest, and bundle
  verification gates.

## Status today

| Capability | Implemented today | Important limit |
| --- | --- | --- |
| USB build and flash | PlatformIO environments, pinned dependencies/toolchain evidence, exact per-model partitions, deterministic build metadata, and immutable checksummed bundles exist for E1001, E1002, and E1004. | Current artifacts truthfully declare `signed=false`; no browser may install them. Command-line PlatformIO/esptool remains the only qualified write path. |
| Browser firmware gateway | Cookie-authenticated, rate-limited catalog/manifest/signature/artifact routes verify a signed approval catalog and every bundle byte from local immutable storage. | Production defaults contain no trusted key or approved catalog. The Admin surface is metadata-only and all three write gates are fixed false. |
| Runtime configuration | Candidate.3 implements bounded RET1 and three-slot atomic NVS configuration while keeping generic release images unkeyed, enrollment-disabled, and free of credentials. The application now has a fail-closed policy, intent/ticket API, hashed per-device credentials, activation, bounded rollback, and revocation. | Production has no online enrollment key or qualified release/model allowlist, and the shipped browser does not import serial transport. Command-line `uploadfs` remains the only hardware workflow until HIL passes. |
| Application partitions | Explicit single-slot layouts and exact protected NVS/LittleFS ranges are release-verified. Normal preserve-config artifacts cannot overlap either range. | There is no second application slot, so safe A/B OTA and automatic rollback remain impossible. |
| Device check-in | Firmware reports bounded model, build, wake, battery, RSSI, memory, boot, and image metadata. The server stores sparse bounded battery history and gives conservative charge guidance. | MAC and the legacy shared terminal URL are routing data, not device authentication. Charging inference is not a write-safety proof. |
| TLS and OTA | No update transport is enabled. Firmware continues to fetch only schedule JSON and BMP images. | Runtime HTTPS still uses `setInsecure()`, and there is no A/B updater, acknowledgement, rollout, or boot rollback. OTA remains blocked. |
| E1004 | The firmware builds reproducibly and its full-refresh dual-controller implementation is present. | No hardware qualification exists; E1004 browser installation and OTA are explicitly ineligible. |

The personal checkout under `~/Development/reTerminalColor` remains dirty and
must not be used as a release source. Firmware work uses a separate clean
worktree and the private GitHub repository. Reproducibility does not make the
current unsigned, single-slot output safe to install.

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
```

Do not put signing private keys in the application environment or artifact
tree. The trust-key value contains only key IDs and public Ed25519 keys. Before
any future enablement, stage the tree as root-owned/read-only, validate it
offline, assign a never-reused higher catalog generation, pin that positive
generation in configuration, and restart into a catalog-only verification
window. The browser flag alone is insufficient: a zero generation, unsigned or
unqualified model, missing hardware revisions, or any validation error keeps
downloads blocked.

The shipped Admin component only requests and audits catalog metadata. It
observes HTTPS, Web Serial, and Web Locks support without requesting a port.
There is no esptool dependency, download loop, erase command, serial write, or
dynamic flashing code in the production bundle.

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

The current single-slot layout cannot safely rewrite itself into A/B. The first
move to `ab-v1` is therefore a one-time USB/Web Serial migration:

1. Build a reviewed `ab-v1` partition-table family with two equal application
   slots, OTA data, NVS, LittleFS, and coredump space. A per-model storage
   profile is acceptable because E1004 needs a much larger frame cache. Size
   both app slots from measured worst-case binaries plus explicit growth
   headroom. Do not freeze offsets in this roadmap.
2. Preserve the existing first application, NVS, and LittleFS offsets and sizes
   where validation shows that is safe; the unused upper portion of 32 MB flash
   can hold the second app slot. Treat ROM bootloader recovery—not power-loss
   atomicity—as the migration safety net.
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

CA validation is a prerequisite milestone. Replace `setInsecure()` with a
maintained CA bundle, establish usable time before the first verified HTTPS
request, and retain the last trusted time across sleep. First boot can use a
bounded SNTP bootstrap plus a compile-time lower bound. Certificate or clock
failure must fail closed, preserve the running image, and sleep with backoff.
Plain HTTP remains available only in an explicitly non-production development
build.

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
`firmware` offer. Old firmware ignores it. Example:

```json
{
  "schema_version": 1,
  "next_checkin_sec": 900,
  "image": { "url": "image.bmp", "etag": "img-…", "format": "bmp4-spectra6-800x480" },
  "firmware": {
    "offer_id": "01K…",
    "release_id": "terminal-e1002-0.2.0+4f52c9d",
    "version": "0.2.0",
    "manifest_url": "firmware/offers/01K….json",
    "required": false,
    "not_before": "2026-09-02T14:00:00Z"
  }
}
```

The manifest is an envelope whose decoded `signed_payload` bytes are verified
before parsing. This avoids ambiguous JSON canonicalization on the device:

```json
{
  "schema_version": 1,
  "signed_payload": "<base64url of exact UTF-8 payload bytes>",
  "signature": {
    "algorithm": "ecdsa-p256-sha256",
    "key_id": "terminal-ota-2026-01",
    "value": "<base64url signature>"
  }
}
```

The verified payload contains, at minimum:

- offer/release ID, semantic version, Git commit, channel, build timestamp, and
  expiry;
- exact model and hardware-revision allowlist, chip family, minimum flash
  bytes, current/target partition-layout IDs, and a monotonic security counter;
- immutable HTTPS artifact URL, content length, SHA-256, and application image
  type; and
- minimum source version plus minimum battery millivolts/percent.

Embed the active public verification key in firmware and support an overlap of
old and new `key_id` values for rotation. Private signing keys belong in the CI
signing boundary, never in this repository or the application database.

Server-side records should separate:

- **release:** immutable signed artifact metadata and lifecycle
  (`draft`, `approved`, `active`, `paused`, `revoked`);
- **offer:** one release/device eligibility decision and rollout cohort; and
- **event:** append-only, idempotent device acknowledgements from which the
  latest attempt state is projected.

The acknowledgement endpoint accepts a per-device-authenticated body such as:

```json
{
  "schema_version": 1,
  "event_id": "01K…",
  "attempt_id": "01K…",
  "offer_id": "01K…",
  "release_id": "terminal-e1002-0.2.0+4f52c9d",
  "state": "staged",
  "running_version": "0.1.0",
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
retries idempotent. Store received time server-side, validate transitions, keep
bounded error codes rather than arbitrary logs, and retain the last unsent
event in NVS so deep sleep or an outage does not erase the outcome. Never treat
`staged` or a version header as success; only a validated image can emit
`succeeded`.

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
- Back off failed downloads across wakes. Never remain awake in an unbounded
  retry loop and never perform a panel refresh merely to report OTA progress.

## Staged rollout and recovery

Use deterministic cohorts derived from device ID plus rollout ID. A suggested
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
   and revocation now have deterministic software tests. CA validation,
   production Web Serial transport, and the repeatable physical E1001/E1002
   interruption/recovery matrix remain. E1004 stays locked.
4. **Browser first install:** add a pinned flashing implementation only after
   browser-side signature verification and milestone 3 pass. Flash exact
   preserve-config artifacts, verify ROM-loader output and rebooted identity,
   and keep a command-line rescue flow. The server and client write gates may
   then be changed through a separately reviewed release.
5. **A/B OTA canary:** define and migrate to `ab-v1`, implement signed manifest
   verification, CA-validated inactive-slot writes, pending validation,
   rollback, battery gates, and a one-device rollout.
6. **Managed rollout:** add cohort promotion, pause/revoke, key rotation,
   charging notices, dashboards, and recovery drills before wider release.

No milestone should be promoted merely because it builds. Its exit gate is a
repeatable artifact, device evidence for each eligible model, server-observed
acknowledgements, and a demonstrated recovery path.
