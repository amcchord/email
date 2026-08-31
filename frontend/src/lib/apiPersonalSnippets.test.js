import assert from 'node:assert/strict';
import test from 'node:test';

import { api } from './api.js';


function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}


test('personal snippet API uses only authenticated compose routes and exact versions', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({
      url,
      method: options.method,
      body: options.body ? JSON.parse(options.body) : null,
    });
    return options.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse({});
  };

  const payload = {
    snippet_id: '00000000-0000-4000-8000-000000000101',
    name: 'Generated snippet',
    shortcut: 'generated',
    body_html: '<p>Generated</p>',
    body_text: 'Generated',
  };
  await api.listPersonalSnippets();
  await api.createPersonalSnippet(payload);
  await api.replacePersonalSnippet('id/with spaces', { ...payload, expected_revision: 2 });
  await api.deletePersonalSnippet('id/with spaces', 3);

  assert.deepEqual(calls, [
    { url: '/api/compose/snippets', method: 'GET', body: null },
    { url: '/api/compose/snippets', method: 'POST', body: payload },
    {
      url: '/api/compose/snippets/id%2Fwith%20spaces',
      method: 'PUT',
      body: { ...payload, expected_revision: 2 },
    },
    {
      url: '/api/compose/snippets/id%2Fwith%20spaces?expected_revision=3',
      method: 'DELETE',
      body: null,
    },
  ]);
});
