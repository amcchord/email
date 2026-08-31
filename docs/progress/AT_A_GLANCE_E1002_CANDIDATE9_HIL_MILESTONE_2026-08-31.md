# At a Glance E1002 candidate.9 physical milestone — 2026-08-31

## Outcome

One user-authorized USB-C-attached SeeedStudio E1002 now runs At a Glance
firmware `0.2.0-candidate.9`, checks in through the existing owner-scoped legacy
schedule route, renders the 800×480 Spectra6 view, reports battery/runtime
telemetry, and returns to timed deep sleep.

The physical run found and corrected a release-blocking flash-mode mismatch.
Candidate.8's inherited QIO boot header watchdog-looped immediately on this
unit. DIO recovered the same exact four preserve-config segment layout.
Candidate.9 makes DIO explicit in the build and signed manifest and rejects
malformed or non-DIO bootloader headers before packaging.

Exact private firmware `main` and feature branch:
`52ba6c58ca7f17741d0d74c225f8d942b6119241`.

Exact successful firmware workflow: `33412815120`.

The Email application runtime remains
`fcbea4afccfa2226b5519c6c2f278960bee8b29c`, with production Alembic exactly
`b1c2d3e4f5a6 (head)`. The documentation work begins from exact GitHub and
production Attachments closeout `636218605d5cf6e4db1f41f2a395ebac62bc4742`
and changes Email documentation only.

## Physical Boundary

- Device: SeeedStudio reTerminal E1002, ESP32-S3 revision 0.2, 8 MB PSRAM,
  32 MB flash.
- Original state: stock SenseCraft application and a factory partition layout
  incompatible with the At a Glance `ab-v1` release layout.
- Installation: explicit command-line ROM/esptool four-segment write; no
  erase-all operation and no browser transport enablement.
- Configuration: existing supported LittleFS file configuration. Network and
  schedule credentials were used only to configure the attached device and
  were excluded from Git, logs retained as evidence, and progress documents.
- Recovery boundary: the complete factory image was not captured. Restoring
  stock firmware requires Seeed's factory image; the temporary partition-table
  capture was removed after candidate.9 succeeded.

## Failure and Correction

1. Candidate.8 was built from exact private firmware `main` and written with
   the board default QIO boot header.
2. The E1002 entered an immediate ROM watchdog reset loop before application
   startup.
3. Rewriting the same bootloader, partition table, OTA data, and application
   segment set under DIO restored normal boot.
4. The source fix advanced the version to candidate.9, pinned
   `board_build.flash_mode = dio`, added `flash_constraints.mode = dio` to the
   release manifest, and made packaging validate the ESP bootloader header.
5. Candidate.9 was rebuilt cleanly, flashed from the exact committed SHA, and
   booted with ROM `mode:DIO`.

Candidate.8 remains immutable. No previously published candidate byte was
replaced or relabeled.

## Device Evidence

The candidate.9 boot and live service cycle reported:

- exact firmware build ID
  `52ba6c58ca7f17741d0d74c225f8d942b6119241`;
- model E1002, `partition_layout=ab-v1`, `running_partition=ota_0`,
  `boot_state=stable`, and valid partition identity;
- retained file configuration and bounded reset recovery window;
- cached-AP Wi-Fi connection at approximately -27 dBm;
- fresh UTC synchronization and CA/hostname-validated HTTPS;
- a valid scoped schedule response and 192,118-byte E1002 image fetch;
- changed-image verification followed by a 128×85 partial refresh covering
  about 1% of the panel; and
- 90% measured battery followed by a 264-second timer sleep.

The signed-in production At a Glance surface showed Terminal 0a80 using the
`spectra6_800x480` profile with a fresh check-in, candidate.9, boot 9, strong
signal, and 90% battery. No mail or calendar content was opened or mutated.

## Verification

- Fifteen focused firmware release-tool tests passed, including manifest DIO
  declaration and malformed/QIO bootloader rejection.
- A clean exact E1002 candidate.9 build passed; the bootloader header declared
  DIO and the application contained the exact candidate.9 version/build ID.
- Physical flash readback hashes passed before reset.
- GitHub Actions run `33412815120` passed release tooling, keyed RET1 and OTA1
  builds, every model, deterministic rebuild/reproducibility, release manifest
  verification, and immutable candidate upload.
- The firmware worktree was clean after credential-bearing local configuration,
  filesystem image, and temporary recovery artifacts were removed.

## Gates That Remain Closed

This is one bounded E1002 installation/render/sleep result. It does not prove
the complete revision-bound schema-2 HIL record and does not authorize a signed
production release. In particular, evidence is still required for:

- a physical E1001;
- interrupted flash and encrypted configuration writes;
- RET1 enrollment, activation, revocation, and lost-result recovery;
- three-slot configuration interruption and rollback continuity;
- A/B inactive-slot writes, pending-image validation, power interruption, and
  automatic rollback; and
- repeatable ROM rescue for every qualified model/revision.

Production therefore retains no trusted release key, signed positive-generation
catalog, online enrollment key, qualified model/revision tuple, nonzero OTA
rollout, or device update offer. Browser enrollment and OTA transports remain
independently locked.

## Rollback and Next Action

Firmware source rollback is a Git revert that creates a new candidate; do not
move candidate.8 bytes or labels. Device recovery uses the ESP32-S3 ROM
bootloader and the exact candidate.9 DIO four-segment bundle. Returning to
SenseCraft requires the vendor factory image because no complete stock image
was retained.

Next, keep this candidate.9 E1002 run as regression evidence and execute the
remaining HIL cases on dedicated E1001/E1002 hardware before any offline signing
ceremony, allowlist update, enrollment enablement, or OTA rollout change.
