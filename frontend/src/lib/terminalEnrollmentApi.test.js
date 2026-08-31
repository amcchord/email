import assert from 'node:assert/strict';
import test from 'node:test';

import {
  cancelTerminalEnrollmentIntent,
  completeTerminalEnrollmentIntent,
  createTerminalEnrollmentIntent,
  getTerminalEnrollmentIntent,
  issueTerminalEnrollmentTicket,
  terminalEnrollmentRevokeEndpoint,
} from './terminalEnrollmentApi.js';

const ATTEMPT_ID = '123e4567-e89b-42d3-a456-426614174000';

test('terminal revocation endpoint is scoped to the encoded public device id', () => {
  assert.equal(
    terminalEnrollmentRevokeEndpoint('52e18b2d-84af-4f3b-a059-f316930c8ef5'),
    '/terminal/enrollment/devices/52e18b2d-84af-4f3b-a059-f316930c8ef5/revoke',
  );
  assert.equal(
    terminalEnrollmentRevokeEndpoint('device/id'),
    '/terminal/enrollment/devices/device%2Fid/revoke',
  );
});

test('terminal revocation endpoint rejects a missing public device id', () => {
  assert.throws(() => terminalEnrollmentRevokeEndpoint(''), /public ID is required/);
  assert.throws(() => terminalEnrollmentRevokeEndpoint('   '), /public ID is required/);
  assert.throws(() => terminalEnrollmentRevokeEndpoint(null), /public ID is required/);
});

test('RET1 enrollment API exposes the exact intent, ticket, completion, cancellation, and read routes', async t => {
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
    return new Response(JSON.stringify({ attempt_id: ATTEMPT_ID }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  const intent = { client_intent_id: ATTEMPT_ID, operation: 'provision' };
  const ticket = {
    client_ticket_id: ATTEMPT_ID,
    credential_sha256: 'a'.repeat(64),
    config_sha256: 'b'.repeat(64),
  };
  const complete = {
    client_ticket_id: ATTEMPT_ID,
    operation: 'provision',
    generation: 1,
    config_sha256: 'b'.repeat(64),
  };
  const cancel = { client_intent_id: ATTEMPT_ID, operation: 'cancel' };

  await createTerminalEnrollmentIntent(intent);
  await issueTerminalEnrollmentTicket(ATTEMPT_ID, ticket);
  await completeTerminalEnrollmentIntent(ATTEMPT_ID, complete);
  await cancelTerminalEnrollmentIntent(ATTEMPT_ID, cancel);
  await getTerminalEnrollmentIntent(ATTEMPT_ID);

  assert.deepEqual(calls, [
    { url: '/api/terminal/enrollment/intents', method: 'POST', body: intent, credentials: 'include' },
    { url: `/api/terminal/enrollment/intents/${ATTEMPT_ID}/ticket`, method: 'POST', body: ticket, credentials: 'include' },
    { url: `/api/terminal/enrollment/intents/${ATTEMPT_ID}/complete`, method: 'POST', body: complete, credentials: 'include' },
    { url: `/api/terminal/enrollment/intents/${ATTEMPT_ID}/cancel`, method: 'POST', body: cancel, credentials: 'include' },
    { url: `/api/terminal/enrollment/intents/${ATTEMPT_ID}`, method: 'GET', body: null, credentials: 'include' },
  ]);
});

test('RET1 enrollment attempt routes reject non-canonical IDs before network access', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount += 1;
    throw new Error('network should not be reached');
  };

  assert.throws(() => getTerminalEnrollmentIntent('../attempt'), /valid terminal enrollment attempt ID/);
  assert.throws(() => issueTerminalEnrollmentTicket('not-a-uuid', {}), /valid terminal enrollment attempt ID/);
  assert.throws(() => completeTerminalEnrollmentIntent('', {}), /valid terminal enrollment attempt ID/);
  assert.throws(() => cancelTerminalEnrollmentIntent('not-an-attempt', {}), /valid terminal enrollment attempt ID/);
  assert.equal(fetchCount, 0);
});
