#!/usr/bin/env node

import assert from 'node:assert/strict';
import { createGeneratedProviderDraftFixture } from './generated_provider_draft_server.mjs';

const T = '2026-08-30T16:00:00.000Z';
const S = '2026-08-30T16:05:00.000Z';

async function request(base, method, path, body = undefined) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${JSON.stringify(payload)}`);
  return payload;
}

async function stageGeneratedDraft(base, clientDraftId, mutationId) {
  return request(base, 'POST', '/api/compose/draft', {
    account_id: 1101,
    to: ['recipient-a@example.test'],
    cc: [],
    bcc: [],
    subject: 'Generated scheduled QA',
    body_html: '<p>Generated scheduled QA</p>',
    body_text: 'Generated scheduled QA',
    is_draft: true,
    attachments: [],
    client_draft_id: clientDraftId,
    revision: 1,
    mutation_id: mutationId,
  });
}

async function stageGeneratedSchedule(base, clientDraftId, idempotencyKey) {
  return request(base, 'POST', '/api/compose/send', {
    account_id: 1101,
    to: ['recipient-a@example.test'],
    cc: [],
    bcc: [],
    subject: 'Generated scheduled QA',
    body_html: '<p>Generated scheduled QA</p>',
    body_text: 'Generated scheduled QA',
    attachments: [],
    client_draft_id: clientDraftId,
    draft_revision: 1,
    idempotency_key: idempotencyKey,
    scheduled_for: S,
    schedule_timezone: 'America/New_York',
  });
}

const fixture = createGeneratedProviderDraftFixture();
try {
  const address = await fixture.listen(0);
  const base = `http://${address.address}:${address.port}`;

  await request(base, 'POST', '/api/qa/reset', { clock_now: T });
  const firstDraft = '10000000-0000-4000-8000-000000000001';
  await stageGeneratedDraft(base, firstDraft, '20000000-0000-4000-8000-000000000001');
  const first = await stageGeneratedSchedule(
    base,
    firstDraft,
    '30000000-0000-4000-8000-000000000001',
  );
  assert.equal(first.state, 'staged');
  assert.equal(first.execute_after, S);

  await request(base, 'POST', '/api/qa/clock', { now: '2026-08-30T16:04:59.999Z' });
  const beforeDue = await request(base, 'GET', `/api/compose/sends/${first.send_id}`);
  assert.equal(beforeDue.state, 'staged');
  let audit = await request(base, 'GET', '/api/qa/audit');
  assert.equal(audit.counters.provider_send_lookups, 0);
  assert.equal(audit.counters.provider_sends, 0);

  const cancelled = await request(base, 'POST', `/api/compose/sends/${first.send_id}/cancel`, {});
  assert.equal(cancelled.state, 'cancelled');
  const restoredDraft = await request(base, 'GET', `/api/compose/drafts/by-client-id/${firstDraft}`);
  assert.equal(restoredDraft.state, 'synced');
  assert.equal(restoredDraft.subject, 'Generated scheduled QA');
  await request(base, 'POST', '/api/qa/clock', { now: '2026-08-30T16:06:00.000Z' });
  await request(base, 'GET', `/api/compose/sends/${first.send_id}`);
  audit = await request(base, 'GET', '/api/qa/audit');
  assert.equal(audit.counters.provider_send_lookups, 0);
  assert.equal(audit.counters.provider_sends, 0);
  assert.equal(audit.logical_outbounds[0].payload_retained, false);

  await request(base, 'POST', '/api/qa/reset', { clock_now: T });
  const secondDraft = '10000000-0000-4000-8000-000000000002';
  await stageGeneratedDraft(base, secondDraft, '20000000-0000-4000-8000-000000000002');
  const second = await stageGeneratedSchedule(
    base,
    secondDraft,
    '30000000-0000-4000-8000-000000000002',
  );
  await request(base, 'POST', '/api/qa/clock', { now: S });
  const sent = await request(base, 'GET', `/api/compose/sends/${second.send_id}`);
  assert.equal(sent.state, 'sent');
  audit = await request(base, 'GET', '/api/qa/audit');
  assert.equal(audit.counters.provider_send_lookups, 1);
  assert.equal(audit.counters.provider_sends, 1);
  assert.equal(audit.counters.external_network_calls, 0);
  assert.equal(audit.counters.unexpected_mutations, 0);
  assert.equal(audit.counters.unknown_routes, 0);

  await request(base, 'POST', '/api/qa/reset', { clock_now: T });
  const thirdDraft = '10000000-0000-4000-8000-000000000003';
  await stageGeneratedDraft(base, thirdDraft, '20000000-0000-4000-8000-000000000003');
  const third = await stageGeneratedSchedule(
    base,
    thirdDraft,
    '30000000-0000-4000-8000-000000000003',
  );
  const sentNow = await request(base, 'POST', `/api/compose/sends/${third.send_id}/send-now`, {});
  assert.equal(sentNow.state, 'sent');
  audit = await request(base, 'GET', '/api/qa/audit');
  assert.equal(audit.counters.outbound_send_now, 1);
  assert.equal(audit.counters.provider_send_lookups, 1);
  assert.equal(audit.counters.provider_sends, 1);

  process.stdout.write(`${JSON.stringify({
    ok: true,
    boundary: 'not-before exact',
    cancelled_before_due_provider_calls: 0,
    due_provider_lookups: audit.counters.provider_send_lookups,
    due_provider_sends: audit.counters.provider_sends,
    send_now_provider_sends: audit.counters.provider_sends,
    external_network_calls: audit.counters.external_network_calls,
  })}\n`);
} finally {
  await fixture.close();
}
