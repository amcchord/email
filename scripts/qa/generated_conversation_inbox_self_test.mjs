#!/usr/bin/env node

// End-to-end contract check for the conversation-first Inbox against generated
// `.example.test` mail only. The fixture records provider activity so this
// script can prove no Gmail account or production mailbox was touched.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';

const port = 8138;
const baseUrl = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['scripts/qa/generated_mail_action_server.mjs'], {
  cwd: process.cwd(),
  env: { ...process.env, QA_API_PORT: String(port) },
  stdio: ['ignore', 'pipe', 'pipe'],
});

let serverOutput = '';
server.stdout.on('data', chunk => { serverOutput += chunk.toString(); });
server.stderr.on('data', chunk => { serverOutput += chunk.toString(); });

async function waitForServer() {
  const deadline = Date.now() + 8_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/health`);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error(`Generated conversation server did not start: ${serverOutput}`);
}

async function request(method, path, body = undefined, expectedStatus = 200) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expectedStatus, `${method} ${path}: ${JSON.stringify(payload)}`);
  return payload;
}

try {
  await waitForServer();

  const inbox = await request('GET', '/api/emails/conversations?mailbox=INBOX&page=1&page_size=3');
  assert.equal(inbox.total, 7, 'two generated sibling messages count as one conversation');
  assert.equal(inbox.conversations.length, 3);
  assert.equal(inbox.total_pages, 3);
  assert.equal(new Set(inbox.conversations.map(item => item.conversation_key)).size, 3);

  const design = inbox.conversations.find(item => item.gmail_thread_id === 'generated-thread-1');
  assert.ok(design, 'newest generated conversation is present');
  assert.equal(design.member_count, 2);
  assert.equal(design.matched_count, 2);
  assert.equal(design.unread_count, 2);
  assert.equal(design.star_state, 'none');
  assert.equal(design.conversation_key, '1:thread:generated-thread-1');

  const thread = await request('GET', '/api/emails/thread/generated-thread-1?account_id=1');
  assert.equal(thread.emails.length, 2);
  assert.ok(thread.emails.every(email => email.account_id === 1));
  assert.ok(Date.parse(thread.emails[0].date) <= Date.parse(thread.emails[1].date));

  const actionKey = randomUUID();
  const actionPayload = {
    email_ids: [design.anchor_email_id],
    action: 'mark_read',
    scope: 'conversations',
    idempotency_key: actionKey,
  };
  const markedRead = await request('POST', '/api/emails/actions', actionPayload, 202);
  assert.equal(markedRead.accepted_count, 2, 'one row expands to all synchronized members');
  const replay = await request('POST', '/api/emails/actions', actionPayload, 202);
  assert.equal(replay.request_id, markedRead.request_id);

  let audit = await request('GET', '/api/__qa/mail-action-audit');
  assert.ok(audit.emails.filter(email => email.gmail_thread_id === 'generated-thread-1').every(email => email.is_read));

  await request('POST', `/api/emails/actions/${markedRead.request_id}/undo`, {}, 200);
  audit = await request('GET', '/api/__qa/mail-action-audit');
  assert.ok(audit.emails.filter(email => email.gmail_thread_id === 'generated-thread-1').every(email => !email.is_read));
  assert.equal(audit.provider_calls, 0);
  assert.deepEqual(audit.fixture_domains, ['example.test']);
  assert.equal(audit.unknown_routes.length, 0);

  process.stdout.write(`${JSON.stringify({
    generated_only: true,
    provider_calls: audit.provider_calls,
    conversation_total: inbox.total,
    page_size: inbox.page_size,
    expanded_messages: markedRead.accepted_count,
    full_thread_messages: thread.emails.length,
    undo_verified: true,
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
