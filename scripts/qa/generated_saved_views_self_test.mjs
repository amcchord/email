#!/usr/bin/env node

// Integration contract test for Saved Views on the generated structured-search
// server. It starts localhost only and proves all accepted writes are confined
// to the in-memory Saved Views fixture.

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';

async function reservePort() {
  const probe = createServer();
  await new Promise((resolve, reject) => {
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', resolve);
  });
  const { port } = probe.address();
  await new Promise(resolve => probe.close(resolve));
  return port;
}
const port = await reservePort();
const baseUrl = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['scripts/qa/generated_search_server.mjs'], {
  cwd: process.cwd(),
  env: { ...process.env, QA_PORT: String(port) },
  stdio: ['ignore', 'pipe', 'pipe'],
});

let serverOutput = '';
server.stdout.on('data', chunk => { serverOutput += chunk.toString(); });
server.stderr.on('data', chunk => { serverOutput += chunk.toString(); });

async function waitForServer() {
  const deadline = Date.now() + 8_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/build-version`);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  throw new Error(`Generated search server did not start: ${serverOutput}`);
}

async function request(method, pathname, body, expectedStatus = 200) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = null;
  if (text) payload = JSON.parse(text);
  assert.equal(response.status, expectedStatus, `${method} ${pathname}: ${text}`);
  if (pathname.startsWith('/api/saved-views')) {
    assert.match(response.headers.get('cache-control') || '', /private.*no-store/i);
  }
  return payload;
}

const get = (pathname, expectedStatus = 200) => request('GET', pathname, undefined, expectedStatus);
const post = (pathname, body, expectedStatus = 200) => request('POST', pathname, body, expectedStatus);
const put = (pathname, body, expectedStatus = 200) => request('PUT', pathname, body, expectedStatus);
const remove = (pathname, expectedStatus = 204) => request('DELETE', pathname, undefined, expectedStatus);

async function reset(currentUser = 'generated-a') {
  return post('/api/test/saved-views/reset', { current_user: currentUser });
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 1_000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.fail(message);
}

const ITEM_KEYS = [
  'account_id',
  'create_id',
  'created_at',
  'id',
  'name',
  'position',
  'query',
  'revision',
  'updated_at',
].sort();
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PRIVATE_QUERY = 'from:renee+launch@example.test subject:"Quarterly & Planning" has:attachment -is:read in:inbox';
const SECONDARY_QUERY = 'from:renee+launch@example.test subject:"Quarterly & Planning" -is:read in:inbox';
const CREATE_ID = 'a049c2c7-12a9-4f92-ad43-79738c9015bb';
const FOREIGN_ID = '72727272-cf14-4a8b-9589-d984385616c8';

function assertItem(item) {
  assert.deepEqual(Object.keys(item).sort(), ITEM_KEYS);
  assert.match(item.id, UUID_PATTERN);
  assert.match(item.create_id, UUID_PATTERN);
  assert.ok(item.account_id === null || Number.isSafeInteger(item.account_id));
  assert.ok(Number.isSafeInteger(item.revision) && item.revision > 0);
  assert.ok(Number.isSafeInteger(item.position) && item.position >= 0);
  assert.ok(Number.isFinite(Date.parse(item.created_at)));
  assert.ok(Number.isFinite(Date.parse(item.updated_at)));
}

try {
  await waitForServer();
  await reset();

  const userA = await get('/api/auth/me');
  assert.equal(userA.username, 'saved-view-user-a@example.test');
  const userAAccounts = await get('/api/accounts/');
  assert.deepEqual(userAAccounts.map(account => account.id), [1, 2]);

  const initial = await get('/api/saved-views');
  assert.deepEqual(Object.keys(initial).sort(), ['items', 'max_views']);
  assert.equal(initial.max_views, 12);
  assert.equal(initial.items.length, 2);
  initial.items.forEach(assertItem);
  assert.deepEqual(initial.items.map(item => item.position), [0, 1]);
  assert.deepEqual(initial.items.map(item => item.account_id), [1, 2]);
  assert.equal(initial.items[0].query, PRIVATE_QUERY);

  const createBody = {
    create_id: CREATE_ID,
    name: '  Generated   Important  ',
    account_id: 1,
    query: PRIVATE_QUERY,
  };
  const created = await post('/api/saved-views', createBody, 201);
  assertItem(created);
  assert.equal(created.name, 'Generated Important');
  assert.equal(created.account_id, 1);
  assert.equal(created.query, PRIVATE_QUERY);
  assert.equal(created.revision, 1);
  assert.equal(created.position, 2);

  const replayedCreate = await post('/api/saved-views', {
    ...createBody,
    name: 'Generated Important',
  });
  assert.deepEqual(replayedCreate, created);
  await post('/api/saved-views', { ...createBody, name: 'Different replay' }, 409);
  await post('/api/saved-views', { ...createBody, create_id: 'not-a-uuid' }, 422);
  await post('/api/saved-views', {
    ...createBody,
    create_id: '32323232-5d0c-4ae1-84de-fb80c291e44c',
    account_id: 3,
  }, 404);
  await post('/api/saved-views', {
    ...createBody,
    create_id: '43434343-efba-4755-8608-0f531401446d',
    query: 'subject:"unterminated',
  }, 422);

  const updated = await put(`/api/saved-views/${created.id}`, {
    revision: created.revision,
    name: 'Generated Renamed',
    account_id: 1,
    query: SECONDARY_QUERY,
  });
  assert.equal(updated.name, 'Generated Renamed');
  assert.equal(updated.account_id, 1);
  assert.equal(updated.query, SECONDARY_QUERY);
  assert.equal(updated.revision, 2);
  const replayedUpdate = await put(`/api/saved-views/${created.id}`, {
    revision: created.revision,
    name: 'Generated Renamed',
    account_id: 1,
    query: SECONDARY_QUERY,
  });
  assert.deepEqual(replayedUpdate, updated);
  await put(`/api/saved-views/${created.id}`, {
    revision: created.revision,
    name: 'Generated stale overwrite',
    account_id: 1,
    query: PRIVATE_QUERY,
  }, 409);
  await put(`/api/saved-views/${FOREIGN_ID}`, {
    revision: 7,
    name: 'Foreign overwrite',
    account_id: 1,
    query: PRIVATE_QUERY,
  }, 404);

  let beforeReorder = await get('/api/saved-views');
  const beforeIds = beforeReorder.items.map(item => item.id);
  const desiredIds = [...beforeIds].reverse();
  await post('/api/saved-views/reorder', {
    expected_order: [...beforeIds].reverse(),
    view_ids: desiredIds,
  }, 409);
  const reordered = await post('/api/saved-views/reorder', {
    expected_order: beforeIds,
    view_ids: desiredIds,
  });
  assert.deepEqual(reordered.items.map(item => item.id), desiredIds);
  assert.deepEqual(reordered.items.map(item => item.position), [0, 1, 2]);

  const deleting = reordered.items.find(item => item.id === created.id);
  await remove(`/api/saved-views/${created.id}?revision=${created.revision}`, 409);
  await remove(`/api/saved-views/${created.id}?revision=${deleting.revision}`);
  const afterDelete = await get('/api/saved-views');
  assert.equal(afterDelete.items.length, 2);
  assert.deepEqual(afterDelete.items.map(item => item.position), [0, 1]);

  await post('/api/test/saved-views/scenario', { scenario: 'fail-next' });
  await get('/api/saved-views', 503);
  assert.equal((await get('/api/saved-views')).items.length, 2);

  await reset();
  await post('/api/test/saved-views/scenario', { scenario: 'hold-next-list' });
  const heldUserAList = get('/api/saved-views');
  await waitFor(async () => (
    (await get('/api/test/saved-views-audit')).pending_held_requests === 1
  ), 'held Saved Views request did not start');
  await post('/api/test/saved-views/session', { current_user: 'generated-b' });
  const userB = await get('/api/auth/me');
  assert.equal(userB.username, 'saved-view-user-b@example.test');
  assert.deepEqual((await get('/api/accounts/')).map(account => account.id), [3]);
  const userBList = await get('/api/saved-views');
  assert.equal(userBList.items.length, 1);
  assert.equal(userBList.items[0].id, FOREIGN_ID);
  assert.ok(userBList.items.every(item => item.account_id === 3));
  await post('/api/test/saved-views/release', {});
  const heldResponse = await heldUserAList;
  assert.equal(heldResponse.items.length, 2);
  assert.ok(heldResponse.items.every(item => [1, 2].includes(item.account_id)));
  assert.ok(heldResponse.items.every(item => item.id !== FOREIGN_ID));

  await post('/api/test/saved-views/session', { current_user: 'anonymous' });
  await get('/api/saved-views', 401);
  await get('/api/accounts/', 401);

  await post('/api/test/saved-views/session', { current_user: 'generated-a' });
  const audit = await get('/api/test/saved-views-audit');
  assert.equal(audit.localhost_only, true);
  assert.deepEqual(audit.fixture_domains, ['example.test']);
  assert.equal(audit.counters.mail_mutations, 0);
  assert.equal(audit.counters.calendar_mutations, 0);
  assert.equal(audit.counters.provider_mutations, 0);
  assert.equal(audit.counters.provider_sends, 0);
  assert.equal(audit.counters.external_network_calls, 0);
  assert.equal(audit.counters.auth_rejections, 1);
  assert.equal(audit.counters.held_requests, 1);
  assert.equal(audit.counters.expected_local_mutations, 0, 'reset cleared earlier local mutation counters');
  const auditText = JSON.stringify(audit);
  assert.equal(auditText.includes(PRIVATE_QUERY), false, 'private query leaked into audit');
  assert.equal(auditText.includes('Quarterly & Planning'), false, 'private query term leaked into audit');

  const mainAudit = await get('/api/test/audit');
  assert.deepEqual(mainAudit.mutation_attempts, []);
  assert.equal(mainAudit.saved_views.counters.provider_sends, 0);
  assert.equal(mainAudit.saved_views.counters.external_network_calls, 0);

  process.stdout.write(`${JSON.stringify({
    generated_only: true,
    saved_view_contract: true,
    isolated_users: ['generated-a', 'generated-b'],
    isolated_accounts: [1, 2, 3],
    held_session_provenance: true,
    private_query_in_audit: false,
    provider_sends: audit.counters.provider_sends,
    mail_mutations: audit.counters.mail_mutations,
    calendar_mutations: audit.counters.calendar_mutations,
    external_network_calls: audit.counters.external_network_calls,
  }, null, 2)}\n`);
} finally {
  server.kill('SIGTERM');
  await new Promise(resolve => {
    const timer = setTimeout(resolve, 1_000);
    server.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });
  });
}
