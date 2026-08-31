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
  mailboxA: '00000000-0000-4000-8000-000000000111',
  mailboxB: '00000000-0000-4000-8000-000000000112',
  sourceRace: '00000000-0000-4000-8000-000000000113',
  personalSnippet: '00000000-0000-4000-8000-000000000114',
  personalSnippetConflict: '00000000-0000-4000-8000-000000000115',
  followUp: '00000000-0000-4000-8000-000000000116',
  followUpSend: '00000000-0000-4000-8000-000000000117',
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
  followUpReminder = 'default',
  followUpTimeZone = 'America/New_York',
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
    follow_up_reminder: followUpReminder,
    follow_up_time_zone: followUpTimeZone,
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
  const responseText = await response.text();
  const payload = responseText ? JSON.parse(responseText) : null;
  assert.equal(
    response.status,
    expectedStatus,
    `${method} ${pathname}: ${JSON.stringify(payload)}`,
  );
  return payload;
}

const get = pathname => request('GET', pathname);
const post = (pathname, body = {}, options = {}) => request('POST', pathname, body, options);
const put = (pathname, body = {}, options = {}) => request('PUT', pathname, body, options);
const del = (pathname, options = {}) => request('DELETE', pathname, undefined, options);
const postDraft = (body, options = {}) => post(
  '/api/compose/draft',
  body,
  { expectedStatus: 202, ...options },
);

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
  // Account defaults remain off until an explicit revisioned save. A custom
  // 4-day policy round-trips, and the exact draft choice reaches send
  // admission without any external provider or network call.
  await reset('clean');
  let policies = await get('/api/follow-up/policies');
  assert.equal(policies.total, 2);
  assert.equal(policies.accounts[0].enabled, false);
  assert.equal(policies.accounts[0].revision, 0);
  const savedPolicy = await put('/api/follow-up/policies/1101', {
    enabled: true,
    delay_days: 4,
    wake_local_time: '08:30',
    time_zone: 'America/New_York',
    weekdays_only: true,
    expected_revision: 0,
  });
  assert.equal(savedPolicy.revision, 1);
  assert.equal(savedPolicy.delay_days, 4);
  const replayedPolicy = await put('/api/follow-up/policies/1101', {
    enabled: true,
    delay_days: 4,
    wake_local_time: '08:30',
    time_zone: 'America/New_York',
    weekdays_only: true,
    expected_revision: 0,
  });
  assert.deepEqual(replayedPolicy, savedPolicy);
  await put('/api/follow-up/policies/1101', {
    enabled: false,
    delay_days: 4,
    wake_local_time: '08:30',
    time_zone: 'America/New_York',
    weekdays_only: true,
    expected_revision: 0,
  }, { expectedStatus: 409 });
  const followUpDraftPayload = draftPayload({
    clientDraftId: ids.followUp,
    followUpReminder: 'default',
    followUpTimeZone: 'America/New_York',
  });
  await postDraft(followUpDraftPayload);
  const reopenedFollowUp = await get(
    `/api/compose/drafts/by-client-id/${ids.followUp}`,
  );
  assert.equal(reopenedFollowUp.follow_up_reminder, 'default');
  assert.equal(reopenedFollowUp.follow_up_time_zone, 'America/New_York');
  const followUpSend = await post('/api/compose/send', {
    ...followUpDraftPayload,
    mutation_id: undefined,
    revision: undefined,
    is_draft: undefined,
    idempotency_key: ids.followUpSend,
    client_draft_id: ids.followUp,
    draft_revision: 1,
  }, { expectedStatus: 202 });
  assert.equal(followUpSend.follow_up_requested, true);
  const cancelledFollowUp = await post(
    `/api/compose/sends/${followUpSend.send_id}/undo`,
    {},
  );
  assert.equal(cancelledFollowUp.state, 'cancelled');
  let snapshot = await audit();
  assert.equal(snapshot.counters.follow_up_policy_reads, 1);
  assert.equal(snapshot.counters.follow_up_policy_writes, 1);
  assert.equal(snapshot.counters.follow_up_policy_conflicts, 1);
  assert.equal(snapshot.counters.follow_up_requested_sends, 1);
  assert.equal(snapshot.logical_outbounds[0].follow_up_requested, true);
  assert.equal(snapshot.logical_outbounds[0].state, 'cancelled');
  assertExpectedFlowSafety(snapshot);
  results.follow_up = snapshot.counters;

  // Recipient suggestions are account-scoped, de-duplicated across current
  // and legacy history shapes, exclude every owned address, and never cross
  // the generated authenticated-user boundary.
  await reset('clean');
  const primaryRecipients = await get(
    '/api/compose/recipients?account_id=1101&q=&limit=20',
  );
  assert.deepEqual(primaryRecipients.suggestions.map(item => item.address), [
    'ada.correspondent@example.test',
    'casey.duplicate@example.test',
    'legacy-string@example.test',
  ]);
  assert.deepEqual(primaryRecipients.suggestions[0], {
    name: 'Lovelace, Ada',
    address: 'ada.correspondent@example.test',
    formatted: '"Lovelace, Ada" <ada.correspondent@example.test>',
  });
  assert.equal(
    primaryRecipients.suggestions.filter(item => item.address === 'casey.duplicate@example.test').length,
    1,
  );
  assert.equal(
    primaryRecipients.suggestions.find(item => item.address === 'casey.duplicate@example.test').name,
    'Casey Current',
  );

  const legacyRecipient = await get(
    '/api/compose/recipients?account_id=1101&query=legacy&limit=8',
  );
  assert.deepEqual(legacyRecipient.suggestions, [{
    name: 'Legacy String Recipient',
    address: 'legacy-string@example.test',
    formatted: 'Legacy String Recipient <legacy-string@example.test>',
  }]);
  const ownedRecipientDecoys = await get(
    '/api/compose/recipients?account_id=1101&q=sender&limit=20',
  );
  assert.deepEqual(ownedRecipientDecoys.suggestions, []);
  const alternateAccountRecipients = await get(
    '/api/compose/recipients?account_id=1102&q=&limit=20',
  );
  assert.deepEqual(alternateAccountRecipients.suggestions, [{
    name: 'Alternate Account Only',
    address: 'alternate-only@example.test',
    formatted: 'Alternate Account Only <alternate-only@example.test>',
  }]);
  await request(
    'GET',
    '/api/compose/recipients?account_id=1201&q=',
    undefined,
    { expectedStatus: 404 },
  );
  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  const userBRecipients = await get(
    '/api/compose/recipients?account_id=1201&q=&limit=20',
  );
  assert.deepEqual(userBRecipients.suggestions, [{
    name: 'User B Private Decoy',
    address: 'user-b-only@example.test',
    formatted: 'User B Private Decoy <user-b-only@example.test>',
  }]);
  assert.ok(!primaryRecipients.suggestions.some(item => item.address === 'user-b-only@example.test'));
  let recipientSnapshot = await audit();
  assert.equal(recipientSnapshot.counters.recipient_lookup_requests, 6);
  assert.equal(recipientSnapshot.counters.recipient_lookup_successes, 5);
  assert.equal(recipientSnapshot.counters.recipient_lookup_account_rejections, 1);
  assert.equal(recipientSnapshot.counters.recipient_lookup_failures, 0);
  assertExpectedFlowSafety(recipientSnapshot);
  const serializedRecipientAudit = JSON.stringify(recipientSnapshot);
  assert.doesNotMatch(serializedRecipientAudit, /ada\.correspondent|legacy-string|user-b-only/i);
  assert.doesNotMatch(serializedRecipientAudit, /Lovelace|Casey Current|Private Decoy/);
  results.recipient_directory = recipientSnapshot.counters;

  await reset('recipient-delay');
  const delayedRecipients = await get(
    '/api/compose/recipients?account_id=1101&q=ada&limit=8',
  );
  assert.equal(delayedRecipients.suggestions[0].address, 'ada.correspondent@example.test');
  recipientSnapshot = await audit();
  assert.equal(recipientSnapshot.counters.recipient_lookup_requests, 1);
  assert.equal(recipientSnapshot.counters.recipient_lookup_successes, 1);
  assert.equal(recipientSnapshot.counters.recipient_lookup_delays, 1);
  assertExpectedFlowSafety(recipientSnapshot);
  results.recipient_delay = recipientSnapshot.counters;

  await reset('recipient-fails');
  const failedRecipients = await request(
    'GET',
    '/api/compose/recipients?account_id=1101&q=ada&limit=8',
    undefined,
    { expectedStatus: 503 },
  );
  assert.equal(failedRecipients.detail.code, 'recipient_lookup_unavailable');
  recipientSnapshot = await audit();
  assert.equal(recipientSnapshot.counters.recipient_lookup_requests, 1);
  assert.equal(recipientSnapshot.counters.recipient_lookup_successes, 0);
  assert.equal(recipientSnapshot.counters.recipient_lookup_failures, 1);
  assertExpectedFlowSafety(recipientSnapshot);
  results.recipient_failure = recipientSnapshot.counters;

  // Hold a User A lookup across an auth transition. Its generated response is
  // still the captured A response, while the active B session can retrieve
  // only its own account; the application must ignore the stale A result.
  await reset('recipient-held-session');
  const heldRecipientPromise = fetch(
    `${baseUrl}/api/compose/recipients?account_id=1101&q=ada&limit=8`,
  ).then(async response => ({ status: response.status, body: await response.json() }));
  await waitFor(async () => {
    const current = await audit();
    return current.counters.recipient_lookup_held === 1;
  }, 'User A recipient response was not held');
  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  await post('/api/qa/release-held');
  const heldRecipientResult = await heldRecipientPromise;
  assert.equal(heldRecipientResult.status, 200);
  assert.equal(
    heldRecipientResult.body.suggestions[0].address,
    'ada.correspondent@example.test',
  );
  const activeUserBRecipients = await get(
    '/api/compose/recipients?account_id=1201&q=private&limit=8',
  );
  assert.equal(activeUserBRecipients.suggestions[0].address, 'user-b-only@example.test');
  recipientSnapshot = await audit();
  assert.equal(recipientSnapshot.current_user_id, 9102);
  assert.equal(recipientSnapshot.counters.recipient_lookup_requests, 2);
  assert.equal(recipientSnapshot.counters.recipient_lookup_successes, 2);
  assert.equal(recipientSnapshot.counters.recipient_lookup_delays, 1);
  assert.equal(recipientSnapshot.counters.recipient_lookup_held, 1);
  assert.equal(recipientSnapshot.counters.recipient_lookup_stale_session_responses, 1);
  assert.equal(recipientSnapshot.counters.stale_session_responses_released, 1);
  assertExpectedFlowSafety(recipientSnapshot);
  results.recipient_stale_session = recipientSnapshot.counters;

  // Hold the first User A snippet list across an A-to-B auth transition. The
  // released payload remains the captured A contract, while a subsequent list
  // sees only B's snippets. Audit output contains counts, never snippet bodies.
  await reset('snippet-held-session');
  const heldSnippetPromise = fetch(
    `${baseUrl}/api/compose/snippets`,
  ).then(async response => ({ status: response.status, body: await response.json() }));
  await waitFor(async () => {
    const current = await audit();
    return current.counters.snippet_list_held_requests === 1;
  }, 'User A snippet list response was not held');
  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  const releasedSnippets = await post('/api/qa/release-held');
  assert.equal(releasedSnippets.released, 1);
  const heldSnippetResult = await heldSnippetPromise;
  assert.equal(heldSnippetResult.status, 200);
  assert.equal(heldSnippetResult.body.total, 2);
  assert.equal(heldSnippetResult.body.limit, 250);
  assert.deepEqual(
    heldSnippetResult.body.snippets.map(item => item.shortcut),
    ['follow-up', 'intro'],
  );
  assert.ok(!heldSnippetResult.body.snippets.some(item => item.shortcut === 'response'));
  const activeUserBSnippets = await get('/api/compose/snippets');
  assert.equal(activeUserBSnippets.total, 1);
  assert.equal(activeUserBSnippets.snippets[0].shortcut, 'response');

  let snippetSessionSnapshot = await audit();
  assert.equal(snippetSessionSnapshot.current_user_id, 9102);
  assert.equal(snippetSessionSnapshot.counters.snippet_list_requests, 2);
  assert.equal(snippetSessionSnapshot.counters.snippet_list_held_requests, 1);
  assert.equal(snippetSessionSnapshot.counters.snippet_list_stale_session_responses, 1);
  assert.equal(snippetSessionSnapshot.counters.snippet_list_releases, 1);
  assert.equal(snippetSessionSnapshot.counters.stale_session_responses_released, 1);
  assertExpectedFlowSafety(snippetSessionSnapshot);
  const serializedSnippetSessionAudit = JSON.stringify(snippetSessionSnapshot);
  assert.doesNotMatch(serializedSnippetSessionAudit, /Hello from the generated snippet fixture/);
  assert.doesNotMatch(serializedSnippetSessionAudit, /Following up with generated-only content/);
  assert.doesNotMatch(serializedSnippetSessionAudit, /This response belongs only to generated user B/);
  assert.doesNotMatch(serializedSnippetSessionAudit, /"(?:name|shortcut|body_html|body_text)":/);
  results.snippet_stale_session = snippetSessionSnapshot.counters;

  // Reset re-arms the one-shot hold and terminates any pending response. The
  // next clean state must contain neither held state nor its prior counters.
  await reset('snippet-held-session');
  const resetHeldSnippetPromise = fetch(
    `${baseUrl}/api/compose/snippets`,
  ).then(async response => ({ status: response.status, body: await response.json() }));
  await waitFor(async () => {
    const current = await audit();
    return current.counters.snippet_list_held_requests === 1;
  }, 'Snippet list hold was not re-armed after reset');
  await reset('clean');
  const resetHeldSnippetResult = await resetHeldSnippetPromise;
  assert.equal(resetHeldSnippetResult.status, 409);
  assert.equal(resetHeldSnippetResult.body.detail.code, 'qa_reset');
  snippetSessionSnapshot = await audit();
  assert.equal(snippetSessionSnapshot.scenario, 'clean');
  assert.equal(snippetSessionSnapshot.counters.snippet_list_requests, 0);
  assert.equal(snippetSessionSnapshot.counters.snippet_list_held_requests, 0);
  assert.equal(snippetSessionSnapshot.counters.snippet_list_stale_session_responses, 0);
  assert.equal(snippetSessionSnapshot.counters.snippet_list_releases, 0);
  assert.equal(snippetSessionSnapshot.counters.stale_session_responses_released, 0);
  assertExpectedFlowSafety(snippetSessionSnapshot);

  // Personal Snippets are seeded per generated user, owner-scoped, revisioned,
  // replay-safe, and delete-idempotent. Their audit surface contains only
  // identifiers and revision metadata, never snippet content.
  await reset('clean');
  const seededForA = await get('/api/compose/snippets');
  assert.equal(seededForA.total, 2);
  assert.equal(seededForA.limit, 250);
  assert.ok(seededForA.snippets.every(item => item.shortcut !== 'response'));

  const snippetCreatePayload = {
    snippet_id: ids.personalSnippet,
    name: 'Generated scheduling note',
    shortcut: ';schedule',
    body_html: '<p>Generated private scheduling note.</p>',
    body_text: 'Generated private scheduling note.',
  };
  const createdSnippet = await post(
    '/api/compose/snippets',
    snippetCreatePayload,
    { expectedStatus: 201 },
  );
  assert.equal(createdSnippet.shortcut, 'schedule');
  assert.equal(createdSnippet.revision, 1);
  const replayedCreate = await post('/api/compose/snippets', snippetCreatePayload);
  assert.deepEqual(replayedCreate, createdSnippet);
  await post('/api/compose/snippets', {
    ...snippetCreatePayload,
    name: 'Divergent request-id reuse',
  }, { expectedStatus: 409 });
  await post('/api/compose/snippets', {
    ...snippetCreatePayload,
    snippet_id: ids.personalSnippetConflict,
    shortcut: 'intro',
  }, { expectedStatus: 409 });

  const snippetRevisionTwo = {
    name: 'Generated scheduling note updated',
    shortcut: 'schedule',
    body_html: '<p>Generated private scheduling note, revised.</p>',
    body_text: 'Generated private scheduling note, revised.',
    expected_revision: 1,
  };
  const updatedSnippet = await put(
    `/api/compose/snippets/${ids.personalSnippet}`,
    snippetRevisionTwo,
  );
  assert.equal(updatedSnippet.revision, 2);
  const replayedUpdate = await put(
    `/api/compose/snippets/${ids.personalSnippet}`,
    snippetRevisionTwo,
  );
  assert.deepEqual(replayedUpdate, updatedSnippet);
  await put(`/api/compose/snippets/${ids.personalSnippet}`, {
    ...snippetRevisionTwo,
    name: 'Stale divergent update',
  }, { expectedStatus: 409 });

  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  const seededForB = await get('/api/compose/snippets');
  assert.equal(seededForB.total, 1);
  assert.equal(seededForB.snippets[0].shortcut, 'response');
  assert.ok(!seededForB.snippets.some(item => item.snippet_id === ids.personalSnippet));
  await put(`/api/compose/snippets/${ids.personalSnippet}`, {
    ...snippetRevisionTwo,
    expected_revision: 2,
  }, { expectedStatus: 404 });
  await del(
    `/api/compose/snippets/${ids.personalSnippet}?expected_revision=2`,
    { expectedStatus: 204 },
  );

  await post('/api/auth/login', {
    username: 'generated-a',
    password: 'generated-only',
  });
  const stillOwnedByA = await get('/api/compose/snippets');
  assert.ok(stillOwnedByA.snippets.some(item => item.snippet_id === ids.personalSnippet));
  await del(
    `/api/compose/snippets/${ids.personalSnippet}?expected_revision=1`,
    { expectedStatus: 409 },
  );
  await del(
    `/api/compose/snippets/${ids.personalSnippet}?expected_revision=2`,
    { expectedStatus: 204 },
  );
  await del(
    `/api/compose/snippets/${ids.personalSnippet}?expected_revision=2`,
    { expectedStatus: 204 },
  );
  const afterSnippetDelete = await get('/api/compose/snippets');
  assert.equal(afterSnippetDelete.total, 2);

  snapshot = await audit();
  assert.equal(snapshot.counters.snippet_create_requests, 4);
  assert.equal(snapshot.counters.snippet_creates, 1);
  assert.equal(snapshot.counters.snippet_create_replays, 1);
  assert.equal(snapshot.counters.snippet_replace_requests, 4);
  assert.equal(snapshot.counters.snippet_updates, 1);
  assert.equal(snapshot.counters.snippet_update_replays, 1);
  assert.equal(snapshot.counters.snippet_delete_requests, 4);
  assert.equal(snapshot.counters.snippet_deletes, 1);
  assert.equal(snapshot.counters.snippet_conflicts, 4);
  assert.equal(snapshot.counters.snippet_not_found, 3);
  assert.equal(snapshot.counters.logical_snippets, 3);
  assertExpectedFlowSafety(snapshot);
  const serializedSnippetAudit = JSON.stringify(snapshot);
  assert.doesNotMatch(serializedSnippetAudit, /Generated private scheduling note/);
  assert.doesNotMatch(serializedSnippetAudit, /Generated introduction/);
  assert.doesNotMatch(serializedSnippetAudit, /"(?:name|shortcut|body_html|body_text)":/);
  results.personal_snippets = snapshot.counters;

  // Repeated autosave: one create, one immutable mutation replay, one same-
  // revision replay under a fresh mutation, and one higher-revision update.
  await reset('clean');
  const repeatedMutation = mutationId();
  const revisionOne = draftPayload({
    clientDraftId: ids.repeated,
    mutation: repeatedMutation,
  });
  const created = await postDraft(revisionOne);
  const repeatedMutationResponse = await postDraft(revisionOne);
  assert.equal(repeatedMutationResponse.client_draft_id, created.client_draft_id);
  const sameRevision = await postDraft({
    ...revisionOne,
    mutation_id: mutationId(),
  });
  assert.equal(sameRevision.client_draft_id, created.client_draft_id);
  const updated = await postDraft(draftPayload({
    clientDraftId: ids.repeated,
    revision: 2,
    subject: 'Generated provider draft revision two',
  }));
  assert.equal(updated.client_draft_id, created.client_draft_id);
  assert.equal(updated.state, 'synced');
  snapshot = await audit();
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
  await postDraft(immutableRevisionOne);
  await postDraft({
    ...immutableRevisionOne,
    subject: 'Changed under the same mutation',
  }, { expectedStatus: 409 });
  await postDraft({
    ...immutableRevisionOne,
    mutation_id: mutationId(),
    subject: 'Changed under the same revision',
  }, { expectedStatus: 409 });
  await postDraft(draftPayload({
    clientDraftId: ids.immutable,
    revision: 2,
  }));
  await postDraft({
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
  const recoveredLost = await postDraft(lostPayload);
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
  const attachmentCreated = await postDraft(draftPayload({
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
  const attachmentUpdated = await postDraft(draftPayload({
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
  await postDraft(draftPayload({
    clientDraftId: ids.provenance,
    sourceEmailId: 1301,
    threadId: 'wrong-generated-thread',
  }), { expectedStatus: 422 });
  const provenanceCreated = await postDraft(draftPayload({
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
  const provenanceBySource = await get(
    '/api/compose/drafts/by-source-email/1301?account_id=1101',
  );
  assert.equal(provenanceBySource.client_draft_id, ids.provenance);
  const recentMetadata = await get('/api/compose/drafts/recent?limit=20');
  assert.equal(recentMetadata.length, 1);
  for (const forbidden of ['to', 'cc', 'bcc', 'subject', 'body_html', 'body_text', 'attachments']) {
    assert.equal(Object.hasOwn(recentMetadata[0], forbidden), false);
  }
  await postDraft(draftPayload({
    clientDraftId: ids.sourceRace,
    sourceEmailId: 1301,
  }), { expectedStatus: 409 });
  const draftMailbox = await get('/api/emails/?mailbox=DRAFTS');
  assert.equal(draftMailbox.emails.length, 1);
  const reopenedByEmail = await get(
    `/api/compose/drafts/by-email/${draftMailbox.emails[0].id}`,
  );
  assert.equal(reopenedByEmail.client_draft_id, ids.provenance);
  await post('/api/auth/login', {
    username: 'generated-b',
    password: 'generated-only',
  });
  await request(
    'GET',
    `/api/compose/drafts/by-email/${draftMailbox.emails[0].id}`,
    undefined,
    { expectedStatus: 404 },
  );
  await request(
    'GET',
    '/api/compose/drafts/by-source-email/1301?account_id=1101',
    undefined,
    { expectedStatus: 404 },
  );
  await post('/api/auth/login', {
    username: 'generated-a',
    password: 'generated-only',
  });
  await request(
    'GET',
    '/api/compose/drafts/by-source-email/1301?account_id=1102',
    undefined,
    { expectedStatus: 404 },
  );
  await postDraft(draftPayload({
    clientDraftId: ids.provenance,
    revision: 2,
    accountId: 1102,
  }), { expectedStatus: 409 });
  snapshot = await audit();
  assert.equal(snapshot.counters.provenance_checks, 3);
  assert.equal(snapshot.counters.provenance_rejections, 1);
  assert.equal(snapshot.counters.account_conflicts, 1);
  assert.equal(snapshot.counters.source_conflicts, 1);
  assert.equal(snapshot.counters.provider_draft_creates, 1);
  assert.equal(snapshot.counters.provider_draft_updates, 0);
  assert.match(snapshot.logical_drafts[0].provider_draft_id_hash, /^[0-9a-f]{64}$/);
  assert.equal(provenanceCreated.client_draft_id, ids.provenance);
  assertExpectedFlowSafety(snapshot);
  results.provenance_account = snapshot.counters;

  // Provider-draft email identities stay stable when an earlier draft is
  // removed. A stale email ID must never retarget a different logical draft.
  await reset('clean', { discardWindowMs: 15 });
  await postDraft(draftPayload({
    clientDraftId: ids.mailboxA,
    subject: 'Generated mailbox draft A',
  }));
  await postDraft(draftPayload({
    clientDraftId: ids.mailboxB,
    subject: 'Generated mailbox draft B',
  }));
  const mailboxBeforeDiscard = await get('/api/emails/?mailbox=DRAFTS');
  const mailboxA = mailboxBeforeDiscard.emails.find(email => email.subject.endsWith('A'));
  const mailboxB = mailboxBeforeDiscard.emails.find(email => email.subject.endsWith('B'));
  assert.ok(mailboxA);
  assert.ok(mailboxB);
  assert.notEqual(mailboxA.id, mailboxB.id);
  await post(
    `/api/compose/drafts/${ids.mailboxA}/discard`,
    { mutation_id: mutationId() },
    { expectedStatus: 202 },
  );
  await new Promise(resolve => setTimeout(resolve, 25));
  await get(`/api/compose/drafts/by-client-id/${ids.mailboxA}`);
  await get(`/api/compose/drafts/by-client-id/${ids.mailboxA}`);
  const mailboxAfterDiscard = await get('/api/emails/?mailbox=DRAFTS');
  assert.deepEqual(mailboxAfterDiscard.emails.map(email => email.id), [mailboxB.id]);
  await request(
    'GET',
    `/api/compose/drafts/by-email/${mailboxA.id}`,
    undefined,
    { expectedStatus: 404 },
  );
  const stableMailboxB = await get(`/api/compose/drafts/by-email/${mailboxB.id}`);
  assert.equal(stableMailboxB.client_draft_id, ids.mailboxB);
  snapshot = await audit();
  assert.equal(snapshot.counters.provider_draft_creates, 2);
  assert.equal(snapshot.counters.provider_draft_deletes, 1);
  assert.equal(snapshot.counters.live_provider_drafts, 1);
  assertExpectedFlowSafety(snapshot);
  results.stable_mailbox_identity = snapshot.counters;

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
  assert.equal(heldResult.status, 202);
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
  const undoCreated = await postDraft(draftPayload({
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
  await postDraft(draftPayload({
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
  const onlineSaved = await postDraft(offlinePayload);
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
  await postDraft(draftPayload({
    clientDraftId: ids.guard,
    to: ['not-generated@example.com'],
  }), { expectedStatus: 422 });
  await postDraft(draftPayload({
    clientDraftId: ids.guard,
    mutation: mutationId(),
    to: ['victim@outside.invalid <safe@example.test>'],
  }), { expectedStatus: 422 });
  await post('/api/todos/', { title: 'Generated mutation must be rejected' }, {
    expectedStatus: 405,
  });
  snapshot = await audit();
  assert.equal(snapshot.counters.non_example_test_rejections, 2);
  assert.equal(snapshot.counters.provider_draft_creates, 0);
  assert.equal(snapshot.counters.unexpected_mutations, 1);
  assert.equal(snapshot.counters.external_network_calls, 0);
  results.guard_enforcement = snapshot.counters;

  process.stdout.write(`${JSON.stringify({ passed: true, scenarios: results }, null, 2)}\n`);
} finally {
  await fixture.close();
}
