#!/usr/bin/env node

// Focused contract test for the loopback-only touch-first triage fixture.
// It proves generated preference, staged action, Undo, snooze, idempotency,
// account, protected-mailbox, and stale-session boundaries without a browser.

import assert from 'node:assert/strict';

import {
  GENERATED_TOUCH_TRIAGE_HOST,
  createGeneratedTouchTriageFixture,
} from './generated_touch_triage_server.mjs';

const fixture = createGeneratedTouchTriageFixture();
const address = await fixture.listen(0);
const baseUrl = `http://${GENERATED_TOUCH_TRIAGE_HOST}:${address.port}`;

async function rawRequest(method, pathname, body) {
  return fetch(`${baseUrl}${pathname}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function request(method, pathname, body, expectedStatus = 200) {
  const response = await rawRequest(method, pathname, body);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  assert.equal(
    response.status,
    expectedStatus,
    `${method} ${pathname}: ${JSON.stringify(payload)}`,
  );
  assert.match(response.headers.get('cache-control') || '', /no-store/i);
  return payload;
}

const get = (pathname, expectedStatus = 200) => request('GET', pathname, undefined, expectedStatus);
const post = (pathname, body, expectedStatus = 200) => request('POST', pathname, body, expectedStatus);
const put = (pathname, body, expectedStatus = 200) => request('PUT', pathname, body, expectedStatus);

async function reset(scenario = 'ready', currentUser = 'generated-a') {
  return post('/__qa/reset', { scenario, current_user: currentUser });
}

async function audit() {
  return get('/__qa/audit');
}

function actionPayload(emailId, action, suffix, overrides = {}) {
  return {
    email_ids: [emailId],
    action,
    idempotency_key: `71000000-0000-4000-8000-${String(suffix).padStart(12, '0')}`,
    scope: 'conversations',
    ...overrides,
  };
}

function snoozePayload(emailId, suffix) {
  return {
    email_id: emailId,
    wake_at: '2026-09-01T14:00:00.000Z',
    time_zone: 'America/New_York',
    condition: 'always',
    idempotency_key: `72000000-0000-4000-8000-${String(suffix).padStart(12, '0')}`,
  };
}

const ZERO_EXTERNAL_COUNTERS = [
  'provider_reads',
  'provider_calls',
  'provider_writes',
  'gmail_reads',
  'gmail_writes',
  'email_sends',
  'mail_mutations',
  'calendar_reads',
  'calendar_writes',
  'ai_calls',
  'worker_jobs',
  'terminal_reads',
  'terminal_operations',
  'external_network_calls',
  'unexpected_writes',
  'unknown_routes',
];

function assertGeneratedBoundary(snapshot) {
  assert.equal(snapshot.generated_only, true);
  assert.equal(snapshot.localhost_only, true);
  assert.deepEqual(snapshot.fixture_domains, ['example.test']);
  assert.equal(JSON.stringify(snapshot).includes('@gmail.com'), false);
  for (const counter of ZERO_EXTERNAL_COUNTERS) {
    assert.equal(snapshot.counters[counter], 0, `${counter} must remain zero`);
  }
}

const results = {};

try {
  // Preferences expose the exact defaults, accept a partial update, retain
  // unrelated fields, and reject an unknown action without a local write.
  await reset();
  const defaults = await get('/api/auth/ui-preferences');
  assert.deepEqual(defaults, {
    thread_order: 'newest_first',
    theme: 'amber',
    color_scheme: 'light',
    swipe_left_action: 'archive',
    swipe_right_action: 'snooze',
  });
  const changed = await put('/api/auth/ui-preferences', {
    swipe_left_action: 'toggle_read',
    swipe_right_action: 'toggle_star',
  });
  assert.equal(changed.swipe_left_action, 'toggle_read');
  assert.equal(changed.swipe_right_action, 'toggle_star');
  assert.equal(changed.thread_order, 'newest_first');
  await put('/api/auth/ui-preferences', { swipe_left_action: 'delete' }, 422);
  let snapshot = await audit();
  assert.equal(snapshot.counters.preference_reads, 1);
  assert.equal(snapshot.counters.preference_updates, 1);
  assert.equal(snapshot.counters.expected_preference_writes, 1);
  assertGeneratedBoundary(snapshot);
  results.preferences = snapshot.counters;

  // The ordinary conversation endpoint is account exact and exposes protected
  // mailbox fixtures without ever accepting archive from Trash or Spam.
  await reset();
  const merged = await get('/api/emails/conversations?mailbox=INBOX&page=1&page_size=50');
  const primary = await get('/api/emails/conversations?mailbox=INBOX&account_id=9101&page=1&page_size=50');
  const secondary = await get('/api/emails/conversations?mailbox=INBOX&account_id=9102&page=1&page_size=50');
  const trash = await get('/api/emails/conversations?mailbox=TRASH&account_id=9101&page=1&page_size=50');
  const spam = await get('/api/emails/conversations?mailbox=SPAM&account_id=9101&page=1&page_size=50');
  assert.equal(merged.total, 6);
  assert.equal(primary.total, 4);
  assert.equal(secondary.total, 2);
  assert.equal(trash.total, 1);
  assert.equal(spam.total, 1);
  assert.ok(merged.conversations.every(item => item.conversation_scope === true));
  assert.deepEqual(new Set(merged.conversations.map(item => item.account_id)), new Set([9101, 9102]));
  await post('/api/emails/actions', actionPayload(301, 'archive', 1), 422);
  snapshot = await audit();
  assert.equal(snapshot.counters.protected_mailbox_rejections, 1);
  assert.equal(snapshot.counters.expected_mail_action_writes, 0);
  assertGeneratedBoundary(snapshot);
  results.datasets = snapshot.counters;

  // A response lost after the generated staged archive commits is recovered by
  // replaying the same idempotency key. The logical write occurs once, a
  // conflicting replay fails, and exact Undo restores the original Inbox row.
  await reset('lost-action-once');
  const archivePayload = actionPayload(101, 'archive', 2);
  await assert.rejects(rawRequest('POST', '/api/emails/actions', archivePayload));
  snapshot = await audit();
  assert.equal(snapshot.counters.mail_action_creates, 1);
  assert.equal(snapshot.counters.expected_mail_action_writes, 1);
  assert.equal(snapshot.counters.lost_action_responses, 1);
  assert.equal(snapshot.inbox_totals.primary, 3);
  const archive = await post('/api/emails/actions', archivePayload, 202);
  assert.equal(archive.action, 'archive');
  assert.equal(archive.state, 'staged');
  assert.equal(archive.accepted_count, 1);
  assert.ok(Date.parse(archive.undo_until) > Date.parse(archive.created_at));
  await post('/api/emails/actions', {
    ...archivePayload,
    action: 'star',
  }, 409);
  const undone = await post(`/api/emails/actions/${archive.request_id}/undo`, {});
  assert.equal(undone.state, 'cancelled');
  snapshot = await audit();
  assert.equal(snapshot.counters.mail_action_creates, 1);
  assert.equal(snapshot.counters.mail_action_replays, 1);
  assert.equal(snapshot.counters.mail_action_conflicts, 1);
  assert.equal(snapshot.counters.mail_action_undos, 1);
  assert.equal(snapshot.counters.expected_mail_action_writes, 2);
  assert.equal(snapshot.inbox_totals.primary, 4);
  assertGeneratedBoundary(snapshot);
  results.archive_replay_undo = snapshot.counters;

  // The alternate preference actions map onto the existing staged action
  // contract without introducing a new mutation API.
  await reset();
  await post('/api/emails/actions', actionPayload(103, 'mark_read', 3), 202);
  await post('/api/emails/actions', actionPayload(104, 'star', 4), 202);
  const readEmail = await get('/api/emails/103');
  const starredEmail = await get('/api/emails/104');
  assert.equal(readEmail.is_read, true);
  assert.equal(starredEmail.is_starred, true);
  snapshot = await audit();
  assert.equal(snapshot.counters.mail_action_creates, 2);
  assert.equal(snapshot.counters.expected_mail_action_writes, 2);
  assertGeneratedBoundary(snapshot);
  results.toggle_actions = snapshot.counters;

  // Merely fetching the row and opening client UI has no server write. Only an
  // explicit generated wake time creates one snooze plus its one staged local
  // archive. A lost response is recovered with the identical key.
  await reset('lost-snooze-once');
  await get('/api/emails/102');
  snapshot = await audit();
  assert.equal(snapshot.counters.expected_snooze_writes, 0);
  assert.equal(snapshot.counters.expected_mail_action_writes, 0);
  const reminderPayload = snoozePayload(102, 5);
  await assert.rejects(rawRequest('POST', '/api/snoozes', reminderPayload));
  const reminder = await post('/api/snoozes', reminderPayload, 202);
  assert.equal(reminder.email_id, 102);
  assert.equal(reminder.state, 'pending_archive');
  assert.equal(reminder.wake_at, '2026-09-01T14:00:00.000Z');
  snapshot = await audit();
  assert.equal(snapshot.counters.snooze_creates, 1);
  assert.equal(snapshot.counters.snooze_replays, 1);
  assert.equal(snapshot.counters.lost_snooze_responses, 1);
  assert.equal(snapshot.counters.expected_snooze_writes, 1);
  assert.equal(snapshot.counters.snooze_archive_action_writes, 1);
  assert.equal(snapshot.counters.mail_action_creates, 1);
  assert.equal(snapshot.inbox_totals.primary, 3);
  await post(`/api/snoozes/${reminder.id}/cancel`, {});
  snapshot = await audit();
  assert.equal(snapshot.counters.snooze_cancels, 1);
  assert.equal(snapshot.counters.expected_snooze_writes, 2);
  assert.equal(snapshot.inbox_totals.primary, 4);
  assertGeneratedBoundary(snapshot);
  results.snooze_explicit_commit = snapshot.counters;

  // A dataset response captured under a prior authenticated generation can
  // arrive late, but the fixture records no preference, mail-action, or snooze
  // write. The browser contract must discard it and clear selection.
  await reset('slow-dataset');
  const delayed = get('/api/emails/conversations?mailbox=INBOX&account_id=9101&page=1&page_size=50');
  await new Promise(resolve => setTimeout(resolve, 40));
  await post('/__qa/session', { current_user: 'anonymous' });
  const stalePayload = await delayed;
  assert.equal(stalePayload.total, 4);
  snapshot = await audit();
  assert.equal(snapshot.counters.dataset_delays, 1);
  assert.equal(snapshot.counters.stale_dataset_responses, 1);
  assert.equal(snapshot.counters.expected_preference_writes, 0);
  assert.equal(snapshot.counters.expected_mail_action_writes, 0);
  assert.equal(snapshot.counters.expected_snooze_writes, 0);
  assertGeneratedBoundary(snapshot);
  results.stale_session = snapshot.counters;

  process.stdout.write(`${JSON.stringify({
    ok: true,
    fixture: 'generated-touch-first-triage:v1',
    accounts: 2,
    default_swipes: ['archive', 'snooze'],
    alternate_swipes: ['toggle_read', 'toggle_star'],
    archive_exactly_once: true,
    undo_restores_exact_inbox: true,
    snooze_picker_precommit_writes: 0,
    protected_mailbox_writes: 0,
    stale_session_writes: 0,
    results,
  })}\n`);
} finally {
  await fixture.close();
}
