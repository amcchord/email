#!/usr/bin/env node

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';

const port = 18_080;
const base = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['scripts/qa/generated_mail_action_server.mjs'], {
  cwd: process.cwd(),
  env: { ...process.env, QA_API_PORT: String(port) },
  stdio: ['ignore', 'pipe', 'pipe'],
});

let serverOutput = '';
server.stdout.on('data', chunk => { serverOutput += chunk.toString(); });
server.stderr.on('data', chunk => { serverOutput += chunk.toString(); });

async function request(method, path, body = undefined) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`${method} ${path}: ${response.status} ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function waitForServer() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      await request('GET', '/api/health');
      return;
    } catch {
      await new Promise(resolve => setTimeout(resolve, 20));
    }
  }
  throw new Error(`Generated snooze server did not start: ${serverOutput}`);
}

function createPayload(emailId, wakeAt, suffix, condition = 'always') {
  return {
    email_id: emailId,
    wake_at: wakeAt,
    time_zone: 'America/New_York',
    condition,
    idempotency_key: `10000000-0000-4000-8000-${String(suffix).padStart(12, '0')}`,
  };
}

async function emailVisible(emailId) {
  const payload = await request('GET', '/api/emails/?mailbox=INBOX');
  return payload.emails.filter(email => email.id === emailId).length;
}

async function expectConflict(path, body) {
  const response = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  assert.equal(response.status, 409);
  return response.json();
}

try {
  await waitForServer();

  const firstPayload = createPayload(101, '2026-08-30T16:00:00.000Z', 1);
  const first = await request('POST', '/api/snoozes', firstPayload);
  const replay = await request('POST', '/api/snoozes', firstPayload);
  assert.equal(replay.id, first.id);
  assert.equal(first.conversation_message_count, 2);
  assert.equal(await emailVisible(101), 0);
  assert.equal(await emailVisible(107), 0, 'all current Inbox messages in the conversation must hide');
  await expectConflict('/api/snoozes', createPayload(107, '2026-08-30T16:30:00.000Z', 99));

  await request('POST', '/api/__qa/clock', { now: '2026-08-30T15:59:59.999Z' });
  assert.equal(await emailVisible(101), 0, 'mail must stay hidden one millisecond before wake');
  await request('POST', '/api/__qa/clock', { now: '2026-08-30T16:00:00.000Z' });
  assert.equal(await emailVisible(101), 1, 'mail must return at the exact wake instant');
  assert.equal(await emailVisible(107), 1, 'the current conversation must return together');
  assert.equal((await request('GET', `/api/snoozes/${first.id}`)).state, 'returned');

  const second = await request(
    'POST',
    '/api/snoozes',
    createPayload(102, '2026-08-30T17:00:00.000Z', 2),
  );
  await request('PATCH', `/api/snoozes/${second.id}/reschedule`, {
    wake_at: '2026-08-30T18:00:00.000Z',
    time_zone: 'America/New_York',
  });
  await request('POST', '/api/__qa/clock', { now: '2026-08-30T17:00:00.000Z' });
  assert.equal(await emailVisible(102), 0, 'reschedule must invalidate the former wake');
  await request('POST', '/api/__qa/clock', { now: '2026-08-30T18:00:00.000Z' });
  assert.equal(await emailVisible(102), 1);

  const third = await request(
    'POST',
    '/api/snoozes',
    createPayload(103, '2026-08-30T19:00:00.000Z', 3, 'if_no_reply'),
  );
  await request('POST', '/api/__qa/generated-reply', { snooze_id: third.id });
  await request('POST', '/api/__qa/clock', { now: '2026-08-30T19:00:00.000Z' });
  assert.equal((await request('GET', `/api/snoozes/${third.id}`)).status_detail, 'reply_received');
  assert.equal(await emailVisible(103), 0, 'reply-before-due must not revive the archived email');

  const fourth = await request(
    'POST',
    '/api/snoozes',
    createPayload(104, '2026-08-30T20:00:00.000Z', 4),
  );
  await request('POST', '/api/__qa/protected-mailbox', { email_id: 104, mailbox: 'trash' });
  await request('POST', '/api/__qa/clock', { now: '2026-08-30T20:00:00.000Z' });
  assert.equal((await request('GET', `/api/snoozes/${fourth.id}`)).status_detail, 'protected_mailbox');
  assert.equal(await emailVisible(104), 0, 'Trash must never be resurrected');

  const fifth = await request(
    'POST',
    '/api/snoozes',
    createPayload(105, '2026-08-30T21:00:00.000Z', 5),
  );
  await request('POST', `/api/emails/actions/${fifth.archive_action_request_id}/undo`, {});
  assert.equal(await emailVisible(105), 1, 'Undo must restore the optimistic archive');
  assert.equal((await request('GET', `/api/snoozes/${fifth.id}`)).status_detail, 'archive_undone');

  const sentCancel = await request(
    'POST',
    '/api/snoozes',
    createPayload(108, '2026-08-30T22:00:00.000Z', 6),
  );
  assert.equal(sentCancel.originally_in_inbox, false);
  await request('POST', `/api/snoozes/${sentCancel.id}/cancel`, {});
  assert.equal(await emailVisible(108), 0, 'Cancel must preserve a sent-only conversation outside Inbox');

  const sentReturn = await request(
    'POST',
    '/api/snoozes',
    createPayload(108, '2026-08-30T23:00:00.000Z', 7),
  );
  await request('POST', `/api/snoozes/${sentReturn.id}/return-now`, {});
  assert.equal(await emailVisible(108), 1, 'Return now must bring a sent-only reminder to Inbox');

  const audit = await request('GET', '/api/__qa/snooze-audit');
  assert.equal(audit.provider_calls, 0);
  assert.equal(audit.unknown_routes.length, 0);
  assert.equal(audit.rejected_mutations.length, 0);
  assert.equal(audit.snooze_creates.length, 7);
  assert.equal(audit.snooze_replays.length, 1);
  assert.equal(audit.snooze_returns.filter(item => item.reason === 'due').length, 2);

  process.stdout.write(`${JSON.stringify({
    ok: true,
    boundary: 'wake-minus-1ms / exact-wake',
    conversation_messages: first.conversation_message_count,
    original_placement_restored_on_cancel: true,
    sent_only_returned_to_inbox: true,
    idempotent_replays: audit.snooze_replays.length,
    due_returns: audit.snooze_returns.filter(item => item.reason === 'due').length,
    protected_mailbox_resurrections: 0,
    reply_condition_resurrections: 0,
    provider_calls: audit.provider_calls,
    unknown_routes: audit.unknown_routes.length,
  })}\n`);
} finally {
  server.kill('SIGTERM');
  await new Promise(resolve => {
    if (server.exitCode !== null) return resolve();
    server.once('exit', resolve);
    setTimeout(() => {
      server.kill('SIGKILL');
      resolve();
    }, 1_000).unref();
  });
}
