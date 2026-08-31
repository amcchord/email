# At a Glance RET1 Browser Provisioning Release — 2026-08-30

## Outcome

At a Glance now contains the complete, independently gated browser path from
signed preserve-config firmware installation through RET1 encrypted device
configuration and scoped HTTPS activation. Production remains deliberately
locked: no trusted catalog key, positive generation, online enrollment key,
qualified release/model HIL tuple, or enablement is installed, so Wi-Fi inputs
are absent and Connect is disabled before any port or artifact request.

Exact application/runtime commit:
`739fe555d90dc9dd49ffdea28fc165ed2b0f7089`.

Exact private firmware `main`: candidate.8 at
`14f7046ae0253504f25972e9bc6ad952c1fa649f`; exact successful GitHub Actions
run: `33349001516`.

## Shipped Contract

- One explicit user action selects one Web Serial port and holds one
  origin-wide Web Lock through ROM identity, exact four-segment
  preserve-config write/readback, reset, RET1 status/hello, encrypted
  configuration/result, and activation polling.
- Wi-Fi SSID/password, configuration JSON, and the raw device credential remain
  in browser memory and then on the attached device. Application APIs receive
  only credential and configuration SHA-256 values.
- The browser validates compact-JWS structure and exact bindings. Firmware
  performs the authoritative ES256 signature verification before decrypting or
  staging the configuration in its three-slot atomic store.
- Pre-write cancellation is owner-scoped, same-origin, and bound to the exact
  attempt/client intent. A fresh old-generation handshake can safely retry with
  new hashes. A fresh observed target generation can reconcile one unique
  recent lost-result lineage; the browser never automatically replays an
  uncertain encrypted write.
- Browser completion remains advisory. Only the first matching device-scoped
  HTTPS check-in activates a candidate credential. Older generations retain
  the existing bounded rollback/revocation rules.
- Candidate.8 extends a configured device's initial reset window once, only
  after a valid hello, to a fixed 60-second-from-start ceiling. Invalid or
  repeated hellos cannot keep it awake. Unprovisioned and status-only windows
  retain their bounded behavior.

## Verification

- Backend: 716 passed, 65 expected skips.
- Frontend: all 440 tests passed.
- Disposable PostgreSQL: 29 enrollment lifecycle/concurrency/recovery tests
  passed at existing Alembic head `c6d7e8f9a0b1`.
- Frontend production build: 590 modules.
- Firmware Actions run `33349001516` passed release tooling, keyed RET1/OTA
  builds, all models, reproducibility, manifest verification, and immutable
  candidate upload at the exact candidate.8 SHA.
- Signed-in production browser QA was read-only. It confirmed the first-class
  At a Glance route, Browser terminal installer, supported HTTPS/WebSerial/Web
  Locks environment, visible lock blockers, zero Wi-Fi fields, disabled
  Connect, battery/health overview, and zero browser warnings/errors.

No E1001/E1002 hardware was attached. No serial chooser, artifact download,
flash, configuration write, enrollment, catalog/key ceremony, release
qualification, OTA offer, terminal mutation, or real mail/calendar mutation
occurred during release verification.

## Production Postflight

- Production built 590 frontend modules from runtime `739fe555`.
- All seven checked services are active; public health is `ok`.
- Replacement `mailapp` PID 2135271 has `NRestarts=0` and no warning-or-higher
  entries after 2026-08-31 02:00:12 UTC. The retired process emitted only the
  host's three known systemd graceful-stop timeout/kill/result lines.
- Anonymous enrollment and OTA capability endpoints return 401.
- Aggregate enrollment-attempt, device-credential, OTA-attempt, and OTA-event
  counts remain zero.
- Alembic remains exactly `c6d7e8f9a0b1 (head)`; the release is migration-free.
  Revision `d7e8f9a0b1c2` remains reserved for Personal Snippets.

## Remaining Gate and Rollback

The next action is physical execution of the 31-case schema-2 E1001/E1002 HIL
record, including reset timing, interruption, lost-result reconciliation,
three-slot continuity, TLS failure, activation/revocation, A/B recovery, and
secret-free evidence. Only after complete evidence may an operator perform the
protected offline signing ceremony or install any production key, catalog,
generation, allowlist, browser enablement, or OTA canary.

Application rollback is a Git fast-forward/revert to the preceding deployed
runtime; no database downgrade is involved. Candidate.8 is not promoted for a
device and production gates are false/empty, so rollback requires no credential
or terminal state repair.
