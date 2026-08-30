# Terminal Firmware Gateway Release — 2026-08-30

## Outcome

At a Glance now has an authenticated firmware release gateway and a visible
browser-installer status surface. This is a safety foundation, not a browser
flasher: production code can inspect a rigorously approved catalog but cannot
request a serial port, download a firmware artifact, erase a terminal, or write
flash.

## Release identities

- Email base: `6d8e94584f21a6090b16cc697bd4579c3a3c0400`
- Email gateway application commit: `0fe2ef7`
- Email reviewed/deployed release commit: `69a5622659d39709a07334b04aa8f517a8b12728`
- Firmware `main`: `1b5364e5d4b48666b3ecfd0cf8ba31ab7f4bd5c4`
- Firmware reproducibility run: GitHub Actions `33322241770`
- Production Alembic before and after: `d1e2f3a4b5c6`

The final GitHub/production docs-closeout SHA is recorded in the coordinating
task handoff after this release record is committed.

## Implemented boundary

- Four cookie-authenticated routes expose a verified catalog, exact manifest,
  detached signature, and per-model preserve-config artifacts.
- SlowAPI limits catalog/metadata reads to 6/minute and artifact reads to
  12/minute per client. Synchronous hashing/partition work runs off the event
  loop.
- A signed `catalog.json` is limited to one approved content-addressed release
  and a positive generation. Production can pin the minimum allowed generation
  independently of the staged bytes.
- Every request revalidates the catalog, detached manifest signature, closed
  file set, hashes, lengths, build provenance, per-model partition CSV and
  binary table, factory composition, flash offsets, NVS/LittleFS preservation,
  panel/layout identity, hardware revision evidence, and E1004 lockout.
- Descriptor-relative, no-follow reads reject symlinks, path traversal,
  non-regular files, FIFOs, unsafe directory swaps, growth, truncation, and
  unbounded files. Failures become non-disclosing 503 responses.
- Catalog metadata gets a second strict browser audit. The shipped interface
  has three fixed-false safety gates and no flashing dependency or operation.
- The tracked Caddy policy permits Web Serial for this origin without granting
  camera, microphone, or geolocation access.

## Fail-closed production configuration

The release deploys only defaults:

```text
trusted signing keys = none
approved catalog = none
minimum catalog generation = 0
browser flash enabled = false
```

No firmware bytes, signing keys, approval catalog, database row, or migration
are added. An authenticated catalog request therefore returns a safe
unavailable state until a separate operator-reviewed staging event. The Admin
surface remains locked even if browser primitives exist.

## Verification

- `make check`: 459 backend passed, 13 opt-in PostgreSQL skipped; 221 frontend
  passed; 512 frontend modules built.
- Focused gateway/service/router tests: 37 passed.
- Python compilation and `git diff --check`: passed.
- Final adversarial review: no P0-P2 finding.
- Exact firmware main artifact: strict manifest verification and all
  `SHA256SUMS` checks passed; artifacts remained explicitly unsigned,
  single-slot, non-OTA, and browser-unqualified.
- No local Caddy binary was installed. Production syntax validation uses the
  exact tracked `/opt/mail/Caddyfile` before reload.

## Production verification

- Clean production fast-forwarded from `6d8e945` to exact reviewed release
  `69a5622`. The tracked Caddyfile validated before the frontend build,
  `mailapp` restart, and Caddy reload.
- The unchanged frontend lock installed with zero audit vulnerabilities and
  built 514 production modules. The exact new entry asset returned 200.
- All seven services were active, public health returned `ok`, and mailapp and
  Caddy had zero warning-or-higher log entries or automatic restarts after the
  release.
- The unauthenticated catalog returned 401. Response policy included
  `serial=(self)` while camera, microphone, and geolocation remained disabled.
- Signed-in Admin showed the installer as locked, detected HTTPS/Web
  Serial/Web Locks support, and handled the absent trust/catalog as safe
  unavailable state. The installer section had no buttons and listed each
  unmet safety gate. Browser logs contained no warning/error and no serial
  permission prompt appeared.
- Alembic remained exactly `d1e2f3a4b5c6`. No database, mail, calendar,
  terminal, artifact, catalog, signing-key, or configuration mutation occurred.

## Remaining milestones

1. Finish and review confidential `@RET1` serial enrollment, one-time signed
   tickets, per-device credentials, CA validation, and two-slot atomic config.
2. Run the physical E1001/E1002 interruption, preservation, and ROM-recovery
   matrix. Keep E1004 blocked.
3. Add the browser write implementation only after signature verification,
   provisioning, and HIL gates independently pass.
4. Design and qualify A/B partitions, signed OTA, pending-image validation,
   rollback, battery gates, and canary rollout.
