#!/usr/bin/env node

// Focused contract and safety test for the localhost-only generated Share
// Availability fixture. No frontend, provider, mailbox, production
// configuration, or external network is involved.

import assert from 'node:assert/strict';

import {
  GENERATED_SHARE_AVAILABILITY_HOST,
  createGeneratedShareAvailabilityFixture,
} from './generated_share_availability_server.mjs';

const fixture = createGeneratedShareAvailabilityFixture();
const address = await fixture.listen(0);
const baseUrl = `http://${GENERATED_SHARE_AVAILABILITY_HOST}:${address.port}`;

async function request(method, pathname, body, expectedStatus = 200) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const bytes = Buffer.from(await response.arrayBuffer());
  assert.equal(response.status, expectedStatus, `${method} ${pathname}: ${bytes.toString('utf8')}`);
  if (pathname.startsWith('/api/') || pathname.startsWith('/__qa/')) {
    assert.match(response.headers.get('cache-control') || '', /no-store/i);
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  }
  const contentType = response.headers.get('content-type') || '';
  return {
    response,
    bytes,
    payload: contentType.includes('application/json')
      ? JSON.parse(bytes.toString('utf8'))
      : null,
  };
}

const get = async (pathname, expectedStatus = 200) => (
  (await request('GET', pathname, undefined, expectedStatus)).payload
);
const post = async (pathname, body, expectedStatus = 200) => (
  (await request('POST', pathname, body, expectedStatus)).payload
);

function availabilityRequest(overrides = {}) {
  return {
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
    ...overrides,
  };
}

async function availability(overrides = {}, expectedStatus = 200) {
  return post('/api/calendar/availability', availabilityRequest(overrides), expectedStatus);
}

async function reset(scenario = 'ready', currentUser = 'generated-a') {
  return post('/__qa/reset', { scenario, current_user: currentUser });
}

function exactKeys(value, expected) {
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort());
}

function assertGeneratedAddresses(value) {
  const serialized = JSON.stringify(value);
  const addresses = serialized.match(/[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+/giu) || [];
  assert.ok(addresses.every(address => address.toLowerCase().endsWith('@example.test')), addresses);
}

function assertNoCalendarContentLeak(value) {
  const serialized = JSON.stringify(value);
  for (const sentinel of [
    'GENERATED_PRIVATE_EVENT_TITLE_MUST_NOT_ESCAPE',
    'GENERATED_PRIVATE_EVENT_DESCRIPTION_MUST_NOT_ESCAPE',
    'GENERATED_SECOND_PRIVATE_TITLE_MUST_NOT_ESCAPE',
    'generated-attendee@example.test',
    'generated-organizer@example.test',
  ]) {
    assert.equal(serialized.includes(sentinel), false, `calendar content leaked: ${sentinel}`);
  }
  for (const forbiddenKey of ['summary', 'description', 'location', 'attendees', 'organizer_email']) {
    assert.equal(Object.hasOwn(value, forbiddenKey), false, `forbidden availability key: ${forbiddenKey}`);
  }
}

function assertNoExecutedSideEffects(audit) {
  assert.equal(audit.localhost_only, true);
  assert.deepEqual(audit.fixture_domains, ['example.test']);
  for (const counter of [
    'provider_reads',
    'provider_calls',
    'provider_writes',
    'email_sends',
    'mail_mutations',
    'calendar_writes',
    'event_creations',
    'event_holds',
    'external_network_calls',
  ]) assert.equal(audit.counters[counter], 0, `${counter} must remain zero`);
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 1_500;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await new Promise(resolveWait => setTimeout(resolveWait, 5));
  }
  assert.fail(message);
}

const results = {};

try {
  await reset();
  const me = await get('/api/auth/me');
  assert.deepEqual(me, {
    id: 7301,
    username: 'availability-user-a@example.test',
    is_admin: false,
  });
  const accounts = await get('/api/accounts/');
  assert.deepEqual(accounts.map(account => account.id), [1, 2]);
  assert.deepEqual(accounts.map(account => account.email), ['owner@example.test', 'projects@example.test']);
  assert.ok(accounts.every(account => account.has_calendar_scope === true));
  assert.deepEqual(await get('/api/saved-views'), { items: [], max_views: 12 });

  const statuses = await get('/api/calendar/sync-status');
  assert.deepEqual(statuses.map(status => status.account_id), [1, 2]);
  assert.ok(statuses.every(status => status.status === 'idle' && status.needs_reauth === false));
  const events = await get('/api/calendar/events?start=2026-09-01&end=2026-09-08&tz=America%2FNew_York');
  assert.equal(events.total, 2);
  assert.ok(JSON.stringify(events).includes('GENERATED_PRIVATE_EVENT_TITLE_MUST_NOT_ESCAPE'));
  assertGeneratedAddresses({ me, accounts, statuses, events });

  const ready = await availability();
  exactKeys(ready, ['ready', 'generated_at', 'timezone', 'duration_minutes', 'coverage', 'slots']);
  assert.equal(ready.ready, true);
  assert.equal(ready.generated_at, '2026-08-31T16:00:00.000Z');
  assert.equal(ready.timezone, 'America/New_York');
  assert.equal(ready.duration_minutes, 30);
  assert.deepEqual(ready.coverage.map(item => item.account_id), [1, 2]);
  assert.deepEqual(ready.coverage.map(item => item.account_email), ['owner@example.test', 'projects@example.test']);
  assert.ok(ready.coverage.every(item => item.state === 'ready' && item.last_success_at));
  ready.coverage.forEach(item => exactKeys(item, ['account_id', 'account_email', 'state', 'last_success_at']));
  assert.equal(ready.slots.length, 3);
  ready.slots.forEach(slot => {
    exactKeys(slot, ['start', 'end']);
    assert.equal((Date.parse(slot.end) - Date.parse(slot.start)) / 60_000, 30);
  });
  assertNoCalendarContentLeak(ready);
  assertGeneratedAddresses(ready);

  const singleAccount = await availability({ account_ids: [1], duration_minutes: 60 });
  assert.equal(singleAccount.ready, true);
  assert.deepEqual(singleAccount.coverage.map(item => item.account_id), [1]);
  singleAccount.slots.forEach(slot => {
    assert.equal((Date.parse(slot.end) - Date.parse(slot.start)) / 60_000, 60);
  });
  results.ready_contract = true;
  results.account_slot_selection = true;
  results.calendar_content_redacted = true;

  await availability({ account_ids: [1, 1] }, 422);
  await availability({ account_ids: [1, 3] }, 404);
  await availability({ duration_minutes: 20 }, 422);
  await availability({ step_minutes: 20 }, 422);
  await availability({ day_start: '05:45' }, 422);
  await availability({ day_end: '22:15' }, 422);
  await availability({ timezone: 'Not/AZone' }, 422);
  await availability({ end_date: '2026-09-21' }, 422);
  await post('/api/calendar/availability', {
    ...availabilityRequest(),
    unexpected: true,
  }, 422);
  results.strict_request_validation = true;

  const scenarioStates = {
    stale: 'stale',
    'reauthorization-required': 'reauthorization_required',
    'calendar-not-enabled': 'calendar_not_enabled',
    'no-full': 'sync_incomplete',
    'sync-error': 'sync_error',
    syncing: 'syncing',
  };
  for (const [scenario, state] of Object.entries(scenarioStates)) {
    await reset(scenario);
    const incomplete = await availability();
    assert.equal(incomplete.ready, false, scenario);
    assert.deepEqual(incomplete.slots, [], scenario);
    assert.equal(incomplete.coverage.find(item => item.account_id === 2)?.state, state, scenario);
    assertNoCalendarContentLeak(incomplete);
    const audit = await get('/__qa/audit');
    assert.equal(audit.counters.incomplete_coverage_responses, 1);
    assertNoExecutedSideEffects(audit);
  }
  results.incomplete_coverage_states = Object.keys(scenarioStates);

  await reset('fail-once');
  await availability({}, 503);
  const retried = await availability();
  assert.equal(retried.ready, true);
  let audit = await get('/__qa/audit');
  assert.equal(audit.counters.availability_requests, 2);
  assert.equal(audit.counters.transient_failures, 1);
  assert.equal(audit.counters.availability_successes, 1);
  assertNoExecutedSideEffects(audit);
  results.fail_once_retry = true;

  await reset('held');
  const heldResponse = availability();
  await waitFor(async () => {
    const current = await get('/__qa/audit');
    return current.pending_held_requests === 1 ? current : null;
  }, 'availability request was not held');
  await post('/__qa/session', { current_user: 'generated-b' });
  const release = await post('/__qa/release', {});
  assert.deepEqual(release, { released: 1 });
  const capturedResponse = await heldResponse;
  assert.deepEqual(capturedResponse.coverage.map(item => item.account_id), [1, 2]);
  assert.equal((await get('/api/auth/me')).username, 'availability-user-b@example.test');
  assert.deepEqual((await get('/api/accounts/')).map(account => account.id), [3]);
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.held_availability_requests, 1);
  assert.equal(audit.counters.released_held_requests, 1);
  assert.equal(audit.counters.stale_session_responses, 1);
  assertNoExecutedSideEffects(audit);
  results.held_session_capture = true;

  await reset('slow-session');
  const slowResponse = availability();
  await new Promise(resolveWait => setTimeout(resolveWait, 60));
  await post('/__qa/session', { current_user: 'generated-b' });
  const slowCaptured = await slowResponse;
  assert.deepEqual(slowCaptured.coverage.map(item => item.account_id), [1, 2]);
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.slow_availability_requests, 1);
  assert.equal(audit.counters.stale_session_responses, 1);
  assertNoExecutedSideEffects(audit);
  results.slow_session_capture = true;

  await reset();
  const draftId = '9ae7092b-aeb7-4f9e-a775-30dc1b8dfa2f';
  const draftPayload = {
    client_draft_id: draftId,
    mutation_id: 'generated-availability-draft-mutation-1',
    revision: 1,
    account_id: 1,
    source_email_id: 101,
    to: [{ name: 'Generated Scheduling Requester', address: 'requester@example.test' }],
    cc: [],
    bcc: [],
    subject: 'Re: Generated request for meeting times',
    body_text: 'Before caret.\n\nAvailability snapshot\nGenerated time only.\n\nAfter caret.',
    body_html: '<p>Before caret.</p><div><strong>Availability snapshot</strong></div><p>After caret.</p>',
    attachments: [],
  };
  const savedDraft = await post('/api/compose/draft', draftPayload, 202);
  assert.equal(savedDraft.client_draft_id, draftId);
  assert.equal(savedDraft.state, 'synced');
  assert.equal(savedDraft.revision, 1);
  assert.equal(savedDraft.synced_revision, 1);
  assert.equal(savedDraft.body_text, draftPayload.body_text);
  const lookedUp = await get(`/api/compose/drafts/by-client-id/${draftId}`);
  assert.equal(lookedUp.body_text, draftPayload.body_text);
  assert.equal((await get('/api/compose/drafts/recent')).length, 1);
  await post(`/api/compose/drafts/${draftId}/discard`, { mutation_id: 'generated-discard-1' }, 202);
  await post(`/api/compose/drafts/${draftId}/undo-discard`, { mutation_id: 'generated-undo-1' }, 202);
  await post('/api/compose/draft', {
    ...draftPayload,
    client_draft_id: 'a811fcbf-1dc0-45c8-a648-d8b707e0585b',
    mutation_id: 'generated-invalid-address',
    to: [{ address: 'private.person@example.invalid' }],
  }, 422);
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.allowed_draft_writes, 3);
  assert.equal(audit.counters.non_generated_rejections, 1);
  assertNoExecutedSideEffects(audit);
  results.generated_draft_writes_only = true;

  await post('/api/compose/send', {
    account_id: 1,
    to: [{ address: 'requester@example.test' }],
    subject: 'Generated send rejection',
    body_text: 'Must not send',
  }, 405);
  await post('/api/calendar/sync', {}, 405);
  await post('/api/calendar/events', {
    summary: 'Generated event creation must be rejected',
  }, 405);
  await post('/api/calendar/holds', {
    start: '2026-09-01T10:30:00-04:00',
  }, 405);
  await post('/api/emails/actions', {
    email_ids: [101],
    action: 'archive',
  }, 405);
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.rejected_email_send_attempts, 1);
  assert.equal(audit.counters.rejected_calendar_write_attempts, 3);
  assert.equal(audit.counters.rejected_event_creation_attempts, 1);
  assert.equal(audit.counters.rejected_event_hold_attempts, 1);
  assert.equal(audit.counters.rejected_mail_mutation_attempts, 1);
  assert.equal(audit.counters.rejected_provider_action_attempts, 2);
  assertNoExecutedSideEffects(audit);
  results.rejected_side_effect_attempts = true;

  await reset('ready', 'anonymous');
  await get('/api/auth/me', 401);
  await availability({}, 401);
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.auth_rejections, 2);
  assertNoExecutedSideEffects(audit);
  results.auth_required = true;

  process.stdout.write(`${JSON.stringify({
    generated_only: true,
    ...results,
    no_email_send_provider_calendar_event_or_external_side_effects: true,
  }, null, 2)}\n`);
} finally {
  await fixture.close();
}
