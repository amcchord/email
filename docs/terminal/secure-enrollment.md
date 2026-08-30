# Secure terminal enrollment

This document defines the Email-side RET1 enrollment boundary for At a Glance
terminals. It describes implemented software foundations and the evidence still
required before a browser may request a serial port. Firmware installation and
OTA remain separate gates in [`firmware-management.md`](firmware-management.md).

## Current release posture

- Private firmware `main` is `f23d6302ae4bc64326f385fe44593e2ec47febd0`
  (`0.2.0-candidate.5`). Exact-main GitHub Actions run `33338824057` passed its
  keyed RET1/OTA guards, cross-language and host safety tests, all-model
  reproducibility, manifest, and bundle checks.
- Generic firmware artifacts remain unkeyed and enrollment-disabled. No release
  signing key, enrollment private key, credential, Wi-Fi value, or device image
  is committed to either repository.
- The Email application understands signed schema-2 RET1 release claims,
  owner-scoped enrollment intents, short-lived ES256 tickets, hashed device
  credentials, activation, one-generation rollback grace, and revocation.
- Production defaults remain locked. The shipped Admin surface can report
  policy and revoke an existing credential, but cannot request Web Serial,
  create configuration, download firmware, flash, or erase.
- Physical E1001 and E1002 HIL is still mandatory. E1004 remains blocked.

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
2. A future transport adapter obtains an explicit user-selected serial port and
   exchanges exact bounded `@RET1` status, hello, and hello-ack frames. Exact
   candidate.4 status v1 remains accepted; candidate.5 status v2 adds physical-
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
5. The browser verifies the JWS, encrypts the ticket and configuration through
   RET1, and sends them only to the attached device. Firmware verifies before
   decrypting and stages the configuration in its three-slot atomic NVS store.
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
- Activation retains exactly the immediately previous generation as a rollback
  URL for 24 hours. It is accepted only while one current active credential
  matches server generation/config state. Older rollback and candidate rows are
  revoked.
- Revocation locks the device, attempts, and all credentials; supersedes live
  attempts; revokes candidate, active, and rollback generations; and leaves the
  device isolated. Repeating it returns the same terminal state.
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
  WebCrypto module has no DOM, Serial, storage, network, or logging access and
  is not imported by the production UI.
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

1. Complete physical E1001 and E1002 tests for normal enrollment, wrong model,
   interrupted payload/marker writes, three-slot boot selection, old-config
   continuity, rollback grace, Wi-Fi failure, CA failure, candidate check-in,
   revocation, and ROM recovery.
2. Publish a signed schema-2 candidate from the exact reviewed firmware commit
   and stage it in the root-owned immutable artifact tree. Advance and pin a
   never-reused positive catalog generation.
3. Create the independent online P-256 key outside Git and artifacts, with the
   runtime service user as owner and mode `0400` or `0600`. Record only its key
   ID and public hash in the signed release/configuration.
4. Configure the exact HTTPS origin and the explicit release-to-model HIL
   allowlist. Verify capabilities become ready before adding any transport.
5. Add the Web Serial adapter as a separately reviewed production import. It
   must require explicit user gesture, never persist inputs, wipe owned mutable
   buffers, handle reconnect and interruption, and retain command-line rescue.
6. Re-run the complete application, protocol, disposable-PostgreSQL, Caddy,
   browser, and physical recovery gates. Enable one lab unit first.

OTA remains blocked after this checklist. It additionally requires CA-validated
HTTPS, signed A/B artifacts, pending-image validation, automatic rollback,
power gates, acknowledgements, cohorts, pause/revoke controls, and a tested USB
rescue bundle.
