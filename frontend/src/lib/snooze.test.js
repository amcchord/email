import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildSnoozeRequest,
  createSnoozeWithReconciliation,
  cancelAccepted,
  normalizeSnoozedList,
  partitionSnoozeConversation,
  reconcileActiveSnoozeEmails,
  rescheduleMatches,
  returnNowAccepted,
  runSnoozeMutationWithReconciliation,
  snoozeMatchesEmail,
  snoozeThreadKey,
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

test('lifecycle transport failure reconciles authoritative reschedule and return states', async () => {
  const rescheduled = {
    wake_at: '2099-01-02T14:00:00Z',
    time_zone: 'America/New_York',
    state: 'scheduled',
  };
  const result = await runSnoozeMutationWithReconciliation({
    mutate: async () => { throw new TypeError('response lost'); },
    lookup: async () => rescheduled,
    accepted: record => rescheduleMatches(record, rescheduled.wake_at, rescheduled.time_zone),
  });
  assert.equal(result, rescheduled);
  assert.equal(returnNowAccepted({ state: 'pending_return' }), true);
  assert.equal(returnNowAccepted({ state: 'returned' }), true);
  assert.equal(cancelAccepted({ state: 'cancelled' }), true);
  assert.equal(cancelAccepted({ state: 'scheduled' }), false);
});

test('unreachable lifecycle lookup stays unknown instead of authorizing rollback', async () => {
  await assert.rejects(
    runSnoozeMutationWithReconciliation({
      mutate: async () => { throw new TypeError('response lost'); },
      lookup: async () => { throw new TypeError('lookup lost'); },
      accepted: returnNowAccepted,
    }),
    error => error.code === 'snooze_mutation_outcome_unknown',
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

test('active reminders match every row in the owned account and conversation', () => {
  const reminder = {
    email_id: 9,
    account_id: 3,
    gmail_thread_id: 'thread-9',
  };

  assert.equal(snoozeThreadKey(reminder), '3:thread-9');
  assert.equal(snoozeMatchesEmail(reminder, {
    id: 10,
    account_id: 3,
    gmail_thread_id: 'thread-9',
  }), true);
  assert.equal(snoozeMatchesEmail(reminder, {
    id: 10,
    account_id: 4,
    gmail_thread_id: 'thread-9',
  }), false);
  assert.equal(snoozeMatchesEmail({ email_id: 9 }, { id: 9 }), true);
  assert.equal(snoozeMatchesEmail({ email_id: 9 }, { id: 10 }), false);
});

test('Inbox conversation projection removes siblings and retained views annotate them', () => {
  const inboxRows = [
    { id: 101, account_id: 1, gmail_thread_id: 'generated-thread-1', subject: 'Design review notes' },
    { id: 102, account_id: 1, gmail_thread_id: 'generated-thread-1', subject: 'Re: Design review notes' },
    { id: 103, account_id: 1, gmail_thread_id: 'generated-thread-2', subject: 'Other thread' },
  ];
  const reminder = {
    id: 'generated-snooze-1',
    email_id: 101,
    account_id: 1,
    gmail_thread_id: 'generated-thread-1',
    wake_at: '2099-01-01T14:00:00Z',
    time_zone: 'America/New_York',
    condition: 'always',
    state: 'scheduled',
  };

  const optimistic = partitionSnoozeConversation(inboxRows, reminder);
  assert.deepEqual(optimistic.matched.map(entry => entry.email.id), [101, 102]);
  assert.deepEqual(optimistic.remaining.map(email => email.id), [103]);

  const hidden = reconcileActiveSnoozeEmails(inboxRows, [reminder]);
  assert.equal(hidden.matchedCount, 2);
  assert.deepEqual(hidden.emails.map(email => email.id), [103]);

  const retained = reconcileActiveSnoozeEmails(inboxRows, [reminder], { retain: true });
  assert.deepEqual(retained.emails.map(email => email.snooze_id || null), [
    'generated-snooze-1',
    'generated-snooze-1',
    null,
  ]);
});
