#!/usr/bin/env node

// Focused contract and safety test for the localhost-only generated
// Attachments workspace fixture. No frontend, provider, mailbox, production
// configuration, or external network is involved.

import assert from 'node:assert/strict';

import {
  GENERATED_ATTACHMENTS_HOST,
  createGeneratedAttachmentsFixture,
} from './generated_attachments_server.mjs';

const fixture = createGeneratedAttachmentsFixture();
const address = await fixture.listen(0);
const baseUrl = `http://${GENERATED_ATTACHMENTS_HOST}:${address.port}`;

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

const ITEM_KEYS = [
  'account_id',
  'attachment_id',
  'content_type',
  'email_id',
  'filename',
  'is_sent',
  'message_date',
  'sender_address',
  'sender_name',
  'size_bytes',
  'subject',
].sort();
const RESPONSE_KEYS = ['account_id', 'has_more', 'items', 'next_cursor'].sort();
const FORBIDDEN_KEYS = new Set([
  'bcc',
  'bcc_addresses',
  'body',
  'body_html',
  'body_text',
  'content_id',
  'gmail_attachment_id',
  'gmail_message_id',
  'raw_headers',
  'snippet',
  'storage_path',
  'to_addresses',
  'cc_addresses',
]);
const FORBIDDEN_SENTINELS = [
  'GENERATED_DRAFT_ATTACHMENT_MUST_NOT_ESCAPE',
  'GENERATED_SPAM_ATTACHMENT_MUST_NOT_ESCAPE',
  'GENERATED_TRASH_ATTACHMENT_MUST_NOT_ESCAPE',
  'GENERATED_INLINE_ATTACHMENT_MUST_NOT_ESCAPE',
  'generated-bcc-private@example.test',
];

function queryBody(accountId, overrides = {}) {
  return {
    account_id: accountId,
    query: '',
    kind: 'all',
    direction: 'all',
    cursor: null,
    page_size: 50,
    ...overrides,
  };
}

async function query(accountId, overrides = {}, expectedStatus = 200) {
  return post('/api/attachments/query', queryBody(accountId, overrides), expectedStatus);
}

async function reset(scenario = 'normal', currentUser = 'generated-a') {
  return post('/__qa/reset', { scenario, current_user: currentUser });
}

function assertExactKeys(value, expectedKeys) {
  assert.deepEqual(Object.keys(value).sort(), expectedKeys);
}

function assertMetadataOnly(value) {
  function visit(item) {
    if (Array.isArray(item)) {
      item.forEach(visit);
      return;
    }
    if (!item || typeof item !== 'object') return;
    for (const [key, nested] of Object.entries(item)) {
      assert.equal(FORBIDDEN_KEYS.has(key), false, `forbidden key escaped: ${key}`);
      visit(nested);
    }
  }
  visit(value);
  const serialized = JSON.stringify(value);
  for (const sentinel of FORBIDDEN_SENTINELS) {
    assert.equal(serialized.includes(sentinel), false, `forbidden sentinel escaped: ${sentinel}`);
  }
}

function assertItem(item, accountId) {
  assertExactKeys(item, ITEM_KEYS);
  assert.equal(item.account_id, accountId);
  assert.ok(Number.isSafeInteger(item.attachment_id) && item.attachment_id > 0);
  assert.ok(Number.isSafeInteger(item.email_id) && item.email_id > 0);
  assert.equal(typeof item.filename, 'string');
  assert.ok(item.filename.length > 0);
  assert.equal(typeof item.content_type, 'string');
  assert.ok(item.content_type.length > 0);
  assert.ok(item.size_bytes === null || (Number.isSafeInteger(item.size_bytes) && item.size_bytes >= 0));
  assert.ok(item.message_date === null || Number.isFinite(Date.parse(item.message_date)));
  assert.ok(item.sender_name === null || typeof item.sender_name === 'string');
  assert.ok(item.sender_address === null || item.sender_address.endsWith('@example.test'));
  assert.ok(item.subject === null || typeof item.subject === 'string');
  assert.equal(typeof item.is_sent, 'boolean');
}

function assertZeroExternalAndWrites(audit) {
  assert.equal(audit.localhost_only, true);
  assert.deepEqual(audit.fixture_domains, ['example.test']);
  assert.equal(audit.counters.provider_reads, 0);
  assert.equal(audit.counters.provider_writes, 0);
  assert.equal(audit.counters.mail_mutations, 0);
  assert.equal(audit.counters.calendar_mutations, 0);
  assert.equal(audit.counters.unexpected_writes, 0);
  assert.equal(audit.counters.external_network_calls, 0);
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 1_000;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  assert.fail(message);
}

const results = {};

try {
  await reset();

  const me = await get('/api/auth/me');
  assert.deepEqual(me, {
    id: 7101,
    username: 'attachments-user-a@example.test',
    is_admin: false,
  });
  const accounts = await get('/api/accounts/');
  assert.deepEqual(accounts.map(account => account.id), [8101, 8102]);
  assert.ok(accounts.every(account => account.email.endsWith('@example.test')));

  const firstPage = await query(8101, { page_size: 2 });
  assertExactKeys(firstPage, RESPONSE_KEYS);
  assert.equal(firstPage.account_id, 8101);
  assert.equal(firstPage.items.length, 2);
  assert.equal(firstPage.has_more, true);
  assert.equal(typeof firstPage.next_cursor, 'string');
  firstPage.items.forEach(item => assertItem(item, 8101));
  assert.deepEqual(firstPage.items.map(item => item.attachment_id), [9101, 9102]);
  assertMetadataOnly(firstPage);

  const secondPage = await query(8101, {
    cursor: firstPage.next_cursor,
    page_size: 2,
  });
  assert.deepEqual(secondPage.items.map(item => item.attachment_id), [9103, 9104]);
  assert.equal(secondPage.next_cursor, null);
  assert.equal(secondPage.has_more, false);

  const imageOnly = await query(8101, { kind: 'image' });
  assert.equal(imageOnly.items.length, 1);
  assert.equal(imageOnly.items[0].attachment_id, 9102);
  assert.equal(imageOnly.items[0].filename, '<img src=x onerror=generated-attachment-qa>.png');
  assert.equal(imageOnly.items[0].sender_name, '<svg onload=generated-attachment-sender>');
  assert.equal(imageOnly.items[0].subject, '<script>generated attachment subject</script>');

  const sentOnly = await query(8101, { direction: 'sent' });
  assert.deepEqual(sentOnly.items.map(item => item.attachment_id), [9103]);
  assert.equal(sentOnly.items[0].is_sent, true);
  const searched = await query(8101, { query: 'quarterly' });
  assert.deepEqual(searched.items.map(item => item.attachment_id), [9101]);

  const secondary = await query(8102);
  assert.deepEqual(secondary.items.map(item => item.attachment_id), [9201, 9202]);
  secondary.items.forEach(item => assertItem(item, 8102));
  const nullable = secondary.items.find(item => item.attachment_id === 9202);
  assert.ok(nullable);
  assert.equal(nullable.filename, 'generated-unknown-metadata.bin');
  assert.equal(nullable.content_type, 'application/octet-stream');
  assert.equal(nullable.size_bytes, null);
  assert.equal(nullable.message_date, null);
  assert.equal(nullable.sender_name, null);
  assert.equal(nullable.sender_address, null);
  assert.equal(nullable.subject, null);

  await query(8201, {}, 404);
  await query(8101, { page_size: 51 }, 422);
  await query(8101, { query: 'x'.repeat(257) }, 422);
  await query(8101, { cursor: 'not-a-generated-cursor' }, 422);
  await query(8101, { kind: 'executable' }, 422);
  await query(8101, { direction: 'bcc' }, 422);
  await query(8101, { query: 'private.person@example.invalid' }, 422);

  const containingEmail = await get('/api/emails/10101');
  assert.deepEqual(containingEmail, {
    id: 10101,
    account_id: 8101,
    gmail_thread_id: 'generated-attachment-thread-10101',
    is_read: true,
  });
  await get('/api/emails/10301', 404);

  let audit = await get('/__qa/audit');
  assertZeroExternalAndWrites(audit);
  assert.equal(audit.counters.preview_reads, 0);
  assert.equal(audit.counters.download_reads, 0);
  assert.equal(audit.counters.generated_local_byte_reads, 0);
  assert.equal(audit.counters.generated_local_bytes_served, 0);
  assert.equal(audit.counters.navigation_reads, 1);
  assert.equal(audit.counters.non_generated_rejections, 1);
  assert.deepEqual(audit.allowed_routes, [
    'GET /api/auth/me',
    'GET /api/accounts/',
    'POST /api/attachments/query',
    'GET /api/emails/{email_id}',
    'GET /api/emails/{email_id}/attachments/{attachment_id}/preview',
    'GET /api/emails/{email_id}/attachments/{attachment_id}/download',
  ]);
  results.normal_contract = true;
  results.account_isolation = true;
  results.malicious_metadata = true;
  results.null_metadata = true;

  await reset('empty');
  const empty = await query(8101);
  assert.deepEqual(empty, {
    account_id: 8101,
    items: [],
    next_cursor: null,
    has_more: false,
  });
  audit = await get('/__qa/audit');
  assertZeroExternalAndWrites(audit);
  assert.equal(audit.counters.generated_local_byte_reads, 0);
  results.empty = true;

  await reset('fail-once');
  await query(8101, {}, 503);
  const retried = await query(8101);
  assert.equal(retried.items.length, 4);
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.transient_failures, 1);
  assert.equal(audit.counters.query_requests, 2);
  assertZeroExternalAndWrites(audit);
  results.error_retry = true;

  await reset('held');
  const heldUserAQuery = query(8101);
  await waitFor(async () => {
    const snapshot = await get('/__qa/audit');
    return snapshot.pending_held_queries === 1;
  }, 'held Attachments query did not start');
  await post('/__qa/session', { current_user: 'generated-b' });
  assert.deepEqual((await get('/api/accounts/')).map(account => account.id), [8201]);
  const userB = await query(8201);
  assert.equal(userB.account_id, 8201);
  assert.deepEqual(userB.items.map(item => item.attachment_id), [9301]);
  userB.items.forEach(item => assertItem(item, 8201));
  await post('/__qa/release', {});
  const staleUserA = await heldUserAQuery;
  assert.equal(staleUserA.account_id, 8101);
  assert.ok(staleUserA.items.every(item => item.account_id === 8101));
  assert.ok(staleUserA.items.every(item => item.attachment_id !== 9301));
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.held_queries, 1);
  assert.equal(audit.pending_held_queries, 0);
  assertZeroExternalAndWrites(audit);
  results.held_session_provenance = true;

  await reset('mixed-account-response');
  const maliciousResponse = await query(8101);
  assert.equal(maliciousResponse.account_id, 8101);
  assert.ok(maliciousResponse.items.some(item => item.account_id === 8201));
  assert.ok(maliciousResponse.items.some(item => item.attachment_id === 9301));
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.mixed_account_responses, 1);
  assertZeroExternalAndWrites(audit);
  results.mixed_account_response_mode = true;

  await reset();
  await query(8101);
  await get('/api/emails/10101');
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.preview_reads, 0);
  assert.equal(audit.counters.download_reads, 0);
  assert.equal(audit.counters.generated_local_byte_reads, 0);
  assertZeroExternalAndWrites(audit);

  const preview = await request(
    'GET',
    '/api/emails/10101/attachments/9101/preview',
    undefined,
  );
  assert.equal(preview.payload, null);
  assert.match(preview.response.headers.get('content-type') || '', /^application\/pdf/u);
  assert.equal(preview.response.headers.get('x-attachment-preview-kind'), 'pdf');
  assert.equal(preview.response.headers.get('x-attachment-preview-truncated'), 'false');
  assert.equal(preview.bytes.subarray(0, 4).toString('ascii'), '%PDF');
  assert.equal(firstPage.items[0].size_bytes, preview.bytes.length);
  const download = await request(
    'GET',
    '/api/emails/10101/attachments/9101/download',
    undefined,
  );
  assert.deepEqual(download.bytes, preview.bytes);
  assert.match(download.response.headers.get('content-disposition') || '', /^attachment/u);
  await get('/api/emails/10101/attachments/9301/preview', 404);
  await get('/api/emails/10301/attachments/9301/download', 404);

  audit = await get('/__qa/audit');
  assert.equal(audit.counters.preview_reads, 1);
  assert.equal(audit.counters.download_reads, 1);
  assert.equal(audit.counters.generated_local_byte_reads, 2);
  assert.equal(audit.counters.generated_local_bytes_served, preview.bytes.length * 2);
  assertZeroExternalAndWrites(audit);
  results.explicit_generated_bytes_only = true;

  await post('/__qa/session', { current_user: 'anonymous' });
  await query(8101, {}, 401);
  await get('/api/accounts/', 401);
  await post('/__qa/session', { current_user: 'person@example.invalid' }, 422);
  audit = await get('/__qa/audit');
  assert.equal(audit.counters.auth_rejections, 2);
  assert.equal(audit.counters.non_generated_rejections, 1);
  assertZeroExternalAndWrites(audit);
  results.unauthenticated = true;
  results.non_generated_identity_rejected = true;

  process.stdout.write(`${JSON.stringify({
    generated_only: true,
    localhost_only: true,
    contract: {
      request: ['account_id', 'query', 'kind', 'direction', 'cursor', 'page_size'],
      response: ['account_id', 'items', 'next_cursor', 'has_more'],
      item: ITEM_KEYS,
      nullable_metadata: ['size_bytes', 'message_date', 'sender_name', 'sender_address', 'subject'],
    },
    scenarios: results,
    counters: {
      provider_reads: audit.counters.provider_reads,
      provider_writes: audit.counters.provider_writes,
      mail_mutations: audit.counters.mail_mutations,
      calendar_mutations: audit.counters.calendar_mutations,
      external_network_calls: audit.counters.external_network_calls,
    },
  }, null, 2)}\n`);
} finally {
  await fixture.close();
}
