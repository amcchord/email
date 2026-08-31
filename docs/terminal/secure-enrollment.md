# Secure terminal enrollment

This document defines the Email-side RET1 enrollment boundary for At a Glance
terminals. It describes implemented software foundations and the evidence still
required before a browser may request a serial port. Firmware installation and
OTA remain separate gates in [`firmware-management.md`](firmware-management.md).

## Current release posture

- Private firmware `main` is `52ba6c58ca7f17741d0d74c225f8d942b6119241`
  (`0.2.0-candidate.9`). Exact-SHA GitHub Actions run `33412815120` passed
  release tooling, keyed RET1 and OTA builds, all models, reproducibility,
  manifest verification, and immutable candidate upload. The same mainline now
  includes the offline schema-2 HIL-bound promotion tool and rejects invalid or
  non-DIO E1001/E1002 bootloader headers during packaging.
- Generic firmware artifacts remain unkeyed and enrollment-disabled. No release
  signing key, enrollment private key, credential, Wi-Fi value, or device image
  is committed to either repository.
- The deployed Email runtime `739fe555d90dc9dd49ffdea28fc165ed2b0f7089`
  now holds one user-selected Web Serial port and one exclusive Web Lock from
  exact preserve-config flash through RET1 result, creates Wi-Fi configuration
  only in browser memory, and activates only after the first scoped HTTPS
  check-in.
- Production defaults remain locked. No trusted catalog, online enrollment
  identity, qualified release/model pair, or HIL tuple exists, so the Wi-Fi
  fields are absent and the Connect action is disabled without requesting a
  port.
- One attached E1002 has completed a bounded command-line DIO install,
  configured HTTPS fetch/render/check-in, and sleep cycle. The complete
  revision-bound E1001/E1002 HIL record is still mandatory; E1004 remains
  blocked.

Software completeness is not physical qualification. Do not set an enablement
flag, stage an online key, qualify a release/model, or expose the transport UI
until the repeatable HIL matrix passes.

## Independent trust boundaries

```text
offline Ed25519 release key
  -> signed, generation-pinned schema-2 artifact catalog
  -> exact RET1 firmware/key/model claim
                                      \
protected online P-256 key ------------+-> short-lived ES256 ticket
browser-observed RET1 transcript -------/
  -> encrypted local configuration
  -> first scoped HTTPS check-in
  -> active per-device credential
```

The offline release key approves immutable firmware bytes. The online P-256
key authorizes one configuration transition. They must never be the same key or
share storage. The server loads the online key only from a non-symlink regular
file owned by its effective user, with mode `0400` or `0600`, and verifies the
opened file did not change during loading. The derived public-key hash and key
ID must exactly match the signed RET1 claim in the approved schema-2 release.

RET1 provides confidentiality and server authorization over a
browser-observed physical cable. It is not proof of genuine hardware or
approved firmware. Current devices have no Secure Boot, flash encryption, or
protected per-device attestation key, and their ROM downloader remains open.

## Enrollment flow

1. The authenticated browser reads private capabilities. A ready policy
   requires the server flag, exact HTTPS origin, protected online key, signed
   catalog and positive generation floor, matching schema-2 RET1 claim, and an
   explicit E1001/E1002 release/model HIL allowlist.
2. The gated transport adapter obtains one explicit user-selected serial port and
   exchanges exact bounded `@RET1` status, hello, and hello-ack frames. Exact
   candidate.4 status v1 remains accepted; candidate.9 status v2 adds physical-
   cable observations of partition layout, running slot, boot state, and source
   build ID without changing the v1 hello/hello-ack transcript. The
   browser verifies canonical encoding, P-256 points, transcript/session hash,
   model, MAC, firmware version, key ID, and generation.
3. The browser submits only that public transcript to create an owner-scoped,
   idempotent intent. The server reconstructs it independently and rejects
   replay, cross-owner identity, generation drift, unqualified firmware, E1004,
   or more than eight live attempts per owner.
4. The browser creates a random 32-byte URL credential and exact configuration
   locally. It submits only credential SHA-256 and configuration SHA-256. The
   server persists a candidate hash and returns one short-lived ES256 compact
   JWS bound to the exact transition.
5. The browser validates the compact JWS structure and exact transition
   bindings, encrypts the ticket and configuration through RET1, and sends them
   only to the attached device. Firmware performs the authoritative ES256
   signature verification before decrypting and stages the configuration in
   its three-slot atomic NVS store.
   Payload commit, readback, and marker commit preserve the current and
   immediate rollback configurations through interruption.
6. Browser result reporting is advisory. Server activation occurs only when the
   candidate credential first reaches its scoped HTTPS route with the expected
   normalized MAC and exact model query.

The server signs the exact configuration hash supplied by the browser. Because
the configuration is encrypted browser-to-device, the server cannot inspect
its Wi-Fi values or prove the embedded schedule URL equals its template. The
production transport must therefore use the reviewed first-party builder; a
future protocol version should bind the schedule URL or a server-created
configuration commitment if that trust assumption must be removed.

## Credential state and recovery

```text
legacy --intent--> pending --candidate check-in--> enrolled
  ^                    |                              |
  |                    +--24h stale cleanup----------+
  |                                                   |
  +--same-owner shared URL remains usable             +--re-enroll
                                                       -> candidate
                                                       -> new active
                                                       -> prior rollback (24h)

pending/enrolled --owner revoke--> revoked --qualified physical re-enroll--> enrolled
```

- Pending enrollment does not strand a legacy device: only that same owner's
  shared route remains usable. Other users are rejected.
- An enrolled or revoked device never resolves through a shared code. Global
  MAC lookup prevents spoofable auto-registration from recreating it.
- Re-enrollment does not replace the current active configuration on ticket
  issue or browser completion. Only candidate check-in activates it.
- A pre-write browser failure calls the exact owner/same-origin cancellation
  endpoint. Cancellation supersedes only that attempt and candidate; a later
  fresh handshake proving the old generation may safely reuse it with new
  hashes. If a result was lost after an encrypted write, the browser never
  replays automatically: a fresh observed target generation reconciles one
  unique recent lineage and advances again without treating cable evidence as
  activation.
- Activation retains exactly the immediately previous generation as a rollback
  URL for 24 hours. It is accepted only while one current active credential
  matches server generation/config state. Older rollback and candidate rows are
  revoked.
- Revocation locks the device, live RET1 enrollment attempts, and all
  credentials; supersedes those enrollment transitions; revokes candidate,
  active, and rollback generations; and leaves the device isolated. Repeating
  it returns the same terminal state. Historical OTA ledger rows remain
  immutable, while the revoked credential can no longer use their device
  routes.
- A revoked owner may start a new qualified physical enrollment at the exact
  current generation. The revoked state remains isolated until the new
  candidate actually checks in.

All state transitions use the canonical PostgreSQL lock order of device,
attempt, then credentials. Identity creation also takes a transaction advisory
lock derived from the normalized MAC, because an absent row cannot be locked.
A partial unique index allows historical/legacy duplicates but permits only one
non-legacy secure owner for a MAC. Disposable PostgreSQL tests cover concurrent
ownership, activation versus expiry, rollback grace, legacy continuity, and
idempotent revocation.

## Secret handling and HTTP boundary

- The raw device credential is generated in the browser and never sent to an
  application API. PostgreSQL stores only SHA-256.
- Wi-Fi SSID/password and configuration JSON stay browser-to-device. The pure
  WebCrypto module has no DOM, Serial, storage, network, or logging access; the
  production UI imports it only through the dynamically policy-gated workflow,
  clears its local fields at handoff/session teardown, and exposes no inputs
  while production policy is locked.
- Path credentials are unavoidable because current firmware persists only one
  schedule URL. Caddy skips the complete scoped path from access logs. The ASGI
  middleware immediately redacts the server-owned outer scope while routing a
  shallow copy with the real path, including unhandled exception paths.
- Scoped responses are private, revalidated, `nosniff`, and same-origin. A
  wrong UUID, credential, MAC, model/query, state, or grace window returns the
  same 404.
- E1001 requires `variant=bw`; E1002 requires no variant query. E1004 is not
  enrollment-qualified.

## Production enablement checklist

1. Complete the schema-2, 31-case physical E1001 and E1002 record for browser
   reset timing, normal enrollment, partial frames, payload/marker interruption,
   lost-result reconciliation, three-slot continuity, Wi-Fi/CA failure,
   activation, revocation/re-enrollment, A/B recovery, and secret-free evidence.
2. Publish a signed schema-2 candidate from the exact reviewed firmware commit
   and stage it in the root-owned immutable artifact tree. Advance and pin a
   never-reused positive catalog generation.
3. Create the independent online P-256 key outside Git and artifacts, with the
   runtime service user as owner and mode `0400` or `0600`. Record only its key
   ID and public hash in the signed release/configuration.
4. Configure the exact HTTPS origin and the explicit release-to-model HIL
   allowlist. Verify capabilities become ready before allowing the already
   deployed transport to render Wi-Fi inputs or enable Connect.
5. Exercise the exact deployed Web Serial adapter. It requires explicit user
   gesture, never persists inputs, clears owned mutable buffers, handles
   reconnect/interruption without automatic replay, and retains command-line
   rescue.
6. Re-run the complete application, protocol, disposable-PostgreSQL, Caddy,
   browser, and physical recovery gates. Enable one lab unit first.

OTA remains blocked after this checklist even though CA validation, the signed
A/B writer, pending validation/rollback, conservative power and deterministic
cohort gates, the PostgreSQL acknowledgement ledger/routes, and the firmware
coordinator now exist in default-locked software. A real offer still requires a
signed/keyed transport-enabled eligible release, exact E1001/E1002 OTA HIL and
printed-revision allowlist, physical `ab-v1` migration, nonzero rollout and
server enablement, deployed schema/configuration, and a tested USB rescue
bundle. E1004 remains blocked.
