# At a Glance OTA Control Plane Release — 2026-08-30

## Outcome

At a Glance now has a complete, default-locked software path for managed
E1001/E1002 application updates: an owner-requested server offer, exact
credential-scoped artifacts, an append-only PostgreSQL lifecycle ledger, and a
firmware HTTPS/NVS coordinator that writes only a verified inactive A/B slot.

This release does **not** authorize a production device write. Generic firmware
remains writer-disabled, transport-disabled, and unkeyed. Production server
enablement is false, the exact HIL map is empty, rollout is 0%, no eligible OTA
descriptor is installed, and no device hardware revision is confirmed for an
update. Physical E1001/E1002 migration, interruption, rollback, recovery, and
USB-rescue evidence remains the release gate for a real canary.

## Exact source boundaries

- Email application/runtime: `9253eb42d884868a18f280bbf4ab1aae6b474b5e`
- Email base and Conversation-first Inbox docs closeout:
  `075a4756771530511dfdb1fbca8aa6b6ff6ddf61`
- Alembic: `c6d7e8f9a0b1`, direct child of `b5c6d7e8f9a0`
- Firmware coordinator implementation:
  `949bc87036660e67af2323f34a13cfb6976603c4`
- Firmware candidate.7 branch tip:
  `ea3547b8bdb96cd27a4b14f4ed0ce662445944b4`

## Server control plane

- `TerminalDevice` stores an explicitly owner-confirmed printed hardware
  revision plus one all-or-nothing active-credential OTA telemetry snapshot:
  firmware version, source build, running slot, boot count, measured battery,
  optional direct-power truth, and observation time.
- One immutable `TerminalOtaAttempt` snapshots the exact owner/device/active
  credential, idempotent client request, signed descriptor and parent bundle,
  signing key, catalog generation, model/revision/layout, target build/hash,
  source build/slot/boot, measured reserve, cohort, rollout, and expiry.
- A partial unique index permits only one active attempt per device. Owner
  request replay returns the original attempt even if policy or release
  availability later changes. Only an unstarted offer may be cancelled.
- `TerminalOtaEvent` is append-only through the service boundary with global
  event identity and per-attempt sequence uniqueness. First acceptance and
  exact replay are distinct (`201` and `200`); conflicting payload, binding,
  transition, source/target build, slot, or boot evidence fails closed.
- Event insertion and attempt projection commit together. Sequence gaps are
  retained explicitly and cannot count as clean future promotion evidence.
- Active enrolled credentials alone can receive an optional schedule offer and
  the exact manifest, signature, application, and event routes. Candidate,
  rollback, revoked, foreign, wrong-MAC, wrong-release, and stale credentials
  are non-disclosing failures.
- The schedule ETag includes offer identity, so a previously unchanged image
  cannot hide a new or withdrawn firmware offer behind `304 Not Modified`.
- Artifact evidence is re-read from bounded, regular, non-symlink files and
  re-verified against the signed catalog, parent bundle, OTA descriptor, and
  exact application bytes on every delivery.

## Firmware transport

- `RETERMINAL_OTA_TRANSPORT_ENABLED` is a second compile-time gate beside the
  existing signed writer. All generic E1001/E1002/E1004 environments set both
  to zero and contain no public update key.
- A keyed synthetic E1002 build accepts only the exact active enrollment URL
  scope and strict OTA1 offer. It uses the existing bounded fresh-time and
  public-CA policy, disables redirects/downgrade, and performs one bounded GET
  each for manifest, raw 64-byte signature, and application.
- Descriptor signature, model, `ab-v1`, version, content-addressed release ID,
  application length, and streaming SHA-256 must all agree before finalization
  and boot selection.
- Power is sampled before descriptor verification and again at the erase/write
  boundary. The writer requires valid, bounded, fresh measurements of at least
  4000 mV and 80%. Forecasts and `possible_charging` never enter admission.
- One CRC-protected NVS record retains exact attempt identity, recovery phase,
  monotonic state/sequence, and one canonical unsent event. An event is durable
  before POST; exact retry is idempotent across reset/deep sleep.
- Artifact failures terminally fail the attempt. Event delivery is bounded to
  three posts per wake with a 300-second retry sleep; there is no same-event
  awake loop. A permanently rejected stale pre-write offer is safely cleared,
  while staged, boot, rollback, recovery, and terminal evidence is retained.
- Booted images reconcile durable state before the existing local pending-image
  test. Only a successfully marked-valid target can report `succeeded`; source
  rollback and failed rollback report `rolled_back` or `recovery_required` with
  exact runtime identity.

## Validation

- Focused server gate before the no-overlap Inbox rebase: 158 passed with 16
  expected skips.
- Fresh disposable PostgreSQL OTA gate: 4 passed, including concurrent
  idempotent create/replay, immutable event projection, active-credential
  enforcement, expiry persistence, and revision freezing.
- Actual migration round-trip passed: `b5 → c6 → b5 → c6`.
- Exact post-rebase terminal and migration-head gate: 273 passed with 16
  expected hardware/disposable-database skips; `git diff --check` passed.
- Firmware host safety suite passed scope/URL/model binding, CRC corruption,
  monotonic/gap transitions, stale-offer rejection, pending-boot ordering, and
  conservative battery reserve.
- Generic E1001, E1002, and E1004 builds and the keyed E1002 coordinator build
  passed at implementation commit `949bc87`. The candidate.7 exact-SHA
  reproducibility run is the final GitHub promotion gate.

## Production deployment

- A validated pre-migration backup was created at
  `/var/backups/mailapp/maildb-pre-terminal-ota-20260831T0019Z.dump`: 1,383,737,691
  bytes, `postgres:postgres`, mode `0600`, SHA-256
  `5d05849d9197b3a2ad513cee0c4263b7efe9869bc8e20dc430f0ffb83a13b80e`.
- Production fast-forwarded cleanly from `075a475` to exact runtime `9253eb4`
  and applied only `b5c6d7e8f9a0 → c6d7e8f9a0b1`.
- Only `mailapp` was replaced. The retired process again exceeded the host's
  graceful-drain timeout and was killed; replacement MainPID `2130573` became
  active at 2026-08-31 00:22:23 UTC with `NRestarts=0` and no warning-or-higher
  entries after 00:22:24 UTC.
- All seven checked services are active and public health is `ok`. Anonymous
  capabilities and attempt reads return `401`.
- Aggregate postflight is `terminal_ota_attempts=0` and
  `terminal_ota_events=0`. Effective production settings are
  `enabled=false`, `rollout_percentage=0`, zero qualified releases, and minimum
  catalog generation 0.
- No device schedule offer, artifact download, serial prompt, mail/calendar
  mutation, firmware write, or physical terminal action occurred.

## Rollback and remaining gates

The safest runtime rollback is to keep the independent server gates closed;
that is the deployed state. A code rollback can leave the additive `c6` schema
unused. Downgrading to `b5` removes the OTA tables and their history, so it is
safe only while they remain empty or after restoring/retaining the validated
backup above.

Before any real canary:

1. produce and sign a transport-enabled candidate with the reviewed public key;
2. physically migrate a dedicated E1001/E1002 to the exact `ab-v1` table;
3. execute the full 18-case HIL and USB-rescue evidence record;
4. install the exact eligible parent bundle and OTA descriptor;
5. explicitly confirm the printed device revision and HIL allowlist;
6. enable only one deterministic nonzero cohort; and
7. observe clean, gap-free success and rollback/recovery behavior before any
   manual rollout increase.

No automatic promotion worker or owner-facing OTA controls were added. Those
are follow-on product surfaces over this durable boundary, not prerequisites
for keeping the server safely locked today.
