#!/usr/bin/env node

// Focused contract test for the generated-only Contact query/profile fixture.
// All data remains in memory on localhost under the reserved .example.test
// domain; the fixture has no provider or external-network capability.

import assert from 'node:assert/strict';

import {
  GENERATED_PROVIDER_DRAFT_HOST,
  createGeneratedProviderDraftFixture,
} from './generated_provider_draft_server.mjs';

const fixture = createGeneratedProviderDraftFixture();
const address = await fixture.listen(0);
const baseUrl = `http://${GENERATED_PROVIDER_DRAFT_HOST}:${address.port}`;

async function request(method, pathname, body, expectedStatus = 200) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  assert.equal(
    response.status,
    expectedStatus,
    `${method} ${pathname}: ${JSON.stringify(payload)}`,
  );
  if (pathname.startsWith('/api/contacts/')) {
    assert.match(response.headers.get('cache-control') || '', /no-store/i);
  }
  return payload;
}

const get = (pathname, expectedStatus = 200) => request(
  'GET',
  pathname,
  undefined,
  expectedStatus,
);
const post = (pathname, body = {}, expectedStatus = 200) => (
  request('POST', pathname, body, expectedStatus)
);

async function reset(scenario = 'clean', currentUser = 'generated-a') {
  return post('/api/qa/reset', { scenario, current_user: currentUser });
}

async function query(accountId, overrides = {}, expectedStatus = 200) {
  return post('/api/contacts/query', {
    account_id: accountId,
    query: '',
    relationship: 'all',
    page: 1,
    page_size: 50,
    ...overrides,
  }, expectedStatus);
}

async function profile(accountId, contactKey, overrides = {}, expectedStatus = 200) {
  return post('/api/contacts/profile', {
    account_id: accountId,
    contact_key: contactKey,
    recent_limit: 8,
    ...overrides,
  }, expectedStatus);
}

async function waitFor(predicate, message, timeoutMs = 1_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  assert.fail(message);
}

const QUERY_KEYS = [
  'account_id',
  'contacts',
  'coverage',
  'page',
  'page_size',
  'total',
  'total_pages',
].sort();
const SUMMARY_KEYS = [
  'account_id',
  'address',
  'contact_key',
  'formatted',
  'name',
  'observed_conversation_count',
  'observed_first_at',
  'observed_last_at',
  'observed_last_received_at',
  'observed_last_sent_at',
  'observed_message_count',
  'observed_received_count',
  'observed_sent_count',
  'relationship',
].sort();
const COVERAGE_KEYS = [
  'history_may_be_truncated',
  'observed_newest_at',
  'observed_oldest_at',
  'row_limit',
  'rows_scanned',
].sort();
const PROFILE_KEYS = ['account_id', 'contact', 'recent_conversations'].sort();
const RECENT_KEYS = [
  'account_id',
  'anchor_email_id',
  'direction',
  'observed_last_at',
  'observed_message_count',
  'thread_id',
].sort();
const FORBIDDEN_CONTENT_KEYS = new Set([
  'subject',
  'snippet',
  'body',
  'body_text',
  'body_html',
  'ai_summary',
  'attachments',
  'bcc',
  'bcc_addresses',
]);
const FORBIDDEN_SENTINELS = [
  'GENERATED_CONTACT_PRIVATE_SUBJECT_MUST_NOT_ESCAPE',
  'GENERATED_CONTACT_PRIVATE_BODY_MUST_NOT_ESCAPE',
  'bcc-only@example.test',
  'sender-a@example.test',
  'alternate-a@example.test',
  'draft-only@example.test',
  'spam-only@example.test',
  'trash-only@example.test',
  'User B Private',
  'user-b-contact@example.test',
];

function assertExactKeys(value, expected) {
  assert.deepEqual(Object.keys(value).sort(), expected);
}

function assertMetadataOnly(value) {
  function visit(item) {
    if (Array.isArray(item)) {
      item.forEach(visit);
      return;
    }
    if (!item || typeof item !== 'object') return;
    for (const [key, nested] of Object.entries(item)) {
      assert.equal(FORBIDDEN_CONTENT_KEYS.has(key), false, `forbidden content key: ${key}`);
      visit(nested);
    }
  }
  visit(value);
  const serialized = JSON.stringify(value);
  for (const sentinel of FORBIDDEN_SENTINELS) {
    assert.equal(serialized.includes(sentinel), false, `forbidden sentinel: ${sentinel}`);
  }
}

function assertReadOnlyAudit(snapshot) {
  assert.equal(snapshot.localhost_only, true);
  assert.deepEqual(snapshot.fixture_domains, ['example.test']);
  assert.equal(snapshot.counters.expected_mutations, 0);
  assert.equal(snapshot.counters.unexpected_mutations, 0);
  assert.equal(snapshot.counters.external_network_calls, 0);
  assert.equal(snapshot.counters.provider_draft_creates, 0);
  assert.equal(snapshot.counters.provider_draft_updates, 0);
  assert.equal(snapshot.counters.provider_sends, 0);
}

const results = {};

try {
  await reset();
  const primary = await query(1101);
  assertExactKeys(primary, QUERY_KEYS);
  assertExactKeys(primary.coverage, COVERAGE_KEYS);
  assert.equal(primary.account_id, 1101);
  assert.equal(primary.page, 1);
  assert.equal(primary.page_size, 50);
  assert.equal(primary.total, 4);
  assert.equal(primary.total_pages, 1);
  assert.equal(primary.coverage.rows_scanned, 7);
  assert.equal(primary.coverage.history_may_be_truncated, false);
  assert.deepEqual(primary.contacts.map(contact => contact.address), [
    'ada.profile@example.test',
    'outbound-only@example.test',
    'inbound-only@example.test',
    'shared@example.test',
  ]);
  primary.contacts.forEach(contact => {
    assertExactKeys(contact, SUMMARY_KEYS);
    assert.equal(contact.account_id, 1101);
    assert.match(contact.contact_key, /^[0-9a-f]{64}$/);
    assert.ok(['bidirectional', 'inbound_only', 'outbound_only'].includes(contact.relationship));
  });
  assertMetadataOnly(primary);

  const ada = primary.contacts.find(contact => contact.address === 'ada.profile@example.test');
  assert.ok(ada);
  assert.equal(ada.relationship, 'bidirectional');
  assert.equal(ada.observed_message_count, 2);
  assert.equal(ada.observed_received_count, 1);
  assert.equal(ada.observed_sent_count, 1);
  assert.equal(ada.observed_conversation_count, 1);
  const inboundOnly = await query(1101, { relationship: 'inbound_only' });
  assert.deepEqual(inboundOnly.contacts.map(contact => contact.address), [
    'inbound-only@example.test',
  ]);
  const outboundOnly = await query(1101, { relationship: 'outbound_only' });
  assert.deepEqual(new Set(outboundOnly.contacts.map(contact => contact.address)), new Set([
    'outbound-only@example.test',
    'shared@example.test',
  ]));

  const adaProfile = await profile(1101, ada.contact_key);
  assertExactKeys(adaProfile, PROFILE_KEYS);
  assertExactKeys(adaProfile.contact, SUMMARY_KEYS);
  assert.equal(adaProfile.account_id, 1101);
  assert.equal(adaProfile.contact.account_id, 1101);
  assert.equal(adaProfile.recent_conversations.length, 1);
  assertExactKeys(adaProfile.recent_conversations[0], RECENT_KEYS);
  assert.deepEqual(adaProfile.recent_conversations[0], {
    account_id: 1101,
    anchor_email_id: 1401,
    thread_id: 'generated-contact-ada-thread',
    observed_last_at: '2026-08-30T15:59:00.000Z',
    observed_message_count: 2,
    direction: 'bidirectional',
  });
  assertMetadataOnly(adaProfile);
  const recentPointer = adaProfile.recent_conversations[0];
  const contactThread = await get(
    `/api/emails/thread/${recentPointer.thread_id}?order=asc&account_id=${recentPointer.account_id}`,
  );
  assert.equal(contactThread.thread_id, recentPointer.thread_id);
  assert.deepEqual(contactThread.emails.map(email => email.id), [1402, 1401]);
  assert.ok(contactThread.emails.every(email => email.account_id === recentPointer.account_id));
  assert.ok(contactThread.emails.every(email => email.gmail_thread_id === recentPointer.thread_id));
  assert.ok(contactThread.emails.every(email => email.is_read === true));
  assert.ok(contactThread.emails.some(email => email.id === recentPointer.anchor_email_id));
  assert.equal(
    JSON.stringify(contactThread).includes('GENERATED_CONTACT_PRIVATE_SUBJECT_MUST_NOT_ESCAPE'),
    false,
  );
  assert.equal(
    JSON.stringify(contactThread).includes('GENERATED_CONTACT_PRIVATE_BODY_MUST_NOT_ESCAPE'),
    false,
  );
  await get(
    `/api/emails/thread/${recentPointer.thread_id}?order=asc&account_id=1102`,
    404,
  );
  await get(`/api/emails/thread/${recentPointer.thread_id}?order=asc`, 404);

  const alternate = await query(1102, { query: 'shared@example.test' });
  assert.equal(alternate.total, 1);
  const alternateShared = alternate.contacts[0];
  const primaryShared = primary.contacts.find(contact => contact.address === 'shared@example.test');
  assert.ok(primaryShared);
  assert.equal(alternateShared.account_id, 1102);
  assert.equal(alternateShared.relationship, 'inbound_only');
  assert.notEqual(alternateShared.contact_key, primaryShared.contact_key);
  const alternateAll = await query(1102);
  const alternateOnly = alternateAll.contacts.find(
    contact => contact.address === 'alternate-profile@example.test',
  );
  assert.ok(alternateOnly);
  const alternateProfile = await profile(1102, alternateOnly.contact_key);
  assert.equal(alternateProfile.recent_conversations[0].thread_id, null);
  assert.equal(alternateProfile.recent_conversations[0].anchor_email_id, 1502);
  const alternateMessage = await get('/api/emails/1502');
  assert.equal(alternateMessage.id, 1502);
  assert.equal(alternateMessage.account_id, 1102);
  assert.equal(alternateMessage.gmail_thread_id, null);
  assert.equal(alternateMessage.is_read, true);
  await profile(1101, alternateShared.contact_key, {}, 404);
  await query(1201, {}, 404);

  let snapshot = await get('/api/qa/audit');
  assert.equal(snapshot.counters.contact_handoff_thread_reads, 1);
  assert.equal(snapshot.counters.contact_handoff_message_reads, 1);
  assert.equal(snapshot.counters.contact_handoff_rejections, 2);
  assertReadOnlyAudit(snapshot);

  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  const userB = await query(1201, { query: 'shared@example.test' });
  assert.equal(userB.total, 1);
  assert.equal(userB.contacts[0].account_id, 1201);
  assert.notEqual(userB.contacts[0].contact_key, primaryShared.contact_key);
  assert.notEqual(userB.contacts[0].contact_key, alternateShared.contact_key);
  assert.equal(JSON.stringify(userB).includes('Shared Primary Relationship'), false);
  assert.equal(JSON.stringify(userB).includes('Shared Alternate Relationship'), false);
  await get('/api/emails/thread/generated-contact-ada-thread?account_id=1101', 404);
  await get('/api/emails/1401', 404);
  results.isolation = true;

  await reset();
  await post('/api/auth/logout');
  await query(1101, {}, 401);
  await profile(1101, ada.contact_key, {}, 401);
  results.unauthorized = true;

  await reset('contact-delay');
  await query(1101);
  await profile(1101, ada.contact_key);
  snapshot = await get('/api/qa/audit');
  assert.equal(snapshot.counters.contact_query_delays, 1);
  assert.equal(snapshot.counters.contact_profile_delays, 1);
  assert.equal(snapshot.counters.contact_query_successes, 1);
  assert.equal(snapshot.counters.contact_profile_successes, 1);
  assertReadOnlyAudit(snapshot);
  results.delay = true;

  await reset('contact-fails');
  await query(1101, {}, 503);
  await profile(1101, ada.contact_key, {}, 503);
  snapshot = await get('/api/qa/audit');
  assert.deepEqual(snapshot.allowed_contact_routes, [
    'POST /api/contacts/query',
    'POST /api/contacts/profile',
    'GET /api/emails/thread/{thread_id}',
    'GET /api/emails/{anchor_email_id}',
  ]);
  assert.equal(snapshot.counters.contact_query_failures, 1);
  assert.equal(snapshot.counters.contact_profile_failures, 1);
  assertReadOnlyAudit(snapshot);
  results.failure = true;

  await reset('contact-held-session');
  const heldQuery = query(1101, { query: 'ada' });
  await waitFor(async () => {
    const pending = await get('/api/qa/audit');
    return pending.counters.contact_query_held === 1;
  }, 'contact query was not held');
  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  const release = await post('/api/qa/release-held');
  assert.equal(release.released, 1);
  const stalePayload = await heldQuery;
  assert.equal(stalePayload.account_id, 1101);
  assert.equal(stalePayload.contacts[0].address, 'ada.profile@example.test');
  snapshot = await get('/api/qa/audit');
  assert.equal(snapshot.current_user_id, 9102);
  assert.equal(snapshot.counters.contact_query_stale_session_responses, 1);
  assert.equal(snapshot.counters.stale_session_responses_released, 1);
  assert.equal(snapshot.counters.external_network_calls, 0);
  assert.equal(snapshot.counters.unexpected_mutations, 0);
  results.stale_session = true;

  await reset();
  const finalQuery = await query(1101, { query: 'ada' });
  await profile(1101, finalQuery.contacts[0].contact_key);
  snapshot = await get('/api/qa/audit');
  assert.equal(snapshot.counters.contact_query_requests, 1);
  assert.equal(snapshot.counters.contact_query_successes, 1);
  assert.equal(snapshot.counters.contact_profile_requests, 1);
  assert.equal(snapshot.counters.contact_profile_successes, 1);
  assert.equal(snapshot.counters.contact_query_failures, 0);
  assert.equal(snapshot.counters.contact_profile_failures, 0);
  assertReadOnlyAudit(snapshot);
  results.read_only_counters = true;

  process.stdout.write(`${JSON.stringify({ passed: true, cases: results })}\n`);
} finally {
  await fixture.close();
}
