# At a Glance Browser Transport Release — 2026-08-30

## Outcome

At a Glance now contains the real, pinned browser transport needed to install a
qualified E1001/E1002 release, plus owner-facing OTA inspection and rescue
controls and exact fail-closed design registries. The implementation is deployed
but intentionally unusable for a production device write: every trust,
enrollment, printed-revision, physical-HIL, browser, and OTA rollout gate remains
independent and closed.

This milestone changes the product from a transport mock/foundation into the
exact software that can be physically qualified. It does not claim that a
device has been qualified, signed, enrolled, flashed, or offered an update.

## Exact source boundaries

- Base Focused/Split Inbox closeout:
  `e2fdffd562f125c341703042620e09e9b96c8aa5`
- Owner OTA controls source commit:
  `118a1b8bd64341b166213d635508150ebdcfff8f`
- Exact design registry source commit:
  `cddbb72338fbd6a3866bb83c98dcbab52e860a0b`
- Browser transport source commit:
  `d06d37d447aed23b0318511407e92b627cc14714`
- Integrated Email application/runtime:
  `fdc766c234c02e5cd7d59df453691e8bc39eadbc`
- Private firmware candidate.7 `main`:
  `ea3547b8bdb96cd27a4b14f4ed0ce662445944b4`
- Exact candidate.7 Actions run: `33344430605`
- Private offline promotion-tool branch:
  `aadac9d6dbb0afc0e115db3528251691a93c6fc5`
- Alembic remains `c6d7e8f9a0b1`; this application milestone is
  migration-free.

## Browser install transport

- The application pins the official unscoped `esptool-js@0.6.1` package.
- One explicit user gesture selects one Web Serial port. One origin-wide
  exclusive Web Lock owns that port across ROM probing, write/readback, reset,
  and application verification.
- The adapter requires ESP32-S3 identity, 32 MB flash, and the expected MAC. It
  writes only the four signed preserve-config segments from the qualified
  manifest, never exposes a whole-chip erase, and reads every written byte back
  for comparison.
- Success requires the rebooted device on the same port to report exact RET1
  status-v2 model, version, partition layout, and source-build identity.
  Disconnects, cancellation after a write begins, mismatched identity, or
  failed readback become explicit recovery-required states rather than partial
  success.
- The transport module is loaded only after the existing server and browser
  eligibility computation enables Connect. Production's empty trust/catalog/
  HIL state keeps that action unreachable, so deployment itself cannot request
  a port or fetch firmware bytes.

## Owner controls

- Terminal Settings exposes the effective OTA capability blockers and exact
  per-device attempt history/detail.
- An owner may explicitly confirm or clear the device's printed hardware
  revision and may cancel only an `offered` attempt whose last sequence is zero.
- The surface cannot create an OTA offer, change server enablement or rollout,
  stage a release, download device-authenticated artifacts, or access a serial
  port.

## Extensible design contract

- Every catalog-declared `(content_type, design)` now requires an exact Pillow
  renderer and palette registration, with import-time equality checks against
  device and browser renderers.
- Unknown content, designs, palettes, and incomplete future registrations fail
  closed. Existing Home Editorial/Swiss and Day Ahead Editorial output remains
  byte-for-byte pinned by exact pixel hashes.

## Offline promotion path

The private promotion tool consumes immutable candidate bytes only after
complete exact-revision E1001 and E1002 HIL records and status evidence. It
emits the application gateway's exact schema-2 signed manifest and one-release
schema-1 catalog, enforces monotonic generation, preserves the candidate bytes,
and keeps E1004 plus all OTA eligibility false. It accepts protected private-key
inputs but no real key or HIL evidence was used, and it was deliberately not
merged into firmware `main` so candidate.7's source/build identity stayed exact.

## Validation

- Integrated focused backend gate: 101 passed.
- Full frontend suite: 412 passed.
- Dependency audit: zero vulnerabilities.
- Production frontend build: 587 modules transformed.
- Isolated design-registry gate: 133 passed.
- Offline promotion-tool gate: 20 passed.
- `git diff --check` passed before deployment.

No E1001/E1002 was attached. No browser port chooser, ROM write, RET1
provisioning, real signing ceremony, catalog promotion, enrollment, OTA offer,
provider operation, or real mail/calendar mutation was performed.

## Production evidence

- Production fast-forwarded cleanly from `e2fdffd` to exact runtime `fdc766c`,
  installed the pinned frontend dependency, and built 587 modules.
- Only `mailapp` was restarted. The retired process reached the host's known
  graceful-drain timeout; replacement PID 2133109 became active at
  2026-08-31 01:14:33 UTC with `NRestarts=0` and no warning-or-higher entries
  after 01:14:34 UTC.
- All seven checked services are active and public health is `ok`. Production
  Git is exact and clean and Alembic remains `c6d7e8f9a0b1`.
- Effective lock state is browser flashing false, zero trusted release keys,
  OTA disabled, rollout zero, and zero OTA attempt/event rows. Anonymous
  firmware catalog, OTA capabilities, and enrollment capabilities remain 401.
- The built production bundle contains the new owner-control and transport
  surfaces, while the effective lock state keeps all device access unreachable.

No migration, database backup, worker restart, Caddy change, terminal mutation,
or production mail/calendar operation was part of this deployment.

## Rollback and next gate

The application rollback boundary is the reviewed base `e2fdffd`; the additive
`c6` schema remains compatible and unused by this migration-free UI/transport
slice. The safer operational rollback is already active: leave the independent
trust, catalog, browser-flash, enrollment, HIL, and OTA gates closed.

The next milestone is physical evidence, not more simulated eligibility:

1. attach dedicated E1001 and E1002 devices and record exact printed revisions;
2. execute the browser ROM-write/readback/reset, RET1, A/B migration, power-loss,
   disconnect, rollback, and command-line rescue matrix;
3. collect complete signed HIL records for both exact revisions;
4. run the protected offline promotion ceremony over the unchanged candidate.7
   bytes; and
5. separately review first browser enrollment and a one-device OTA canary.

E1004 remains ineligible.
