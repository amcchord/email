#!/usr/bin/env node

// Short-lived contract test for generated_provider_draft_server.mjs.
// It uses an ephemeral localhost port and exits after every in-memory fixture
// scenario has proved its exact provider and safety counters.

import assert from 'node:assert/strict';

import {
  GENERATED_PROVIDER_DRAFT_HOST,
  createGeneratedProviderDraftFixture,
} from './generated_provider_draft_server.mjs';

const fixture = createGeneratedProviderDraftFixture({ discardWindowMs: 20 });
const address = await fixture.listen(0);
const baseUrl = `http://${GENERATED_PROVIDER_DRAFT_HOST}:${address.port}`;

const ids = Object.freeze({
  repeated: '00000000-0000-4000-8000-000000000101',
  immutable: '00000000-0000-4000-8000-000000000110',
  lost: '00000000-0000-4000-8000-000000000102',
  attachment: '00000000-0000-4000-8000-000000000103',
  provenance: '00000000-0000-4000-8000-000000000104',
  held: '00000000-0000-4000-8000-000000000105',
  undo: '00000000-0000-4000-8000-000000000106',
  deletion: '00000000-0000-4000-8000-000000000107',
  offline: '00000000-0000-4000-8000-000000000108',
  guard: '00000000-0000-4000-8000-000000000109',
});

let mutationSequence = 200;
function mutationId() {
  mutationSequence += 1;
  return `00000000-0000-4000-8000-${String(mutationSequence).padStart(12, '0')}`;
}

function draftPayload({
  clientDraftId,
  mutation = mutationId(),
  revision = 1,
  accountId = 1101,
  subject = 'Generated provider draft',
  bodyHtml = '<p>Generated provider draft fixture.</p>',
  sourceEmailId = null,
  threadId = null,
  inReplyTo = null,
  references = null,
  attachments = [],
  to = ['recipient@example.test'],
} = {}) {
  return {
    client_draft_id: clientDraftId,
    mutation_id: mutation,
    revision,
    account_id: accountId,
    to,
    cc: [],
    bcc: [],
    subject,
    body_html: bodyHtml,
    body_text: bodyHtml.replace(/<[^>]*>/g, ''),
    source_email_id: sourceEmailId,
    thread_id: threadId,
    in_reply_to: inReplyTo,
    references,
    is_draft: true,
    attachments,
  };
}

async function request(method, pathname, body, { expectedStatus = 200 } = {}) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  assert.equal(
    response.status,
    expectedStatus,
    `${method} ${pathname}: ${JSON.stringify(payload)}`,
  );
  return payload;
}

const get = pathname => request('GET', pathname);
const post = (pathname, body = {}, options = {}) => request('POST', pathname, body, options);

async function reset(scenario = 'clean', options = {}) {
  return post('/api/qa/reset', {
    scenario,
    current_user: 'generated-a',
    discard_window_ms: options.discardWindowMs ?? 20,
  });
}

async function audit() {
  return get('/api/qa/audit');
}

function assertExpectedFlowSafety(snapshot) {
  assert.equal(snapshot.counters.unexpected_mutations, 0);
  assert.equal(snapshot.counters.unknown_routes, 0);
  assert.equal(snapshot.counters.external_network_calls, 0);
  assert.equal(snapshot.fixture_domains.length, 1);
  assert.equal(snapshot.fixture_domains[0], 'example.test');
  assert.equal(snapshot.localhost_only, true);
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

const results = {};

try {
  // Repeated autosave: one create, one immutable mutation replay, one same-
  // revision replay under a fresh mutation, and one higher-revision update.
  await reset('clean');
  const repeatedMutation = mutationId();
  const revisionOne = draftPayload({
    clientDraftId: ids.repeated,
    mutation: repeatedMutation,
  });
  const created = await post('/api/compose/draft', revisionOne);
  const repeatedMutationResponse = await post('/api/compose/draft', revisionOne);
  assert.equal(repeatedMutationResponse.client_draft_id, created.client_draft_id);
  const sameRevision = await post('/api/compose/draft', {
    ...revisionOne,
    mutation_id: mutationId(),
  });
  assert.equal(sameRevision.client_draft_id, created.client_draft_id);
  const updated = await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.repeated,
    revision: 2,
    subject: 'Generated provider draft revision two',
  }));
  assert.equal(updated.client_draft_id, created.client_draft_id);
  assert.equal(updated.state, 'synced');
  let snapshot = await audit();
  assert.equal(snapshot.counters.draft_upsert_requests, 4);
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.provider_draft_updates, 1);
  assert.equal(snapshot.counters.same_mutation_replays, 1);
  assert.equal(snapshot.counters.same_revision_replays, 1);
  assert.equal(snapshot.counters.live_provider_drafts, 1);
  assertExpectedFlowSafety(snapshot);
  results.repeated_autosave = snapshot.counters;

  // Mutation IDs and revision payloads are immutable, while stale revisions
  // cannot overwrite a newer provider draft.
  await reset('clean');
  const immutableMutation = mutationId();
  const immutableRevisionOne = draftPayload({
    clientDraftId: ids.immutable,
    mutation: immutableMutation,
  });
  await post('/api/compose/draft', immutableRevisionOne);
  await post('/api/compose/draft', {
    ...immutableRevisionOne,
    subject: 'Changed under the same mutation',
  }, { expectedStatus: 409 });
  await post('/api/compose/draft', {
    ...immutableRevisionOne,
    mutation_id: mutationId(),
    subject: 'Changed under the same revision',
  }, { expectedStatus: 409 });
  await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.immutable,
    revision: 2,
  }));
  await post('/api/compose/draft', {
    ...immutableRevisionOne,
    mutation_id: mutationId(),
  }, { expectedStatus: 409 });
  snapshot = await audit();
  assert.equal(snapshot.counters.draft_upsert_requests, 5);
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.provider_draft_updates, 1);
  assert.equal(snapshot.counters.mutation_conflicts, 1);
  assert.equal(snapshot.counters.immutable_revision_conflicts, 1);
  assert.equal(snapshot.counters.stale_revision_rejections, 1);
  assertExpectedFlowSafety(snapshot);
  results.immutable_operations = snapshot.counters;

  // The first accepted mutation persists before its HTTP connection is lost.
  // Retrying the identical mutation returns the one provider identity.
  await reset('lost-response');
  const lostMutation = mutationId();
  const lostPayload = draftPayload({
    clientDraftId: ids.lost,
    mutation: lostMutation,
  });
  await assert.rejects(
    fetch(`${baseUrl}/api/compose/draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lostPayload),
    }),
    error => error instanceof TypeError,
  );
  const recoveredLost = await post('/api/compose/draft', lostPayload);
  assert.equal(recoveredLost.state, 'synced');
  snapshot = await audit();
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.provider_draft_updates, 0);
  assert.equal(snapshot.counters.lost_responses_after_persist, 1);
  assert.equal(snapshot.counters.retries_after_lost_response, 1);
  assert.equal(snapshot.counters.same_mutation_replays, 1);
  assertExpectedFlowSafety(snapshot);
  results.lost_response = snapshot.counters;

  // Full owned detail preserves attachment bytes through reload and continues
  // updating the same provider draft identity.
  await reset('clean');
  const attachmentBytes = Buffer.from('generated attachment bytes\n', 'utf8');
  const attachment = {
    filename: 'generated-note.txt',
    content_type: 'text/plain',
    data_base64: attachmentBytes.toString('base64'),
  };
  const attachmentCreated = await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.attachment,
    attachments: [attachment],
  }));
  const rehydrated = await get(
    `/api/compose/drafts/by-client-id/${ids.attachment}`,
  );
  assert.equal(rehydrated.client_draft_id, attachmentCreated.client_draft_id);
  assert.equal(rehydrated.attachments[0].size_bytes, attachmentBytes.length);
  assert.match(rehydrated.attachments[0].attachment_id, /^[0-9a-f-]{36}$/);
  assert.match(rehydrated.attachments[0].sha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(
    Buffer.from(rehydrated.attachments[0].data_base64, 'base64'),
    attachmentBytes,
  );
  const attachmentUpdated = await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.attachment,
    revision: 2,
    subject: 'Generated attachment after reload',
    attachments: [attachment],
  }));
  assert.equal(attachmentUpdated.client_draft_id, attachmentCreated.client_draft_id);
  snapshot = await audit();
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.provider_draft_updates, 1);
  assert.equal(snapshot.counters.draft_get_requests, 1);
  assert.equal(snapshot.counters.attachment_rehydrates, 1);
  assert.equal(snapshot.counters.attachment_bytes_rehydrated, attachmentBytes.length);
  assertExpectedFlowSafety(snapshot);
  results.reload_attachment = snapshot.counters;

  // Reply metadata is derived from the owned source. Foreign/mismatched
  // provenance and cross-account reuse are rejected before provider mutation.
  await reset('clean');
  await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.provenance,
    sourceEmailId: 1301,
    threadId: 'wrong-generated-thread',
  }), { expectedStatus: 422 });
  const provenanceCreated = await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.provenance,
    sourceEmailId: 1301,
  }));
  const provenanceDetail = await get(
    `/api/compose/drafts/by-client-id/${ids.provenance}`,
  );
  assert.equal(provenanceDetail.thread_id, 'generated-source-thread-a');
  assert.equal(provenanceDetail.in_reply_to, '<generated-parent-a@example.test>');
  assert.equal(
    provenanceDetail.references,
    '<generated-root-a@example.test> <generated-parent-a@example.test>',
  );
  await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.provenance,
    revision: 2,
    accountId: 1102,
  }), { expectedStatus: 409 });
  snapshot = await audit();
  assert.equal(snapshot.counters.provenance_checks, 2);
  assert.equal(snapshot.counters.provenance_rejections, 1);
  assert.equal(snapshot.counters.account_conflicts, 1);
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.provider_draft_updates, 0);
  assert.match(snapshot.logical_drafts[0].provider_draft_id_hash, /^[0-9a-f]{64}$/);
  assert.equal(provenanceCreated.client_draft_id, ids.provenance);
  assertExpectedFlowSafety(snapshot);
  results.provenance_account = snapshot.counters;

  // Hold User A's persisted response, authenticate as B, then release it.
  // B cannot look up A's UUID and the fixture records the stale response.
  await reset('held-session');
  const heldPayload = draftPayload({ clientDraftId: ids.held });
  const heldPromise = fetch(`${baseUrl}/api/compose/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(heldPayload),
  }).then(async response => ({ status: response.status, body: await response.json() }));
  await waitFor(async () => {
    const current = await audit();
    return current.counters.held_responses === 1;
  }, 'User A draft response was not held');
  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  await post('/api/qa/release-held');
  const heldResult = await heldPromise;
  assert.equal(heldResult.status, 200);
  assert.equal(heldResult.body.client_draft_id, ids.held);
  await request(
    'GET',
    `/api/compose/drafts/by-client-id/${ids.held}`,
    undefined,
    { expectedStatus: 404 },
  );
  snapshot = await audit();
  assert.equal(snapshot.current_user_id, 9102);
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.held_responses, 1);
  assert.equal(snapshot.counters.stale_session_responses_released, 1);
  assertExpectedFlowSafety(snapshot);
  results.stale_session = snapshot.counters;

  // Discard is staged, replayable, and undo restores the identical provider
  // draft without ever invoking provider delete.
  await reset('clean', { discardWindowMs: 20 });
  const undoCreated = await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.undo,
  }));
  const discardMutation = mutationId();
  const discardPending = await post(
    `/api/compose/drafts/${ids.undo}/discard`,
    { mutation_id: discardMutation },
    { expectedStatus: 202 },
  );
  assert.equal(discardPending.state, 'discard_pending');
  assert.equal(discardPending.can_undo_discard, true);
  await post(
    `/api/compose/drafts/${ids.undo}/discard`,
    { mutation_id: discardMutation },
  );
  const undoResponse = await post(
    `/api/compose/drafts/${ids.undo}/undo-discard`,
    { mutation_id: mutationId() },
  );
  assert.equal(undoResponse.state, 'synced');
  assert.equal(undoResponse.client_draft_id, undoCreated.client_draft_id);
  await new Promise(resolve => setTimeout(resolve, 30));
  const afterUndoDeadline = await get(
    `/api/compose/drafts/by-client-id/${ids.undo}`,
  );
  assert.equal(afterUndoDeadline.state, 'synced');
  snapshot = await audit();
  assert.equal(snapshot.counters.discard_replays, 1);
  assert.equal(snapshot.counters.discard_undos, 1);
  assert.equal(snapshot.counters.provider_delete_attempts, 0);
  assert.equal(snapshot.counters.provider_draft_deletes, 0);
  assert.equal(snapshot.counters.live_provider_drafts, 1);
  assertExpectedFlowSafety(snapshot);
  results.discard_undo = snapshot.counters;

  // A fail-before-mutation deletion becomes failed, then one later attempt
  // commits exactly one provider delete. Additional polling is idempotent.
  await reset('delete-fails', { discardWindowMs: 15 });
  await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.deletion,
  }));
  await post(
    `/api/compose/drafts/${ids.deletion}/discard`,
    { mutation_id: mutationId() },
    { expectedStatus: 202 },
  );
  await new Promise(resolve => setTimeout(resolve, 25));
  const failedDelete = await get(
    `/api/compose/drafts/by-client-id/${ids.deletion}`,
  );
  assert.equal(failedDelete.state, 'failed');
  const syncingDelete = await get(
    `/api/compose/drafts/by-client-id/${ids.deletion}`,
  );
  assert.equal(syncingDelete.state, 'syncing');
  const deleted = await get(
    `/api/compose/drafts/by-client-id/${ids.deletion}`,
  );
  assert.equal(deleted.state, 'discarded');
  const stillDeleted = await get(
    `/api/compose/drafts/by-client-id/${ids.deletion}`,
  );
  assert.equal(stillDeleted.state, 'discarded');
  snapshot = await audit();
  assert.equal(snapshot.counters.provider_delete_attempts, 2);
  assert.equal(snapshot.counters.provider_delete_failures, 1);
  assert.equal(snapshot.counters.provider_draft_deletes, 1);
  assert.equal(snapshot.counters.live_provider_drafts, 0);
  assertExpectedFlowSafety(snapshot);
  results.delete_failure = snapshot.counters;

  // Offline rejection does not create a provider draft. The same immutable
  // mutation succeeds once online and full detail restores attachment bytes.
  await reset('offline');
  const offlineBytes = Buffer.from('generated offline attachment\n', 'utf8');
  const offlinePayload = draftPayload({
    clientDraftId: ids.offline,
    attachments: [{
      filename: 'generated-offline.txt',
      content_type: 'text/plain',
      data_base64: offlineBytes.toString('base64'),
    }],
  });
  const offlineResponse = await post(
    '/api/compose/draft',
    offlinePayload,
    { expectedStatus: 503 },
  );
  assert.equal(offlineResponse.state, 'pending');
  let offlineAudit = await audit();
  assert.equal(offlineAudit.counters.provider_draft_creates, 0);
  await post('/api/qa/connectivity', { draft_api: 'online' });
  const onlineSaved = await post('/api/compose/draft', offlinePayload);
  assert.equal(onlineSaved.state, 'synced');
  const offlineRehydrated = await get(
    `/api/compose/drafts/by-client-id/${ids.offline}`,
  );
  assert.deepEqual(
    Buffer.from(offlineRehydrated.attachments[0].data_base64, 'base64'),
    offlineBytes,
  );
  snapshot = await audit();
  assert.equal(snapshot.counters.offline_rejections, 1);
  assert.equal(snapshot.counters.offline_recoveries, 1);
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.live_provider_drafts, 1);
  assertExpectedFlowSafety(snapshot);
  const serializedAudit = JSON.stringify(snapshot);
  assert.doesNotMatch(serializedAudit, /Generated provider draft fixture\./);
  assert.doesNotMatch(serializedAudit, /recipient@example\.test/);
  assert.doesNotMatch(serializedAudit, new RegExp(offlinePayload.attachments[0].data_base64));
  results.offline_recovery = snapshot.counters;

  // Guard behavior is tested in its own reset so expected-flow safety audits
  // remain exactly zero for unknown and external mutations.
  await reset('clean');
  await post('/api/compose/draft', draftPayload({
    clientDraftId: ids.guard,
    to: ['not-generated@example.com'],
  }), { expectedStatus: 422 });
  await post('/api/todos/', { title: 'Generated mutation must be rejected' }, {
    expectedStatus: 405,
  });
  snapshot = await audit();
  assert.equal(snapshot.counters.non_example_test_rejections, 1);
  assert.equal(snapshot.counters.provider_draft_creates, 0);
  assert.equal(snapshot.counters.unexpected_mutations, 1);
  assert.equal(snapshot.counters.external_network_calls, 0);
  results.guard_enforcement = snapshot.counters;

  process.stdout.write(`${JSON.stringify({ passed: true, scenarios: results }, null, 2)}\n`);
} finally {
  await fixture.close();
}
