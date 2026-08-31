import assert from 'node:assert/strict';
import test from 'node:test';

import {
  BROWSER_INSTALLER_SAFETY_GATES,
  createTerminalFirmwareDeviceSession,
  describeTerminalFirmwareInstallState,
  detectTerminalFirmwareSupport,
  getTerminalInstallerLock,
} from './terminalFirmwareInstaller.js';

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

test('installer remains unconditionally locked behind all three future safety gates', () => {
  assert.deepEqual(BROWSER_INSTALLER_SAFETY_GATES, {
    browserSignatureVerification: false,
    secureDeviceProvisioning: false,
    hardwareInLoopQualification: false,
  });
  const lock = getTerminalInstallerLock(
    { valid: true },
    { supported: true, blockers: [] },
  );
  assert.equal(lock.locked, true);
  assert.equal(lock.blockers.length, 3);
  assert.match(lock.blockers.join(' '), /signature verification/i);
  assert.match(lock.blockers.join(' '), /provisioning/i);
  assert.match(lock.blockers.join(' '), /hardware-in-the-loop/i);
});

test('installer preserves server-side catalog blockers while remaining client-locked', () => {
  const lock = getTerminalInstallerLock(
    { valid: true, catalog: { blockers: ['Server writing is disabled.'] } },
    { supported: true, blockers: [] },
  );
  assert.equal(lock.locked, true);
  assert.equal(lock.blockers[0], 'Server writing is disabled.');
  assert.equal(lock.blockers.length, 4);
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
