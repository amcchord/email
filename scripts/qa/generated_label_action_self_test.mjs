#!/usr/bin/env node

// End-to-end contract check for Labels & Move against generated .example.test
// mail only. The local server records provider calls so this script can prove
// that no Gmail account or production mailbox was touched.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';

const port = 8137;
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
  throw new Error(`Generated label server did not start: ${serverOutput}`);
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

function labelAction(action, emailIds, labelId, idempotencyKey = randomUUID()) {
  return {
    email_ids: emailIds,
    action,
    label_id: labelId,
    idempotency_key: idempotencyKey,
  };
}

function emailById(audit, id) {
  const email = audit.emails.find(item => item.id === id);
  assert.ok(email, `missing generated email ${id}`);
  return email;
}

try {
  await waitForServer();

  const firstAccountLabels = await request('GET', '/api/emails/labels/all?account_id=1');
  assert.deepEqual(firstAccountLabels.map(label => label.id), [11, 12, 13]);
  assert.ok(firstAccountLabels.every(label => label.account_id === 1));

  const addKey = randomUUID();
  const added = await request('POST', '/api/emails/actions', labelAction('add_label', [101], 11, addKey), 202);
  assert.equal(added.accepted_count, 2, 'one selected message expands to its two-message conversation');
  const replay = await request('POST', '/api/emails/actions', labelAction('add_label', [101], 11, addKey), 202);
  assert.equal(replay.request_id, added.request_id);
  await request('POST', '/api/emails/actions', labelAction('add_label', [101], 12, addKey), 409);

  let audit = await request('GET', '/api/__qa/mail-action-audit');
  assert.ok(emailById(audit, 101).labels.includes('Label_Projects'));
  assert.ok(emailById(audit, 107).labels.includes('Label_Projects'));
  assert.deepEqual(audit.label_actions[0].expanded_email_ids.sort((a, b) => a - b), [101, 107]);

  const removed = await request('POST', '/api/emails/actions', labelAction('remove_label', [107], 11), 202);
  assert.equal(removed.accepted_count, 2);
  audit = await request('GET', '/api/__qa/mail-action-audit');
  assert.equal(emailById(audit, 101).labels.includes('Label_Projects'), false);
  assert.equal(emailById(audit, 107).labels.includes('Label_Projects'), false);

  const moved = await request('POST', '/api/emails/actions', labelAction('move_to_label', [102], 12), 202);
  audit = await request('GET', '/api/__qa/mail-action-audit');
  assert.ok(emailById(audit, 102).labels.includes('Label_Receipts'));
  assert.equal(emailById(audit, 102).labels.includes('INBOX'), false);

  await request('POST', `/api/emails/actions/${moved.request_id}/undo`, {}, 200);
  audit = await request('GET', '/api/__qa/mail-action-audit');
  assert.ok(emailById(audit, 102).labels.includes('INBOX'));
  assert.equal(emailById(audit, 102).labels.includes('Label_Receipts'), false);

  await request('POST', '/api/emails/actions', labelAction('add_label', [103, 109], 11), 422);
  await request('POST', '/api/emails/actions', labelAction('add_label', [101], 13), 422);

  audit = await request('GET', '/api/__qa/mail-action-audit');
  assert.equal(audit.provider_calls, 0);
  assert.deepEqual(audit.fixture_domains, ['example.test']);
  assert.equal(audit.unknown_routes.length, 0);
  assert.equal(audit.label_actions.length, 3);
  assert.equal(audit.rejected_mutations.length, 3);

  process.stdout.write(`${JSON.stringify({
    generated_only: true,
    provider_calls: audit.provider_calls,
    label_actions: audit.label_actions.length,
    thread_expansion: audit.label_actions[0].expanded_email_ids.length,
    rejected_conflict_or_account_or_system_targets: audit.rejected_mutations.length,
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
