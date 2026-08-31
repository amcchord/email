import assert from 'node:assert/strict';
import test from 'node:test';

import { api } from './api.js';

test('Inbox placement rule API uses private query/body contracts and cancellation', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null, signal: options.signal });
    if (options.method === 'DELETE') return new Response(null, { status: 204 });
    return new Response(JSON.stringify({
      id: '9a14d2a4-7832-4e37-995c-dcb085ac6ed5',
      account_id: 7,
      account_email: 'work@example.test',
      scope: 'sender',
      display_value: 'sender@example.test',
      placement: 'other',
      enabled: true,
      revision: 2,
      created_at: '2026-08-31T12:00:00Z',
      updated_at: '2026-08-31T12:00:00Z',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  const controller = new AbortController();
  await api.getInboxPlacementRuleCandidate(7, 91, { signal: controller.signal });
  const payload = {
    create_id: 'c4b2a424-4834-4f0d-b104-82216418d2fd',
    account_id: 7,
    anchor_email_id: 91,
    scope: 'sender',
    placement: 'other',
    enabled: true,
    expected_revision: 0,
  };
  await api.createInboxPlacementRule(payload);
  await api.updateInboxPlacementRule('9a14d2a4-7832-4e37-995c-dcb085ac6ed5', { placement: 'focused', enabled: false, revision: 2 });
  await api.deleteInboxPlacementRule('9a14d2a4-7832-4e37-995c-dcb085ac6ed5', 3);

  assert.deepEqual(calls, [
    { url: '/api/inbox-placement-rules/candidate?account_id=7&anchor_email_id=91', method: 'GET', body: null, signal: controller.signal },
    { url: '/api/inbox-placement-rules', method: 'POST', body: payload, signal: undefined },
    { url: '/api/inbox-placement-rules/9a14d2a4-7832-4e37-995c-dcb085ac6ed5', method: 'PUT', body: { placement: 'focused', enabled: false, revision: 2 }, signal: undefined },
    { url: '/api/inbox-placement-rules/9a14d2a4-7832-4e37-995c-dcb085ac6ed5?revision=3', method: 'DELETE', body: null, signal: undefined },
  ]);
});
