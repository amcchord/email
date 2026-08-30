import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildSnoozeRequest,
  createSnoozeWithReconciliation,
  normalizeSnoozedList,
  snoozedRecordToEmail,
} from './snooze.js';

test('create request preserves exact email, UTC instant, timezone, condition, and idempotency', () => {
  const result = buildSnoozeRequest(42, {
    wakeAt: '2099-11-01T06:30:00.000Z',
    timeZone: 'America/New_York',
    condition: 'if_no_reply',
    idempotencyKey: '00000000-0000-4000-8000-000000000042',
  });

  assert.deepEqual(result, {
    email_id: 42,
    wake_at: '2099-11-01T06:30:00.000Z',
    time_zone: 'America/New_York',
    condition: 'if_no_reply',
    idempotency_key: '00000000-0000-4000-8000-000000000042',
  });
});

test('lost create response retries the identical operation then resolves by idempotency key', async () => {
  const payload = { idempotency_key: 'stable-key' };
  let createCalls = 0;
  let lookupKey = null;
  const result = await createSnoozeWithReconciliation({
    createSnooze: async received => {
      assert.equal(received, payload);
      createCalls += 1;
      throw new TypeError('network response lost');
    },
    getSnoozeByIdempotency: async key => {
      lookupKey = key;
      return { id: 'accepted-reminder' };
    },
  }, payload);

  assert.equal(createCalls, 2);
  assert.equal(lookupKey, 'stable-key');
  assert.deepEqual(result, { id: 'accepted-reminder' });
});

test('unreachable reconciliation remains explicitly ambiguous', async () => {
  const payload = { idempotency_key: 'stable-key' };
  await assert.rejects(
    createSnoozeWithReconciliation({
      createSnooze: async () => { throw new TypeError('network response lost'); },
      getSnoozeByIdempotency: async () => { throw new TypeError('lookup unavailable'); },
    }, payload),
    error => error.code === 'snooze_outcome_unknown',
  );
});

test('request builder rejects missing identity, invalid conditions, and past times', () => {
  assert.throws(() => buildSnoozeRequest(null, { wakeAt: '2099-01-01T00:00:00Z' }), /Choose an email/);
  assert.throws(() => buildSnoozeRequest(1, { wakeAt: '2000-01-01T00:00:00Z' }), /one minute/);
  assert.throws(() => buildSnoozeRequest(1, { wakeAt: '2099-01-01T00:00:00Z', condition: 'maybe' }), /valid reminder condition/);
});

test('snooze list records become Inbox-compatible rows without losing reminder identity', () => {
  const record = {
    id: 'reminder-public-id',
    email_id: 9,
    account_id: 3,
    account_email: 'generated@example.test',
    gmail_thread_id: 'thread-9',
    wake_at: '2099-01-01T14:00:00Z',
    time_zone: 'America/New_York',
    condition: 'always',
    state: 'scheduled',
    email: { id: 9, subject: 'Generated reminder', snippet: 'Safe fixture' },
  };

  assert.deepEqual(snoozedRecordToEmail(record), {
    id: 9,
    subject: 'Generated reminder',
    snippet: 'Safe fixture',
    account_id: 3,
    account_email: 'generated@example.test',
    gmail_thread_id: 'thread-9',
    snooze_id: 'reminder-public-id',
    snooze_wake_at: '2099-01-01T14:00:00Z',
    snooze_time_zone: 'America/New_York',
    snooze_condition: 'always',
    snooze_state: 'scheduled',
    snooze_status_detail: null,
  });

  assert.deepEqual(normalizeSnoozedList({ items: [record], total: 1 }), {
    emails: [snoozedRecordToEmail(record)],
    total: 1,
  });
});
