import assert from 'node:assert/strict';
import test from 'node:test';

import { api } from './api.js';


test('availability API posts the exact request and preserves cancellation', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const controller = new AbortController();
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({
      url,
      method: options.method,
      body: JSON.parse(options.body),
      signal: options.signal,
    });
    return new Response(JSON.stringify({ ready: false, coverage: [], slots: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  const payload = {
    account_ids: [1, 2],
    start_date: '2026-09-01',
    end_date: '2026-09-07',
    timezone: 'America/New_York',
    duration_minutes: 30,
    step_minutes: 30,
    day_start: '09:00',
    day_end: '17:00',
    include_weekends: false,
    minimum_notice_minutes: 120,
  };
  await api.getCalendarAvailability(payload, { signal: controller.signal });

  assert.deepEqual(calls, [{
    url: '/api/calendar/availability',
    method: 'POST',
    body: payload,
    signal: controller.signal,
  }]);
});
