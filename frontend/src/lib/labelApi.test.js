import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from './api.js';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('label actions send the local label id through the durable action endpoint', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let call;
  globalThis.fetch = async (url, options) => {
    call = { url, options };
    return jsonResponse({ request_id: 'request-label', state: 'staged' }, 202);
  };

  await api.emailActions([41, 42], 'move_to_label', 'label-key', 17);

  assert.equal(call.url, '/api/emails/actions');
  assert.deepEqual(JSON.parse(call.options.body), {
    email_ids: [41, 42],
    action: 'move_to_label',
    idempotency_key: 'label-key',
    label_id: 17,
  });
});

test('account label loading remains account scoped', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let url;
  globalThis.fetch = async requestUrl => {
    url = requestUrl;
    return jsonResponse([]);
  };

  await api.getLabels(7);
  assert.equal(url, '/api/emails/labels/all?account_id=7');
});
