import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  followUpDelayChoices,
  followUpPolicyIsDirty,
  followUpPolicyPayload,
  followUpPolicyForAccount,
  followUpPolicySummary,
  followUpReminderIsEnabled,
  followUpRequestFields,
  followUpSendSummary,
  normalizeFollowUpPolicy,
  normalizeFollowUpPolicyList,
  normalizeFollowUpReminderMode,
  validateFollowUpPolicy,
} from './followUpReminders.js';


const persisted = {
  account_id: 17,
  account_email: 'writer@example.test',
  enabled: true,
  delay_days: 5,
  wake_local_time: '08:30:00',
  time_zone: 'America/New_York',
  weekdays_only: true,
  revision: 4,
};


test('normalizes strict account policies and rejects malformed or duplicate lists', () => {
  assert.deepEqual(normalizeFollowUpPolicy(persisted), {
    ...persisted,
    wake_local_time: '08:30',
  });
  assert.equal(normalizeFollowUpPolicy({ ...persisted, delay_days: 4 }).delay_days, 4);
  assert.equal(normalizeFollowUpPolicy({ ...persisted, delay_days: 31 }), null);
  assert.equal(normalizeFollowUpPolicy({ ...persisted, time_zone: 'Not/AZone' }), null);
  assert.deepEqual(normalizeFollowUpPolicyList({ accounts: [persisted], total: 1 }).accounts[0].account_id, 17);
  assert.throws(
    () => normalizeFollowUpPolicyList({ accounts: [persisted, persisted], total: 2 }),
    /duplicate accounts/,
  );
  assert.throws(() => normalizeFollowUpPolicyList({ accounts: [persisted], total: 2 }), /total/);
});


test('preset choices retain a valid custom persisted delay', () => {
  assert.deepEqual(followUpDelayChoices(4), [1, 2, 3, 4, 5, 7, 14]);
  assert.deepEqual(followUpDelayChoices(5), [1, 2, 3, 5, 7, 14]);
  assert.deepEqual(followUpDelayChoices(31), [1, 2, 3, 5, 7, 14]);
});


test('revision-zero records receive safe default-off values in the valid browser timezone', () => {
  assert.deepEqual(normalizeFollowUpPolicy({
    account_id: 23,
    account_email: 'new@example.test',
    revision: 0,
  }, { browserTimeZone: 'Europe/London' }), {
    account_id: 23,
    account_email: 'new@example.test',
    enabled: false,
    delay_days: 3,
    wake_local_time: '09:00',
    time_zone: 'Europe/London',
    weekdays_only: true,
    revision: 0,
  });
  assert.equal(normalizeFollowUpPolicy({
    account_id: 23,
    account_email: 'new@example.test',
    revision: 0,
    time_zone: 'America/Chicago',
  }, { browserTimeZone: 'invalid/browser-zone' }).time_zone, 'America/Chicago');
});


test('save payloads preserve the effective timezone and revision while validation fails closed', () => {
  const normalized = normalizeFollowUpPolicy(persisted);
  assert.deepEqual(followUpPolicyPayload(normalized), {
    enabled: true,
    delay_days: 5,
    wake_local_time: '08:30',
    time_zone: 'America/New_York',
    weekdays_only: true,
    expected_revision: 4,
  });
  assert.equal(validateFollowUpPolicy({ ...normalized, wake_local_time: '25:00' }), 'Choose a valid local reminder time.');
  assert.throws(() => followUpPolicyPayload({ ...normalized, time_zone: '../UTC' }), /time zone is invalid/);
});


test('dirty state and effective summaries compare only editable values', () => {
  const normalized = normalizeFollowUpPolicy(persisted);
  assert.equal(followUpPolicyIsDirty(normalized, { ...normalized, account_email: 'renamed@example.test' }), false);
  assert.equal(followUpPolicyIsDirty(normalized, { ...normalized, delay_days: 7 }), true);
  assert.equal(
    followUpPolicySummary(normalized),
    'After 5 days at 08:30 · weekdays only · America/New_York',
  );
  assert.equal(followUpPolicySummary({ ...normalized, enabled: false }), 'Off — no automatic reminders');
});


test('send helpers preserve tri-state intent and derive the selected account schedule', () => {
  const normalized = normalizeFollowUpPolicy(persisted);
  assert.equal(followUpPolicyForAccount([normalized], '17'), normalized);
  assert.equal(followUpPolicyForAccount([normalized], 99), null);
  assert.equal(normalizeFollowUpReminderMode('ENABLED'), 'enabled');
  assert.equal(normalizeFollowUpReminderMode('unexpected'), 'default');
  assert.equal(followUpReminderIsEnabled('default', normalized), true);
  assert.equal(followUpReminderIsEnabled('disabled', normalized), false);
  assert.equal(followUpReminderIsEnabled('enabled', { ...normalized, enabled: false }), true);
  assert.equal(
    followUpSendSummary({ ...normalized, enabled: false }),
    'After 5 days at 08:30 · weekdays only · America/New_York',
  );
  assert.deepEqual(followUpRequestFields({ mode: 'enabled', policy: normalized }), {
    follow_up_reminder: 'enabled',
    follow_up_time_zone: 'America/New_York',
  });
  assert.deepEqual(followUpRequestFields({ mode: 'bogus', timeZone: 'Europe/London' }), {
    follow_up_reminder: 'default',
    follow_up_time_zone: 'Europe/London',
  });
});


test('settings surface states privacy, explicit saves, and authenticated-session boundaries', async () => {
  const source = await readFile(new URL('./admin/FollowUpPreferences.svelte', import.meta.url), 'utf8');
  assert.match(source, /provider confirms delivery/);
  assert.match(source, /no tracking pixels or read receipts/);
  assert.match(source, /Save changes/);
  assert.match(source, /captureAuthenticatedSession\(\)/);
  assert.match(source, /isAuthenticatedSessionCurrent\(session\)/);
  assert.match(source, /api\.listFollowUpPolicies\(\)/);
  assert.match(source, /api\.replaceFollowUpPolicy\(policy\.account_id, payload\)/);
});
