import assert from 'node:assert/strict';
import test from 'node:test';

import { api } from './api.js';


test('email search query round-trips reserved characters through URLSearchParams', async t => {
  const originalFetch = globalThis.fetch;
  const query = 'from:renee+launch@example.test subject:"Q3 & 工作" -is:read ticket:1234';
  let requestedUrl = '';

  globalThis.fetch = async url => {
    requestedUrl = String(url);
    return {
      ok: true,
      status: 200,
      json: async () => ({ emails: [], total: 0, page: 1, page_size: 50, total_pages: 0 }),
    };
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  await api.listEmails({
    mailbox: 'ALL',
    search: query,
    tz: 'America/New_York',
  });

  const parsed = new URL(requestedUrl, 'https://mail.example.test');
  assert.equal(parsed.pathname, '/api/emails/');
  assert.deepEqual(parsed.searchParams.getAll('search'), [query]);
  assert.equal(parsed.searchParams.get('mailbox'), 'ALL');
  assert.equal(parsed.searchParams.get('tz'), 'America/New_York');
});
