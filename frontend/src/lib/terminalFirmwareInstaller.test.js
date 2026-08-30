import assert from 'node:assert/strict';
import test from 'node:test';

import {
  BROWSER_INSTALLER_SAFETY_GATES,
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
