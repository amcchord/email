import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createTerminalFirmwareDeviceSession,
  describeTerminalFirmwareInstallState,
  detectTerminalFirmwareSupport,
  getSelectedTerminalEnrollmentQualification,
  getTerminalInstallerLock,
  terminalEnrollmentCapabilitiesReady,
} from './terminalFirmwareInstaller.js';

const RELEASE_ID = 'a'.repeat(64);
const READY_ENROLLMENT = {
  schema_version: 1,
  state: 'ready',
  enabled: true,
  protocol: 'RET1',
  identity_strength: 'physical_cable_only',
  attestation: false,
  allowed_models: ['E1001', 'E1002'],
  qualified_releases: [{
    release_id: RELEASE_ID,
    firmware_version: '0.2.0-candidate.8',
    git_sha: 'b'.repeat(40),
    models: ['E1002'],
  }],
  blockers: [],
};

const SIGNED_RELEASE = {
  release_id: RELEASE_ID,
  firmware_version: '0.2.0-candidate.8',
  git_sha: 'b'.repeat(40),
  manifest_schema_version: 2,
  serial_enrollment: {
    protocol: 'RET1',
    enabled: true,
    trust_key_id: 'ret1-2026',
    public_key_sha256: 'c'.repeat(64),
    identity_strength: 'physical_cable_only',
    attestation: false,
  },
};

test('support detection observes HTTPS, Web Serial, and Web Locks without invoking them', () => {
  let serialCalls = 0;
  let lockCalls = 0;
  const support = detectTerminalFirmwareSupport({
    isSecureContext: true,
    navigator: {
      serial: { requestPort: () => { serialCalls += 1; } },
      locks: { request: () => { lockCalls += 1; } },
    },
  });

  assert.deepEqual(support, {
    secureContext: true,
    webSerial: true,
    webLocks: true,
    supported: true,
    blockers: [],
  });
  assert.equal(serialCalls, 0);
  assert.equal(lockCalls, 0);
});

test('support detection fails closed when browser primitives are absent or hostile', () => {
  assert.equal(detectTerminalFirmwareSupport({ isSecureContext: false, navigator: {} }).supported, false);
  const hostile = {};
  Object.defineProperty(hostile, 'navigator', { get: () => { throw new Error('blocked'); } });
  assert.deepEqual(detectTerminalFirmwareSupport(hostile), {
    secureContext: false,
    webSerial: false,
    webLocks: false,
    supported: false,
    blockers: ['Browser capability detection failed closed.'],
  });
});

test('installer lock is driven by signed catalog, browser support, and live enrollment qualification', () => {
  const locked = getTerminalInstallerLock(
    { valid: true },
    { supported: true, blockers: [] },
    {
      ...READY_ENROLLMENT,
      state: 'locked',
      enabled: false,
      qualified_releases: [],
      blockers: ['Physical E1002 enrollment qualification is incomplete.'],
    },
  );
  assert.deepEqual(locked, {
    locked: true,
    blockers: ['Physical E1002 enrollment qualification is incomplete.'],
  });

  const ready = getTerminalInstallerLock(
    { valid: true, catalog: { blockers: [] } },
    { supported: true, blockers: [] },
    READY_ENROLLMENT,
  );
  assert.deepEqual(ready, { locked: false, blockers: [] });
  assert.equal(terminalEnrollmentCapabilitiesReady(READY_ENROLLMENT), true);
  assert.equal(terminalEnrollmentCapabilitiesReady({ ...READY_ENROLLMENT, attestation: true }), false);
});

test('installer preserves server-side catalog blockers without a software hard-lock', () => {
  const lock = getTerminalInstallerLock(
    { valid: true, catalog: { blockers: ['Server writing is disabled.'] } },
    { supported: true, blockers: [] },
    READY_ENROLLMENT,
  );
  assert.equal(lock.locked, true);
  assert.equal(lock.blockers[0], 'Server writing is disabled.');
  assert.equal(lock.blockers.length, 1);
});

test('exact server-qualified release and model derives the immutable RET1 workflow contract', () => {
  assert.deepEqual(
    getSelectedTerminalEnrollmentQualification(READY_ENROLLMENT, SIGNED_RELEASE, 'E1002'),
    {
      releaseId: RELEASE_ID,
      enrollmentKeyId: 'ret1-2026',
      model: 'E1002',
      firmwareVersion: '0.2.0-candidate.8',
    },
  );
  assert.equal(
    getSelectedTerminalEnrollmentQualification(READY_ENROLLMENT, SIGNED_RELEASE, 'E1001'),
    null,
  );
  assert.equal(
    getSelectedTerminalEnrollmentQualification(
      READY_ENROLLMENT,
      { ...SIGNED_RELEASE, release_id: 'd'.repeat(64) },
      'E1002',
    ),
    null,
  );
});

test('operator state presentation distinguishes recovery from safe pre-write cancellation', () => {
  assert.deepEqual(describeTerminalFirmwareInstallState('recovery_required', 'write_interrupted'), {
    state: 'recovery_required',
    tone: 'danger',
    title: 'Recovery required',
    detail: 'Leave the USB cable connected, return the terminal to ROM mode, and retry only the exact preserve-config package.',
    errorCode: 'write_interrupted',
    recoveryRequired: true,
    canDisconnect: false,
  });
  const cancelled = describeTerminalFirmwareInstallState('cancelled_before_write');
  assert.equal(cancelled.recoveryRequired, false);
  assert.equal(cancelled.canDisconnect, true);
  assert.equal(describeTerminalFirmwareInstallState('probing').canDisconnect, true);
  assert.equal(describeTerminalFirmwareInstallState('flashing').canDisconnect, false);
  assert.equal(describeTerminalFirmwareInstallState('unknown').state, 'blocked');
});

test('device session aborts and closes each injected transport exactly once on disconnect', async () => {
  const session = createTerminalFirmwareDeviceSession();
  const controller = new AbortController();
  let closeCalls = 0;
  const transport = { close: async () => { closeCalls += 1; } };
  session.attach({ abortController: controller, transports: [transport, transport] });
  assert.equal(session.isActive(), true);
  assert.equal(await session.disconnect(), true);
  assert.equal(controller.signal.aborted, true);
  assert.equal(closeCalls, 1);
  assert.equal(session.isActive(), false);
  assert.equal(await session.disconnect(), false);

  let secondClosed = false;
  const throwing = { close: () => { throw new Error('close failed'); } };
  const second = { close: async () => { secondClosed = true; } };
  const cleanupController = new AbortController();
  session.attach({ abortController: cleanupController, transports: [throwing, second] });
  assert.equal(await session.disconnect(), true);
  assert.equal(secondClosed, true);

  const released = new AbortController();
  session.attach({ abortController: released, transports: [transport] });
  assert.equal(session.release(), true);
  assert.equal(released.signal.aborted, false);
  assert.equal(closeCalls, 1);
});
