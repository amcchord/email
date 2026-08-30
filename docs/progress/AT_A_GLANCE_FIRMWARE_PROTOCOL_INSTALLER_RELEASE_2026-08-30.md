# At a Glance firmware protocol and installer foundation — 2026-08-30

## Outcome

At a Glance now has an exact browser-install package/recovery workflow and a
cross-language OTA1 protocol foundation, while every real device-write path
remains absent or source-hard-disabled. Candidate.6 also makes the physical
E1001/E1002 qualification matrix executable and recoverable without trusting an
enrollment secret.

Exact deployed application/runtime commit:
`84a854a5527c342b85bb2884ef43b89fea95a954`.

Exact private firmware `main` commit:
`5db28243f8dc56309492ae926c0b5186a5fffeb7`
(`0.2.0-candidate.6`). Exact-SHA release run: `33341323506`; identical
main-ref provenance run: `33342394221`.

## Delivered firmware boundary

- A reset opens an eight-second status-only RET1 window even when enrollment
  trust or storage is unavailable. Only the exact bounded status-request frame
  is accepted; automatic sightings, explicit replies, total frames, malformed
  input, and parser work are bounded.
- A strict OTA1 parser validates the exact signed-offer and device-event shapes,
  canonical replay identity, transitions, and sequence gaps. The schedule may
  classify an offer but cannot act on it; no HTTP client, writer, NVS state,
  event sender, or update route exists.
- The HIL tool selects only E1001/E1002 and exact `ab-v1` preserve-config
  segments, verifies the signed candidate bundle, binds a plan ID to source/
  model/revision, validates noisy RET1 v2 recovery identity, and requires all
  18 physical cases. Every pass cites a bounded non-symlink evidence file under
  the selected evidence root with a verified digest.
- E1004 remains single-slot and ineligible. Generic artifacts remain unkeyed,
  enrollment-disabled, OTA-disabled, and physically unqualified.

## Delivered application boundary

- Pure OTA1 offer/event codecs enforce the same exact field, URL scope, replay,
  and transition contract as firmware. They have no router, model, persistence,
  worker, scheduler, or device transport.
- The browser compiles only schema-2 E1001/E1002 exact-revision plans with the
  four approved `ab-v1` offsets. Every artifact must have exact octet-stream
  headers, length, preservation claims, and SHA-256 before a future device is
  connected.
- Prepared bytes are held in memory and re-hashed immediately before the
  injected workflow could probe or write a device. The workflow validates ROM
  chip, minimum flash size, factory MAC continuity, exact segment write/readback,
  reset, and bounded RET1 runtime identity.
- The operator surface distinguishes a safe pre-write cancel from
  recovery-required after write entry, provides an exact CLI/ROM recovery path,
  and aborts/closes all injected transports on disconnect, failure, or teardown.
- Production transport remains a literal false source constant. The shipped UI
  cannot call `requestPort`, Web Serial, esptool, erase, or flash code.

## Locked boundary

Software success is not physical qualification. Production has no browser
release key, positive qualified catalog generation, E1001/E1002 revision
allowlist, online enrollment key, device-authenticated OTA endpoints, artifact
delivery route, durable OTA event ledger, cohort, update scheduler, or write
transport. No terminal received candidate.6 during this release.

## Verification

- Consolidated application validation passed 261 terminal backend tests with 12
  expected opt-in PostgreSQL skips, 59 terminal frontend tests, and a 541-module
  local production build. Diff and write-surface checks passed.
- Firmware validation passed 29 tool tests, RET1/enrollment and OTA1 host tests,
  E1001/E1002/E1004 builds, and two clean reproducible all-model release builds.
  The exact manifest SHA-256 is
  `fb1e7fb35a077356a6e36ed3a790e60ace2d5d5573ae3d23822d697e7b385ef7`.
- Exact-SHA Actions run `33341323506` passed both keyed protocol compiles, the
  full model matrix, byte-for-byte reproducibility, manifest verification, and
  immutable bundle publication before the same SHA was promoted to `main`.

## Production evidence

- Production advanced cleanly from Labels docs closeout
  `8d87efdcd0dd5f11c4c93e4d1652c246ca1d673b` to exact runtime
  `84a854a5527c342b85bb2884ef43b89fea95a954` and built 543 frontend modules.
- The release is migration- and dependency-free. Alembic remains exactly
  `b5c6d7e8f9a0 (head)`; no database backup was required because no database or
  persistent terminal state was touched.
- No service restart was required. All seven services remained active, public
  health returned `ok`, production Git was exact/clean, and warning-or-higher
  logs were empty after deployment.
- Authenticated read-only browser QA loaded first-class At a Glance and its
  Terminal firmware section. `Transport locked` was visible; Verify package and
  Connect & install were disabled; no console warning/error, artifact download,
  browser permission prompt, mail action, or terminal mutation occurred.

## Rollback

Revert the two application terminal commits to Labels docs closeout
`8d87efdcd0dd5f11c4c93e4d1652c246ca1d673b` and rebuild the static frontend.
No service restart or schema downgrade is required. Reverting private firmware
`main` to candidate.5 changes only future release source because candidate.6 was
not installed on hardware. Keep every enrollment/browser/OTA gate false during
rollback.

## Remaining work

1. Execute the complete candidate.6 18-case record on dedicated E1001 and E1002
   devices, including interruption, preserve-config, power loss, rollback, ROM
   recovery, reset RET1 status, and CLI fallback evidence.
2. Only after exact release/model/revision qualification, pin the reviewed
   browser public key and import a concrete Web Serial/esptool adapter behind
   all existing gates.
3. Then allocate a terminal OTA ledger as a child of current head
   `b5c6d7e8f9a0`, add device-authenticated offer/artifact/event transport, and
   qualify power/cohort/rescue behavior before enabling any offer.
