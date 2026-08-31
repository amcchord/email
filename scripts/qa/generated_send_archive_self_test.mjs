#!/usr/bin/env node

import assert from 'node:assert/strict';
import { createGeneratedProviderDraftFixture } from './generated_provider_draft_server.mjs';

const CLOCK = '2026-08-30T16:00:00.000Z';
const SCHEDULE = '2026-08-30T16:05:00.000Z';

async function request(base, method, path, body = undefined, expectedStatus = 200) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(response.status, expectedStatus, `${method} ${path}: ${JSON.stringify(payload)}`);
  return payload;
}

function replyDraft(clientDraftId, mutationId) {
  return {
    account_id: 1101,
    to: ['recipient-a@example.test'],
    cc: [],
    bcc: [],
    subject: 'Re: Generated send and archive QA',
    body_html: '<p>Generated send and archive QA.</p>',
    body_text: 'Generated send and archive QA.',
    source_email_id: 1301,
    thread_id: 'generated-source-thread-a',
    in_reply_to: '<generated-parent-a@example.test>',
    references: '<generated-root-a@example.test> <generated-parent-a@example.test>',
    is_draft: true,
    attachments: [],
    client_draft_id: clientDraftId,
    revision: 1,
    mutation_id: mutationId,
  };
}

function outbound(clientDraftId, idempotencyKey, overrides = {}) {
  return {
    account_id: 1101,
    to: ['recipient-a@example.test'],
    cc: [],
    bcc: [],
    subject: 'Re: Generated send and archive QA',
    body_html: '<p>Generated send and archive QA.</p>',
    body_text: 'Generated send and archive QA.',
    source_email_id: 1301,
    thread_id: 'generated-source-thread-a',
    in_reply_to: '<generated-parent-a@example.test>',
    references: '<generated-root-a@example.test> <generated-parent-a@example.test>',
    archive_source_after_send: true,
    client_draft_id: clientDraftId,
    draft_revision: 1,
    idempotency_key: idempotencyKey,
    ...overrides,
  };
}

const fixture = createGeneratedProviderDraftFixture();
try {
  const address = await fixture.listen(0);
  const base = `http://${address.address}:${address.port}`;

  await request(base, 'POST', '/api/qa/reset', { clock_now: CLOCK });
  const undoDraft = '40000000-0000-4000-8000-000000000001';
  await request(base, 'POST', '/api/compose/draft', replyDraft(
    undoDraft,
    '41000000-0000-4000-8000-000000000001',
  ), 202);
  const undoSend = await request(base, 'POST', '/api/compose/send', outbound(
    undoDraft,
    '42000000-0000-4000-8000-000000000001',
  ), 202);
  assert.equal(undoSend.archive_source_after_send, true);
  await request(base, 'POST', `/api/compose/sends/${undoSend.send_id}/undo`, {});
  let audit = await request(base, 'GET', '/api/qa/audit');
  assert.equal(audit.counters.provider_sends, 0);
  assert.equal(audit.counters.post_send_archives, 0);
  assert.equal(audit.logical_outbounds[0].archive_source_after_send, true);

  await request(base, 'POST', '/api/qa/reset', { clock_now: CLOCK });
  const cancelDraft = '40000000-0000-4000-8000-000000000002';
  await request(base, 'POST', '/api/compose/draft', replyDraft(
    cancelDraft,
    '41000000-0000-4000-8000-000000000002',
  ), 202);
  const scheduled = await request(base, 'POST', '/api/compose/send', outbound(
    cancelDraft,
    '42000000-0000-4000-8000-000000000002',
    { scheduled_for: SCHEDULE, schedule_timezone: 'America/New_York' },
  ), 202);
  await request(base, 'POST', `/api/compose/sends/${scheduled.send_id}/cancel`, {});
  audit = await request(base, 'GET', '/api/qa/audit');
  assert.equal(audit.counters.provider_sends, 0);
  assert.equal(audit.counters.post_send_archives, 0);

  await request(base, 'POST', '/api/qa/reset', { clock_now: CLOCK });
  const sentDraft = '40000000-0000-4000-8000-000000000003';
  await request(base, 'POST', '/api/compose/draft', replyDraft(
    sentDraft,
    '41000000-0000-4000-8000-000000000003',
  ), 202);
  const due = await request(base, 'POST', '/api/compose/send', outbound(
    sentDraft,
    '42000000-0000-4000-8000-000000000003',
    { scheduled_for: SCHEDULE, schedule_timezone: 'America/New_York' },
  ), 202);
  await request(base, 'POST', '/api/qa/clock', { now: SCHEDULE });
  const sent = await request(base, 'GET', `/api/compose/sends/${due.send_id}`);
  assert.equal(sent.state, 'sent');
  audit = await request(base, 'GET', '/api/qa/audit');
  assert.equal(audit.counters.provider_sends, 1);
  assert.equal(audit.counters.post_send_archives, 1);
  assert.equal(audit.counters.external_network_calls, 0);
  assert.equal(audit.counters.non_example_test_rejections, 0);
  assert.equal(audit.counters.unexpected_mutations, 0);
  assert.equal(audit.counters.unknown_routes, 0);
  assert.deepEqual(
    audit.events.filter(event => event.kind === 'post_send_archive_committed').map(event => event.source_email_id),
    [1301],
  );

  process.stdout.write(`${JSON.stringify({
    ok: true,
    undo_archives: 0,
    cancel_archives: 0,
    delivered_archives: audit.counters.post_send_archives,
    external_network_calls: audit.counters.external_network_calls,
  })}\n`);
} finally {
  await fixture.close();
}
