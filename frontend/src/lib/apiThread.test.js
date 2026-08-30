import assert from 'node:assert/strict';
import test from 'node:test';

import { api } from './api.js';


test('thread reads carry the exact account scope without changing the legacy call', async t => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async url => {
    calls.push(String(url));
    return new Response(JSON.stringify({ thread_id: 'thread/example', emails: [], participants: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  await api.getThread('thread-generated', 'desc', 22);
  await api.getThread('legacy-thread');

  assert.equal(calls[0], '/api/emails/thread/thread-generated?order=desc&account_id=22');
  assert.equal(calls[1], '/api/emails/thread/legacy-thread');
});
