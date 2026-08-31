import assert from 'node:assert/strict';
import test from 'node:test';

import { api } from './api.js';


function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}


test('account signature API uses only authenticated compose routes and exact revisions', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({
      url,
      method: options.method,
      body: options.body ? JSON.parse(options.body) : null,
    });
    return jsonResponse({});
  };

  const payload = {
    enabled: true,
    include_on_new: true,
    include_on_replies: true,
    include_on_forwards: false,
    body_html: '<p>Writer Name</p>',
    body_text: 'Writer Name',
    expected_revision: 2,
  };
  await api.listAccountSignatures();
  await api.replaceAccountSignature('17 / primary', payload);

  assert.deepEqual(calls, [
    { url: '/api/compose/signatures', method: 'GET', body: null },
    {
      url: '/api/compose/signatures/17%20%2F%20primary',
      method: 'PUT',
      body: payload,
    },
  ]);
});
