import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from './api.js';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('outbound creation requires and forwards the controller-owned idempotency key', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let call = null;
  globalThis.fetch = async (url, options) => {
    call = { url, options };
    return jsonResponse({ send_id: 'send-1', state: 'staged' }, 202);
  };

  assert.throws(
    () => api.sendEmail({ subject: 'missing key' }),
    /idempotency key is required/,
  );

  const result = await api.sendEmail(
    { account_id: 7, to: ['person@example.com'], subject: 'Hello' },
    '00000000-0000-4000-8000-000000000111',
  );

  assert.equal(call.url, '/api/compose/send');
  assert.equal(call.options.method, 'POST');
  assert.deepEqual(JSON.parse(call.options.body), {
    account_id: 7,
    to: ['person@example.com'],
    subject: 'Hello',
    idempotency_key: '00000000-0000-4000-8000-000000000111',
  });
  assert.equal(result.state, 'staged');
});

test('outbound lifecycle helpers use encoded operation-scoped routes', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method });
    return jsonResponse([]);
  };

  await api.listRecentOutboundSends(7);
  await api.getOutboundSendByIdempotency('key/with spaces');
  await api.getOutboundSend('send/with spaces');
  await api.undoOutboundSend('send/with spaces');
  await api.retryOutboundSend('send/with spaces');

  assert.deepEqual(calls, [
    { url: '/api/compose/sends/recent?limit=7', method: 'GET' },
    { url: '/api/compose/sends/by-idempotency/key%2Fwith%20spaces', method: 'GET' },
    { url: '/api/compose/sends/send%2Fwith%20spaces', method: 'GET' },
    { url: '/api/compose/sends/send%2Fwith%20spaces/undo', method: 'POST' },
    { url: '/api/compose/sends/send%2Fwith%20spaces/retry', method: 'POST' },
  ]);
});

test('outbound lookup errors preserve HTTP status for reconciliation', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({
    detail: { code: 'outbound_not_found', message: 'Send not found' },
  }, 404);

  await assert.rejects(
    api.getOutboundSendByIdempotency('missing-key'),
    error => error.message === 'Send not found'
      && error.status === 404
      && error.code === 'outbound_not_found',
  );
});
