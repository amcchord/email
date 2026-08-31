#!/usr/bin/env node

// Generated-only contract test for user-trainable Focused/Other rules. The
// fixture is imported directly, binds to loopback on an ephemeral port, and
// has no provider, Gmail, mail, calendar, AI, worker, or terminal client.

import assert from 'node:assert/strict';

import { createGeneratedInboxRulesFixture } from './generated_inbox_rules_server.mjs';

const fixture = createGeneratedInboxRulesFixture();
const address = await fixture.listen(0);
const baseUrl = `http://127.0.0.1:${address.port}`;
const CREATE_IDS = Object.freeze({
  domain: '10000000-0000-4000-8000-000000000001',
  sender: '10000000-0000-4000-8000-000000000002',
  conversation: '10000000-0000-4000-8000-000000000003',
  undo: '10000000-0000-4000-8000-000000000004',
  retry: '10000000-0000-4000-8000-000000000005',
});
const RULE_KEYS = [
  'account_email',
  'account_id',
  'created_at',
  'display_value',
  'enabled',
  'id',
  'placement',
  'revision',
  'scope',
  'updated_at',
].sort();
const ZERO_OPERATION_COUNTERS = [
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
];

async function request(method, pathname, body, expectedStatus = 200) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  assert.equal(response.status, expectedStatus, `${method} ${pathname}: ${text}`);
  if (pathname.startsWith('/api/inbox-placement-rules')) {
    assert.match(response.headers.get('cache-control') || '', /private.*no-store/iu);
  }
  return payload;
}

const get = (path, expected = 200) => request('GET', path, undefined, expected);
const post = (path, body, expected = 200) => request('POST', path, body, expected);
const put = (path, body, expected = 200) => request('PUT', path, body, expected);
const remove = (path, expected = 204) => request('DELETE', path, undefined, expected);

async function reset(scenario = 'ready', currentUser = 'generated-a') {
  return post('/__qa/reset', { scenario, current_user: currentUser });
}

function candidatePath(accountId, emailId) {
  return `/api/inbox-placement-rules/candidate?account_id=${accountId}&anchor_email_id=${emailId}`;
}

function createPayload({ createId, accountId = 1, emailId, scope, placement, expectedRevision = 0 }) {
  return {
    create_id: createId,
    account_id: accountId,
    anchor_email_id: emailId,
    scope,
    placement,
    enabled: true,
    expected_revision: expectedRevision,
  };
}

function assertRule(rule, expected = {}) {
  assert.deepEqual(Object.keys(rule).sort(), RULE_KEYS);
  assert.match(rule.id, /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu);
  assert.ok(Number.isSafeInteger(rule.account_id) && rule.account_id > 0);
  assert.ok(Number.isSafeInteger(rule.revision) && rule.revision > 0);
  assert.ok(Number.isFinite(Date.parse(rule.created_at)));
  assert.ok(Number.isFinite(Date.parse(rule.updated_at)));
  for (const [key, value] of Object.entries(expected)) assert.equal(rule[key], value);
}

function rowById(split, emailId) {
  return [...split.focused.conversations, ...split.other.conversations]
    .find(row => row.anchor_email_id === emailId);
}

function assertTotals(split, focused, other) {
  assert.equal(split.focused.total, focused);
  assert.equal(split.other.total, other);
  assert.equal(split.total, focused + other);
}

function assertNoExternalOperations(audit) {
  for (const counter of ZERO_OPERATION_COUNTERS) {
    assert.equal(audit.counters[counter], 0, `${counter} must remain zero`);
  }
  assert.equal(audit.counters.unexpected_writes, 0);
}

try {
  await reset();
  const me = await get('/api/auth/me');
  assert.equal(me.username, 'focused-rules-owner@example.test');
  assert.deepEqual((await get('/api/accounts/')).map(account => account.id), [1, 2]);

  const initial = await get('/api/emails/conversations/split?page=1&page_size=20');
  assertTotals(initial, 4, 2);
  assert.equal(rowById(initial, 101).inbox_placement_source, 'system');

  const candidate = await get(candidatePath(1, 101));
  assert.deepEqual(Object.keys(candidate).sort(), [
    'account_email',
    'account_id',
    'anchor_email_id',
    'conversation_label',
    'rules',
    'sender_address',
    'sender_domain',
  ]);
  assert.equal(candidate.account_email, 'focused-primary@example.test');
  assert.equal(candidate.sender_address, 'alex@sender.example.test');
  assert.equal(candidate.sender_domain, 'sender.example.test');
  assert.deepEqual(candidate.rules, []);
  assert.equal((await get('/__qa/audit')).counters.expected_rule_writes, 0, 'candidate/Cancel path wrote state');

  const domain = await post('/api/inbox-placement-rules', createPayload({
    createId: CREATE_IDS.domain,
    emailId: 103,
    scope: 'domain',
    placement: 'other',
  }), 201);
  assertRule(domain, { account_id: 1, scope: 'domain', display_value: 'sender.example.test', placement: 'other', revision: 1 });
  assert.deepEqual(await post('/api/inbox-placement-rules', createPayload({
    createId: CREATE_IDS.domain,
    emailId: 103,
    scope: 'domain',
    placement: 'other',
  })), domain, 'lost-create replay must be idempotent');
  let split = await get('/api/emails/conversations/split?page=1&page_size=20');
  assertTotals(split, 1, 5);
  assert.equal(rowById(split, 104).inbox_placement_source, 'system', 'an exact domain rule must not match a subdomain');
  assert.equal(rowById(split, 104).inbox_placement_rule_scope, null);
  assert.equal(rowById(split, 201).inbox_placement_source, 'system', 'the same sender in account two must not match');

  const sender = await post('/api/inbox-placement-rules', createPayload({
    createId: CREATE_IDS.sender,
    emailId: 101,
    scope: 'sender',
    placement: 'focused',
  }), 201);
  assertRule(sender, { scope: 'sender', placement: 'focused' });
  split = await get('/api/emails/conversations/split?page=1&page_size=20');
  assertTotals(split, 3, 3);
  assert.equal(rowById(split, 102).inbox_placement_rule_scope, 'sender');

  const conversation = await post('/api/inbox-placement-rules', createPayload({
    createId: CREATE_IDS.conversation,
    emailId: 101,
    scope: 'conversation',
    placement: 'other',
  }), 201);
  assertRule(conversation, { scope: 'conversation', display_value: 'Generated priority proposal', placement: 'other' });
  split = await get('/api/emails/conversations/split?page=1&page_size=20');
  assertTotals(split, 2, 4);
  assert.equal(rowById(split, 101).inbox_placement_rule_scope, 'conversation');
  assert.equal(rowById(split, 101).inbox_placement_reason, 'user_rule_other');
  assert.equal(rowById(split, 102).inbox_placement_rule_scope, 'sender');
  assert.equal(rowById(split, 103).inbox_placement_rule_scope, 'domain');

  const reloaded = await get('/api/emails/conversations/split?page=1&page_size=20');
  assertTotals(reloaded, 2, 4);
  const ledger = await get('/api/inbox-placement-rules');
  assert.equal(ledger.max_rules_per_account, 500);
  assert.equal(ledger.items.length, 3);
  ledger.items.forEach(rule => assertRule(rule));
  assert.equal((await get('/api/inbox-placement-rules?account_id=2')).items.length, 0);

  const domainFocused = await put(`/api/inbox-placement-rules/${domain.id}`, {
    placement: 'focused', enabled: true, revision: domain.revision,
  });
  assertRule(domainFocused, { placement: 'focused', revision: 2 });
  assert.deepEqual(await put(`/api/inbox-placement-rules/${domain.id}`, {
    placement: 'focused', enabled: true, revision: domain.revision,
  }), domainFocused, 'lost-update replay must be idempotent');
  const domainDisabled = await put(`/api/inbox-placement-rules/${domain.id}`, {
    placement: 'focused', enabled: false, revision: domainFocused.revision,
  });
  assertRule(domainDisabled, { enabled: false, revision: 3 });
  split = await get('/api/emails/conversations/split?page=1&page_size=20');
  assert.equal(rowById(split, 103).inbox_placement_source, 'system', 'disabled rule must fall back to system placement');

  await remove(`/api/inbox-placement-rules/${conversation.id}?revision=${conversation.revision}`);
  split = await get('/api/emails/conversations/split?page=1&page_size=20');
  assert.equal(rowById(split, 101).inbox_placement_rule_scope, 'sender');
  assert.equal((await get('/api/inbox-placement-rules')).items.length, 2);
  assertNoExternalOperations(await get('/__qa/audit'));

  await reset();
  const undoRule = await post('/api/inbox-placement-rules', createPayload({
    createId: CREATE_IDS.undo,
    emailId: 101,
    scope: 'conversation',
    placement: 'other',
  }), 201);
  assertTotals(await get('/api/emails/conversations/split?page=1&page_size=20'), 3, 3);
  await remove(`/api/inbox-placement-rules/${undoRule.id}?revision=${undoRule.revision}`);
  assertTotals(await get('/api/emails/conversations/split?page=1&page_size=20'), 4, 2);
  assert.equal((await get('/api/inbox-placement-rules')).items.length, 0);

  await reset('conflict-once');
  const retryPayload = createPayload({
    createId: CREATE_IDS.retry,
    emailId: 101,
    scope: 'sender',
    placement: 'other',
  });
  await post('/api/inbox-placement-rules', retryPayload, 409);
  const retried = await post('/api/inbox-placement-rules', retryPayload, 201);
  assertRule(retried, { scope: 'sender', placement: 'other' });

  await reset('fail-once');
  await get(candidatePath(1, 101), 503);
  assert.equal((await get(candidatePath(1, 101))).anchor_email_id, 101);
  await post('/__qa/scenario', { scenario: 'error' });
  await get('/api/inbox-placement-rules', 503);
  await post('/__qa/scenario', { scenario: 'ready' });
  assert.equal((await get('/api/inbox-placement-rules')).items.length, 0);

  await reset('slow-session');
  const delayedCandidate = get(candidatePath(1, 101));
  await new Promise(resolve => setTimeout(resolve, 50));
  await post('/__qa/session', { current_user: 'anonymous' });
  const capturedCandidate = await delayedCandidate;
  assert.equal(capturedCandidate.account_id, 1, 'delayed response must retain captured account provenance');
  let audit = await get('/__qa/audit');
  assert.equal(audit.counters.stale_session_responses, 1);
  assert.equal(audit.requests.at(-1).captured_user, 'generated-a');
  assertNoExternalOperations(audit);

  await reset();
  await get(candidatePath(2, 101), 404);
  await get('/api/inbox-placement-rules?account_id=999', 404);
  await post('/api/inbox-placement-rules', createPayload({
    createId: '10000000-0000-4000-8000-000000000006',
    accountId: 2,
    emailId: 101,
    scope: 'sender',
    placement: 'other',
  }), 404);
  await post('/api/inbox-placement-rules', {
    ...createPayload({
      createId: '10000000-0000-4000-8000-000000000007',
      emailId: 101,
      scope: 'sender',
      placement: 'other',
    }),
    note: 'not-generated@invalid.example',
  }, 422);
  await post('/__qa/session', { current_user: 'anonymous' });
  await get('/api/inbox-placement-rules', 401);
  await post('/__qa/session', { current_user: 'generated-a' });
  audit = await get('/__qa/audit');
  assert.equal(audit.generated_only, true);
  assert.equal(audit.localhost_only, true);
  assert.deepEqual(audit.fixture_domains, ['example.test']);
  assert.equal(audit.counters.ownership_rejections, 3);
  assert.equal(audit.counters.non_generated_rejections, 1);
  assert.equal(audit.counters.auth_rejections, 1);
  assertNoExternalOperations(audit);
  assert.equal(JSON.stringify(audit).includes('generated-focused-thread'), false, 'raw provider thread identity leaked into audit');

  process.stdout.write(`${JSON.stringify({
    generated_only: true,
    loopback_only: true,
    exact_accounts: [1, 2],
    scopes: ['conversation', 'sender', 'domain'],
    precedence: ['conversation', 'sender', 'exact-domain', 'system'],
    cross_account_isolation: true,
    subdomain_non_match: true,
    reload_persistence: true,
    immediate_undo_contract: true,
    revision_conflict_and_retry: true,
    slow_session_capture: true,
    zero_provider_gmail_mail_calendar_ai_worker_terminal_operations: true,
  }, null, 2)}\n`);
} finally {
  await fixture.close();
}
