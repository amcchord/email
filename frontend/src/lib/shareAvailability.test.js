import assert from 'node:assert/strict';
import test from 'node:test';

import {
  availabilityCoverageMessage,
  availabilityDateRange,
  availabilityPlainInsertion,
  buildAvailabilityRequest,
  defaultAvailabilityAccountIds,
  formatAvailabilitySnapshot,
  groupAvailabilitySlots,
  normalizeAvailabilityResponse,
  senderCanShareAvailability,
} from './shareAvailability.js';

const accounts = [
  { id: 2, email: 'second@example.test', is_active: true, has_calendar_scope: true },
  { id: 1, email: 'sender@example.test', is_active: true, has_calendar_scope: true },
  { id: 3, email: 'mail-only@example.test', is_active: true, has_calendar_scope: false },
  { id: 4, email: 'inactive@example.test', is_active: false, has_calendar_scope: true },
];

const response = {
  ready: true,
  generated_at: '2026-08-31T15:30:00Z',
  timezone: 'America/New_York',
  duration_minutes: 30,
  coverage: [
    { account_id: 1, account_email: 'sender@example.test', state: 'ready', last_success_at: '2026-08-31T15:20:00Z' },
    { account_id: 2, account_email: 'second@example.test', state: 'ready', last_success_at: '2026-08-31T15:10:00Z' },
  ],
  slots: [
    { start: '2026-09-01T13:00:00-04:00', end: '2026-09-01T13:30:00-04:00' },
    { start: '2026-09-02T14:00:00-04:00', end: '2026-09-02T14:30:00-04:00' },
  ],
};

test('calendar scope defaults include every active scoped account and require the sender', () => {
  assert.deepEqual(defaultAvailabilityAccountIds(accounts, 1), [2, 1]);
  assert.equal(senderCanShareAvailability(accounts, 1), true);
  assert.equal(senderCanShareAvailability(accounts, 3), false);
  assert.deepEqual(defaultAvailabilityAccountIds(accounts, 3), []);
});

test('request captures exact sorted calendars and deterministic next-day range', () => {
  assert.deepEqual(buildAvailabilityRequest({
    accountIds: [2, 1, 2],
    senderAccountId: 1,
    durationMinutes: 30,
    rangeDays: 7,
    dayStart: '09:00',
    dayEnd: '17:00',
    includeWeekends: false,
    timeZone: 'America/New_York',
    now: new Date('2026-08-31T23:30:00Z'),
  }), {
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
  });
  assert.deepEqual(
    availabilityDateRange(14, 'Pacific/Auckland', new Date('2026-08-31T13:00:00Z')),
    { start: '2026-09-02', end: '2026-09-15' },
  );
  assert.throws(
    () => buildAvailabilityRequest({ accountIds: [2], senderAccountId: 1, timeZone: 'UTC' }),
    /sending account calendar/i,
  );
});

test('response normalization fails closed on widened, incomplete, or inconsistent coverage', () => {
  const normalized = normalizeAvailabilityResponse(response, {
    accountIds: [2, 1],
    timeZone: 'America/New_York',
    durationMinutes: 30,
  });
  assert.deepEqual(normalized.coverage.map(item => item.account_id), [1, 2]);
  assert.equal(normalized.slots.length, 2);
  assert.equal(normalized.slots[0].start, '2026-09-01T17:00:00.000Z');

  assert.throws(
    () => normalizeAvailabilityResponse(response, { accountIds: [1], timeZone: 'America/New_York', durationMinutes: 30 }),
    /changed the requested calendar coverage/i,
  );
  assert.throws(() => normalizeAvailabilityResponse({
    ...response,
    ready: true,
    coverage: [{ ...response.coverage[0], state: 'stale' }, response.coverage[1]],
  }, { accountIds: [1, 2] }), /overstates calendar coverage/i);
  assert.throws(() => normalizeAvailabilityResponse({
    ...response,
    ready: false,
  }, { accountIds: [1, 2] }), /cannot return times/i);
});

test('response caps selectable slots at eight and formats normalized UTC instants in the returned timezone', () => {
  const slots = Array.from({ length: 9 }, (_, index) => {
    const start = new Date(Date.UTC(2026, 8, 1, 13 + index));
    const end = new Date(start.getTime() + 30 * 60 * 1000);
    return { start: start.toISOString(), end: end.toISOString() };
  });
  const normalized = normalizeAvailabilityResponse({ ...response, slots }, {
    accountIds: [1, 2],
    timeZone: 'America/New_York',
    durationMinutes: 30,
  });
  assert.equal(normalized.slots.length, 8);
  assert.match(groupAvailabilitySlots(normalized.slots, normalized.timezone)[0].slots[0].label, /^9:00 AM EDT/);
});

test('formatters keep source metadata private while recipient copy includes timezone, duration, and exact dates', () => {
  const formatted = formatAvailabilitySnapshot(response, response.slots);
  assert.match(formatted.text, /^Here are a few times that work for me \(America\/New_York, 30 minutes\):/);
  assert.match(formatted.text, /Tuesday, September 1, 2026/);
  assert.match(formatted.text, /Wednesday, September 2, 2026/);
  assert.match(formatted.text, /Let me know what works best\.$/);
  assert.match(formatted.html, /Here are a few times that work for me/);
  assert.deepEqual(formatted.accounts, ['sender@example.test', 'second@example.test']);
  assert.equal(formatted.lastSyncedAt, '2026-08-31T15:10:00.000Z');
  assert.doesNotMatch(`${formatted.text}${formatted.html}`, /(?:sender|second)@example\.test/i);
  assert.doesNotMatch(`${formatted.text}${formatted.html}`, /last synced|Aug 31, 2026/i);
  assert.deepEqual(groupAvailabilitySlots(response.slots, response.timezone).map(group => group.slots.length), [1, 1]);
  assert.doesNotMatch(`${formatted.text}${formatted.html}`, /\b(?:live|hold|booked)\b/i);
});

test('coverage and plain insertion preserve truthful freshness and the current caret', () => {
  assert.match(availabilityCoverageMessage(response.coverage[0], response.timezone), /Last synced/);
  assert.match(availabilityCoverageMessage({ ...response.coverage[0], state: 'stale' }, response.timezone), /snapshot is stale/i);
  assert.deepEqual(
    availabilityPlainInsertion('Hello there', 'Here are times\n• Tuesday', 5),
    { inserted: '\n\nHere are times\n• Tuesday\n\n', caret: 33 },
  );
});
