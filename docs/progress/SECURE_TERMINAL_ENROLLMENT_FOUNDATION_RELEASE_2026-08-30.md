# Secure Terminal Enrollment Foundation Release — 2026-08-30

## Outcome

The Email application now has the server-side foundation for confidential,
owner-scoped terminal enrollment without enabling any browser or device write
path. Production remains deliberately locked: no online enrollment key,
qualified release/model pair, positive signed-catalog generation, serial-port
request, Wi-Fi submission, configuration write, firmware flash, or erase path
is present or enabled.

The deployed application/runtime commit is
`8ff01848a2be2818dfd9eb88b84be9aab4befb0a`. Alembic advanced one additive
revision from `e2f3a4b5c6d7` to `f3a4b5c6d7e8 (head)`. The private firmware
baseline remains `fd8671bd9a3641ecf9af37491bb8a00607dec4d6`
(`0.2.0-candidate.3`); its generic artifacts remain unkeyed,
enrollment-disabled, unsigned for installation, and unqualified on physical
hardware.

## Released Contract

- Signed schema-2 firmware catalogs can bind RET1 protocol claims, exact
  release/model identity, partition layout, hardware revisions, and a positive
  catalog generation. Production has no approved catalog or trust material.
- RET1 intent, ticket, completion, status, activation, rollback, and revocation
  are owner-scoped. Tickets bind the complete physical-cable transcript and use
  a dedicated online P-256 identity that is independent of offline firmware
  release signing.
- Per-device terminal credentials and configuration verifiers are stored only
  as SHA-256 digests. Activation occurs on the first correctly scoped device
  check-in, not on the browser's advisory completion message.
- A pending first enrollment retains same-owner legacy continuity. Enrolled or
  revoked devices cannot fall back to the shared legacy route. The immediately
  previous generation has a bounded 24-hour rollback window; older generations
  are revoked.
- Owner revocation closes pending, active, and rollback credentials. A revoked
  device can begin again only through a newly qualified physical enrollment.
- Device serialization uses canonical row locks plus a PostgreSQL transaction
  advisory lock for a not-yet-present MAC. A partial unique index prevents two
  secure device rows from claiming the same MAC.
- Caddy skips `/terminal/device/*` request logging, while the outer ASGI scope
  redacts that path before normal routing and exception handling. The scoped
  device secret is therefore excluded from routine access and error logs.

## Verification

- `make check` passed with 548 backend tests, 33 intentionally skipped
  PostgreSQL/external tests, 274 frontend tests, and a 518-module local
  production build.
- A disposable PostgreSQL 17 database passed an actual
  `f3a4b5c6d7e8 → e2f3a4b5c6d7 → f3a4b5c6d7e8` migration cycle and all 12
  focused enrollment concurrency/lifecycle tests. The contention suite was
  repeated five times independently and once in the final root gate.
- Focused tests force absent-device advisory-lock contention, identical intent
  replay, cross-owner denial, activation against expiry/revocation, rollback
  inside and outside grace, generation gaps, and revoked-device reenrollment.
- An independent security review found no remaining P0/P1 issue after exact
  transcript, ownership, locking, activation, rollback, revocation, and path
  redaction fixes. The final P2 PostgreSQL regression gaps were then closed.
- The exact local Caddy configuration validated with production Caddy 2.10.2.
  Diff and secret scans were clean; only deliberate fake test values were
  present.

## Production Actions

- Captured and validated
  `/var/backups/mailapp/maildb-pre-terminal-enrollment-20260830T2011Z.dump`:
  1,383,638,606 bytes, mode `0600`, owner `postgres:postgres`, and 299 readable
  archive entries.
- Fast-forwarded clean production from
  `931cd50b042f008125e2b1eafb7f65ca325b2305` to application commit
  `8ff01848a2be2818dfd9eb88b84be9aab4befb0a`, then advanced Alembic to
  `f3a4b5c6d7e8 (head)`.
- Restarted only `mailapp`. The retired API process exceeded its 90-second
  graceful-stop window and systemd killed that old process; its replacement
  started successfully with zero automatic restarts and no warning-or-higher
  entries after its start.
- Installed the existing locked frontend dependency set and built 520 modules
  on production. Validated and reloaded the tracked Caddy configuration without
  restarting Caddy.
- Verified all seven checked services active, public health `ok`, clean exact
  Git, the new frontend asset returning HTTP 200, anonymous enrollment
  capabilities returning 401, and Alembic at the exact new head.

## Read-Only Browser and Data QA

An authenticated production session loaded Settings → At a Glance after a
normal post-deployment chunk refresh. The firmware and secure-enrollment panels
both reported `Locked`; the catalog truthfully reported unavailable because no
approved production catalog is staged. The page exposed no serial, Wi-Fi,
configuration-write, download, flash, or erase control. All four existing
terminals remained labeled as legacy, with no secure-device revocation action.

After browser QA, `terminal_device_credentials` and
`terminal_enrollment_attempts` remained empty, all terminal rows remained
legacy, and the secure-MAC unique index remained present.

## Rollback and Next Boundary

The migration is additive and the new production tables are empty. If runtime
rollback becomes necessary, revert the application to the prior known-good
release and downgrade Alembic to `e2f3a4b5c6d7`; the validated pre-migration
backup is the disaster-recovery boundary. Do not enable RET1 or stage trust/key
material as part of rollback testing.

The next application milestone is a migration-free, first-class At a Glance
route after the coordinated Durable Replies release establishes the next
shared-shell baseline. Browser transport remains blocked until physical E1001
and E1002 enrollment, interruption, recovery, rollback, revocation, TLS, and
preserve-config HIL passes. Signed A/B OTA remains a later milestone.
