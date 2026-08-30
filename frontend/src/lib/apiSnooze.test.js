import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from './api.js';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('snooze API uses operation-scoped routes and exact payloads', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method, body: options.body ? JSON.parse(options.body) : null });
    return jsonResponse({ items: [], total: 0 });
  };

  const payload = {
    email_id: 17,
    wake_at: '2099-01-01T14:00:00Z',
    time_zone: 'America/New_York',
    condition: 'always',
    idempotency_key: '00000000-0000-4000-8000-000000000017',
  };
  await api.createSnooze(payload);
  await api.listSnoozes({ state: 'scheduled', limit: 25, offset: 50 });
  await api.getSnooze('id/with spaces');
  await api.getSnoozeByIdempotency('key/with spaces');
  await api.rescheduleSnooze('id/with spaces', {
    wake_at: '2099-01-02T14:00:00Z',
    time_zone: 'America/New_York',
  });
  await api.cancelSnooze('id/with spaces');
  await api.returnSnoozeNow('id/with spaces');

  assert.deepEqual(calls, [
    { url: '/api/snoozes', method: 'POST', body: payload },
    { url: '/api/snoozes?state=scheduled&limit=25&offset=50', method: 'GET', body: null },
    { url: '/api/snoozes/id%2Fwith%20spaces', method: 'GET', body: null },
    { url: '/api/snoozes/by-idempotency/key%2Fwith%20spaces', method: 'GET', body: null },
    { url: '/api/snoozes/id%2Fwith%20spaces/reschedule', method: 'PATCH', body: { wake_at: '2099-01-02T14:00:00Z', time_zone: 'America/New_York' } },
    { url: '/api/snoozes/id%2Fwith%20spaces/cancel', method: 'POST', body: {} },
    { url: '/api/snoozes/id%2Fwith%20spaces/return-now', method: 'POST', body: {} },
  ]);
});
