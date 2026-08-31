import assert from 'node:assert/strict';
import test from 'node:test';

import {
  canCancelTerminalOtaAttempt,
  cancelTerminalOtaAttempt,
  clearTerminalHardwareRevision,
  confirmTerminalHardwareRevision,
  getTerminalOtaAttempt,
  getTerminalOtaCapabilities,
  listTerminalOtaAttempts,
  normalizeTerminalHardwareRevision,
} from './terminalOtaApi.js';

const ATTEMPT_ID = '123e4567-e89b-42d3-a456-426614174000';

test('owner OTA API exposes only capability, history, detail, revision, and unstarted cancellation requests', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({
      url: String(url),
      method: options.method,
      body: options.body ? JSON.parse(options.body) : null,
      credentials: options.credentials,
    });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  await getTerminalOtaCapabilities();
  await listTerminalOtaAttempts(17);
  await getTerminalOtaAttempt(ATTEMPT_ID);
  await confirmTerminalHardwareRevision(17, '  V1.0-a  ');
  await clearTerminalHardwareRevision(17);
  await cancelTerminalOtaAttempt({
    attempt_id: ATTEMPT_ID,
    state: 'offered',
    last_sequence: 0,
  });

  assert.deepEqual(calls, [
    { url: '/api/terminal/firmware/ota/capabilities', method: 'GET', body: null, credentials: 'include' },
    { url: '/api/terminal/devices/17/ota/attempts', method: 'GET', body: null, credentials: 'include' },
    { url: `/api/terminal/ota/attempts/${ATTEMPT_ID}`, method: 'GET', body: null, credentials: 'include' },
    { url: '/api/terminal/devices/17', method: 'PATCH', body: { hardware_revision: 'V1.0-a' }, credentials: 'include' },
    { url: '/api/terminal/devices/17', method: 'PATCH', body: { hardware_revision: null }, credentials: 'include' },
    { url: `/api/terminal/ota/attempts/${ATTEMPT_ID}/cancel`, method: 'POST', body: { reason: 'owner_cancelled' }, credentials: 'include' },
  ]);
});

test('revision validation and cancellation fail closed before network access', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount += 1;
    throw new Error('network should not be reached');
  };

  assert.equal(normalizeTerminalHardwareRevision(' V1.0_rc-2 '), 'V1.0_rc-2');
  assert.throws(() => normalizeTerminalHardwareRevision(''), /1–64/);
  assert.throws(() => normalizeTerminalHardwareRevision('../V 1'), /printed revision/);
  assert.equal(canCancelTerminalOtaAttempt({ state: 'offered', last_sequence: 0 }), true);
  assert.equal(canCancelTerminalOtaAttempt({ state: 'offered', last_sequence: 1 }), false);
  assert.equal(canCancelTerminalOtaAttempt({ state: 'downloading', last_sequence: 1 }), false);

  assert.throws(
    () => cancelTerminalOtaAttempt({
      attempt_id: ATTEMPT_ID,
      state: 'downloading',
      last_sequence: 1,
    }),
    /Only an unstarted OTA offer/,
  );
  assert.throws(() => listTerminalOtaAttempts('../17'), /valid terminal device ID/);
  assert.throws(() => getTerminalOtaAttempt('../attempt'), /valid terminal OTA attempt ID/);
  assert.equal(fetchCount, 0);
});
