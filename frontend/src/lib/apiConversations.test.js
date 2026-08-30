import assert from 'node:assert/strict';
import test from 'node:test';

const calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url, options });
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => ({}),
  };
};

const { api } = await import('./api.js');

test('conversation list preserves existing mailbox and search parameters', async () => {
  calls.length = 0;
  await api.listConversations({ mailbox: 'INBOX', account_id: 7, search: 'from:generated@example.test' });
  assert.equal(calls[0].url, '/api/emails/conversations?mailbox=INBOX&account_id=7&search=from%3Agenerated%40example.test');
});

test('mail actions can request server-owned conversation expansion', async () => {
  calls.length = 0;
  await api.emailActions([42], 'archive', 'generated-key', null, 'conversations');
  const body = JSON.parse(calls[0].options.body);
  assert.deepEqual(body, {
    email_ids: [42],
    action: 'archive',
    idempotency_key: 'generated-key',
    scope: 'conversations',
  });
});
