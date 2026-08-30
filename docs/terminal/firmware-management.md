# Terminal firmware management roadmap

This document defines the safe path from the current USB-flashed prototype to
browser installation and managed over-the-air (OTA) releases. It is a roadmap,
not a description of capabilities already available in production. The image
wire contract remains in [`server-protocol.md`](server-protocol.md), and panel
formats remain in [`firmware-variants.md`](firmware-variants.md).

Baseline inspected on 2026-08-30:

- this Email checkout and its current terminal protocol documents;
- the sibling `reTerminalColor` checkout at `21fbe86`, including its
  uncommitted working tree.

## Status today

| Capability | Implemented today | Important limit |
| --- | --- | --- |
| USB build and flash | PlatformIO environments exist for E1001, E1002, and E1004. | Command-line workflow only; there is no published, immutable release bundle or browser installer. |
| Runtime configuration | Firmware reads Wi-Fi and the schedule URL from `/config.json` on LittleFS and falls back to compile-time values. | Provisioning rewrites a filesystem image over USB. `LittleFS.begin(true)` may format on mount failure. The `board_build.filesystem = littlefs` correction is only in the dirty firmware working tree, not `origin/main`. |
| Application partitions | E1001/E1002 use Arduino's `huge_app.csv`; E1004 has a custom table with one `ota_0` app partition. All builds declare 32 MB flash. | There is no second application slot, so safe A/B OTA and automatic rollback are impossible. Most flash capacity is currently unused. |
| Device check-in | The firmware reports model-specific user agent, firmware version, MAC, wake reason, boot count, uptime, battery millivolts/percent, RSSI, free PSRAM, and image ETag. | MAC and the shared terminal URL are routing data, not device authentication. Battery percent is a rough linear LiPo estimate and no charging/power-source state is reported. |
| Update transport | None. Firmware fetches only schedule JSON and BMP images. | No updater, release manifest, signature verification, acknowledgement, rollout, or recovery state exists. |
| TLS | HTTPS requests use `WiFiClientSecure`. | `configure_secure_client()` calls `setInsecure()`, and the firmware can also follow plain HTTP. The current protocol text incorrectly claims CA-bundle validation. Production update work must remove this mismatch before OTA is enabled. |
| E1004 | The committed tree contains a full-refresh dual-controller implementation. | Repository prose still calls the driver a stub, partial refresh explicitly falls back to a full refresh, and there is no recorded hardware qualification. Treat E1004 as experimental and OTA-ineligible until code, docs, and hardware results agree. |

The firmware checkout is not a release baseline: `main` and `origin/main` both
point to the single initial-import commit, while 13 tracked files are modified.
Those edits may be useful work, but they must be reviewed, tested, committed,
and built by CI before any artifact is called installable or eligible for OTA.

There are also protocol details to reconcile before firmware management shares
the schedule path:

- Firmware does not retain the last schedule body, so a `304` from
  `schedule.json` currently becomes an error/retry. The server should return a
  complete `200` schedule until the firmware can safely replay a cached one.
- A schedule ETag must change when a firmware offer or device action changes,
  not only when image pixels change. Otherwise a valid OTA offer can be hidden
  behind `304 Not Modified`.
- Relative image-URL support exists only in the dirty firmware worktree. A
  release must not depend on it until that work is integrated.

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

### Provisioning without uploading Wi-Fi credentials

After the generic image boots, the installer reopens the serial port and sends
a versioned provisioning message directly to firmware. The message contains
the SSID, password, schedule URL, declared model/hardware revision, and a
short-lived enrollment token. Firmware validates the message, writes its local
configuration, reads it back, and returns a redacted acknowledgement.

The installer must use no third-party scripts, analytics, session replay, or
remote error capture. Credential values live only in page memory, are sent only
through Web Serial, are never placed in `localStorage`/IndexedDB or the URL, and
are cleared after acknowledgement or cancellation. The server may mint the
one-time enrollment token, but it never receives the SSID or password.

On the first CA-validated check-in, the device exchanges the one-time token for
a per-device credential. Store only a verifier/hash server-side, send the
credential in an authorization header rather than a query string, and redact it
from all logs. The existing terminal code remains a user-facing route secret;
it is not sufficient authentication for OTA acknowledgements.

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

1. **Baseline and release discipline:** reconcile the dirty firmware checkout,
   stale protocol/TLS/E1004 claims, pin the toolchain, build every model in CI,
   and publish checksummed immutable artifacts. No OTA yet.
2. **Secure browser first install:** ship Web Serial flashing, local serial
   provisioning, exact-variant gates, and a tested rescue flow. Install `ab-v1`
   over USB and report its verified version/layout.
3. **Device trust and transport:** remove `setInsecure()`, add trusted time and
   CA validation, enroll per-device credentials, and add normalized firmware
   telemetry/ack events.
4. **A/B OTA canary:** implement signed manifest verification, inactive-slot
   writes, pending validation, rollback, battery gates, and one-device rollout.
5. **Managed rollout:** add cohort promotion, pause/revoke, key rotation,
   charging notices, dashboards, and recovery drills before wider release.

No milestone should be promoted merely because it builds. Its exit gate is a
repeatable artifact, device evidence for each eligible model, server-observed
acknowledgements, and a demonstrated recovery path.
