import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from './api.js';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('draft upsert requires stable identity, revision, and mutation UUID fields', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let call = null;
  globalThis.fetch = async (url, options) => {
    call = { url, options };
    return jsonResponse({ client_draft_id: 'draft-1', revision: 1, state: 'pending' }, 202);
  };

  assert.throws(() => api.saveDraft({ revision: 1, mutation_id: 'mutation-1' }), /client draft ID/);
  assert.throws(
    () => api.saveDraft({ client_draft_id: 'draft-1', revision: 0, mutation_id: 'mutation-1' }),
    /positive draft revision/,
  );
  assert.throws(
    () => api.saveDraft({ client_draft_id: 'draft-1', revision: 1 }),
    /draft mutation ID/,
  );

  const result = await api.saveDraft({
    client_draft_id: '00000000-0000-4000-8000-000000000101',
    revision: 1,
    mutation_id: '00000000-0000-4000-8000-000000000201',
    account_id: 7,
    subject: 'Generated draft',
  });

  assert.equal(call.url, '/api/compose/draft');
  assert.equal(call.options.method, 'POST');
  assert.equal(JSON.parse(call.options.body).revision, 1);
  assert.equal(result.state, 'pending');
});

test('draft lifecycle helpers encode client IDs and preserve action identity', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null });
    return jsonResponse({});
  };

  await api.getComposeDraft('draft/with spaces');
  await api.getComposeDraftByEmail('email/with spaces');
  await api.listRecentComposeDrafts(7);
  await api.discardComposeDraft('draft/with spaces', 'mutation-7');
  await api.undoComposeDraftDiscard('draft/with spaces', 'mutation-8');

  assert.deepEqual(calls, [
    { url: '/api/compose/drafts/by-client-id/draft%2Fwith%20spaces', method: 'GET', body: null },
    { url: '/api/compose/drafts/by-email/email%2Fwith%20spaces', method: 'GET', body: null },
    { url: '/api/compose/drafts/recent?limit=7', method: 'GET', body: null },
    {
      url: '/api/compose/drafts/draft%2Fwith%20spaces/discard',
      method: 'POST',
      body: { mutation_id: 'mutation-7' },
    },
    {
      url: '/api/compose/drafts/draft%2Fwith%20spaces/undo-discard',
      method: 'POST',
      body: { mutation_id: 'mutation-8' },
    },
  ]);
});
