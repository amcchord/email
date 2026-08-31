import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  applyComposeDraftRoute,
  clearUnscopedComposeStorage,
  composeDraftHasContent,
  composeDraftIntentFromRoute,
  composeLastAccountStorageKey,
  composeDraftStorageKey,
  composeReplyContext,
  createComposeDraftIntent,
  ensureComposeDraftIntent,
  knownServerRevisionRequiresRefresh,
  newComposeIntent,
} from './composeDraft.js';

function uuidFactory() {
  let counter = 0;
  return () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
}

test('new, reply, thread, and forward drafts use isolated local keys', () => {
  const keys = [
    composeDraftStorageKey(7, null),
    composeDraftStorageKey(7, { in_reply_to: '<generated-reply@example.test>' }),
    composeDraftStorageKey(7, { thread_id: 'generated-thread-12' }),
    composeDraftStorageKey(7, { draft_key: 'forward:1:313' }),
  ];

  assert.equal(new Set(keys).size, keys.length);
  assert.equal(keys[0], 'composeLocalDraftV3:user:7:new');
  assert.ok(keys.every(key => key.startsWith('composeLocalDraftV3:user:7:')));
  assert.notEqual(composeDraftStorageKey(8, null), keys[0]);
  assert.equal(composeLastAccountStorageKey(7), 'composeLastAccountV2:user:7');
});

test('draft key normalization bounds storage identifiers without merging intent types', () => {
  const forward = composeDraftStorageKey('generated-user', { draft_key: `forward:${'a/b '.repeat(100)}` });
  const reply = composeDraftStorageKey('generated-user', { draft_key: `reply:${'a/b '.repeat(100)}` });

  assert.ok(forward.length <= 'composeLocalDraftV3:user:generated-user:'.length + 240);
  assert.doesNotMatch(forward, /[ /]/);
  assert.notEqual(forward, reply);
});

test('draft and sender keys fail closed without a validated authenticated user', () => {
  for (const invalidUserId of [null, undefined, '', '../shared', 'two users', {}, -1]) {
    assert.equal(composeDraftStorageKey(invalidUserId, null), null);
    assert.equal(composeLastAccountStorageKey(invalidUserId), null);
  }
});

test('unscoped cleanup removes V1 and V2 content while preserving scoped V3 drafts', () => {
  const values = new Map([
    ['composeLocalDraftV1', 'old-global-draft'],
    ['composeLocalDraftV2:new', 'old-global-new-draft'],
    ['composeLocalDraftV2:reply:generated', 'old-global-reply'],
    ['composeLastAccountId', '91'],
    ['composeLocalDraftV3:user:7:new', 'scoped-draft'],
    ['composeLastAccountV2:user:7', '92'],
    ['unrelatedPreference', 'preserved'],
  ]);
  const storage = {
    get length() { return values.size; },
    key(index) { return [...values.keys()][index] ?? null; },
    removeItem(key) { values.delete(key); },
  };

  clearUnscopedComposeStorage(storage);

  assert.deepEqual([...values.entries()], [
    ['composeLocalDraftV3:user:7:new', 'scoped-draft'],
    ['composeLastAccountV2:user:7', '92'],
    ['unrelatedPreference', 'preserved'],
  ]);
});

test('reply metadata alone keeps a handoff draft recoverable', () => {
  assert.equal(composeDraftHasContent({}), false);
  assert.equal(composeDraftHasContent({ body_html: '<p>Generated draft</p>' }), true);
  assert.equal(composeDraftHasContent({ in_reply_to: '<generated@example.test>' }), true);
  assert.equal(composeDraftHasContent({ thread_id: 'generated-thread' }), true);
  assert.equal(composeDraftHasContent({ source_email_id: 301 }), true);

  assert.deepEqual(composeReplyContext({
    in_reply_to: '<generated@example.test>',
    thread_id: 'generated-thread',
    source_email_id: 301,
  }), {
    in_reply_to: '<generated@example.test>',
    references: '<generated@example.test>',
    thread_id: 'generated-thread',
    source_email_id: 301,
  });
});

test('new compose intents are stable per object and distinct per invocation', () => {
  const randomUUID = uuidFactory();
  const first = newComposeIntent({}, { randomUUID });
  const second = newComposeIntent({}, { randomUUID });
  const retained = createComposeDraftIntent(first, { randomUUID });

  assert.notEqual(first.client_draft_id, second.client_draft_id);
  assert.equal(first.client_draft_id, retained.client_draft_id);
  assert.equal(first.intent_key, `new:${first.client_draft_id}`);
  assert.equal(first.draft_key, `client:${first.client_draft_id}`);
});

test('prefilled new-message callers receive isolated identities before routing', () => {
  const randomUUID = uuidFactory();
  const first = ensureComposeDraftIntent({ subject: 'Generated A' }, { randomUUID });
  const second = ensureComposeDraftIntent({ subject: 'Generated B' }, { randomUUID });
  assert.notEqual(first.client_draft_id, second.client_draft_id);
  assert.notEqual(first.intent_key, second.intent_key);

  const reply = ensureComposeDraftIntent({ draft_key: 'reply:2:42', subject: 'Reply' }, { randomUUID });
  assert.equal(reply.intent_key, 'reply:2:42');
});

test('Compose deep links retain only a valid stable draft identity', () => {
  const id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const intent = composeDraftIntentFromRoute(id.toUpperCase());
  assert.equal(intent.client_draft_id, id);
  assert.equal(intent.draft_key, `client:${id}`);
  assert.equal(composeDraftIntentFromRoute('not-a-draft'), null);

  const composeUrl = applyComposeDraftRoute(
    new URL('https://mail.example.test/?page=compose'),
    'compose',
    intent,
  );
  assert.equal(composeUrl.searchParams.get('draft'), id);
  const inboxUrl = applyComposeDraftRoute(composeUrl, 'inbox', intent);
  assert.equal(inboxUrl.searchParams.has('draft'), false);
});

test('a newer revision advertised by Working Drafts forces authoritative comparison', () => {
  assert.equal(knownServerRevisionRequiresRefresh(
    { known_server_revision: 10 },
    { revision: 2 },
  ), true);
  assert.equal(knownServerRevisionRequiresRefresh(
    { known_server_revision: 2 },
    { revision: 2 },
  ), false);
  assert.equal(knownServerRevisionRequiresRefresh({}, { revision: 2 }), false);
});

test('attachment-only snapshots remain recoverable', () => {
  assert.equal(composeDraftHasContent({ to: [], cc: [], bcc: [] }), false);
  assert.equal(composeDraftHasContent({ to: [''] }), false);
  assert.equal(composeDraftHasContent({ to: ['generated@example.test'] }), true);
  assert.equal(composeDraftHasContent({ attachments: [] }), false);
  assert.equal(composeDraftHasContent({ attachments: [{ filename: 'generated.txt' }] }), true);
});

test('Compose persists the latest edit before navigation disposes its session guard', async () => {
  const text = await readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8');
  const cleanup = text.match(/return \(\) => \{([\s\S]*?)\n\s*\};\n\s*\}\);/)?.[1] || '';

  assert.ok(cleanup.includes('if (autosaveReady) persistLocalDraft();'));
  assert.ok(cleanup.indexOf('persistLocalDraft()') < cleanup.indexOf('composeData.set(null)'));
  assert.ok(cleanup.indexOf('persistLocalDraft()') < cleanup.indexOf('sessionGuard?.dispose()'));
  assert.doesNotMatch(text, /onDestroy\(/);
});

test('Compose owns one durable, attachment-complete draft through send handoff', async () => {
  const text = await readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8');
  const releaseEditor = text.match(/const releaseEditor = \(\) => \{([\s\S]*?)\n\s*\};\n\s*try \{/)?.[1] || '';

  assert.match(text, /createIndexedDbDraftStorage\(\)/);
  assert.match(text, /migrateLegacyScopedDrafts\(\{/);
  assert.match(text, /createDraftSessionController\(\{/);
  assert.match(text, /const intent = ensureComposeDraftIntent\(data\);/);
  assert.match(text, /if \(data\?\.client_draft_id !== intent\.client_draft_id\) composeData\.set\(intent\);/);
  assert.match(text, /draftState\.discardInProgress/);
  assert.match(text, /draftState\.sending/);
  assert.match(text, /let draftLocked = \$derived\(\s*sending/);
  assert.match(text, /Boolean\(autosaveStatus\)/);
  assert.match(text, /const input = event\.currentTarget;/);
  assert.match(text, /const ownerController = draftController;/);
  assert.match(text, /draftController === ownerController/);
  assert.match(text, /ownerController\.completeAttachmentImport/);
  assert.doesNotMatch(text, /draftController\.completeAttachmentImport/);
  assert.match(text, /activeDraftKey = state\.clientDraftId \|\| intent\.client_draft_id;/);
  assert.match(text, /client_draft_id: activeDraftKey,/);
  assert.match(text, /markSendUncertain\(operation\)/);
  assert.doesNotMatch(text, /await[\s\S]{0,1000}event\.currentTarget\.value/);
  assert.match(text, /Attachments are stored with this draft and restored when you return\./);
  assert.match(text, /const restoreDraft = \{\s*\.\.\.data,[\s\S]*attachments: attachments\.map/);
  assert.match(text, /await submitOutboundSend\(data, \{[\s\S]*onAccepted: acceptedOperation => \{[\s\S]*releaseEditor\(acceptedOperation\);[\s\S]*onRestore: restoreEditor/);
  assert.match(text, /onSent: forgetSentDraft/);
  assert.doesNotMatch(releaseEditor, /durableStorage|\.delete\(/);
  assert.match(text, /recovery_source_client_draft_id/);
  assert.match(text, /await durableStorage\.delete\(sessionGuard\.userId, recoverySourceClientId\)/);
  assert.match(text, /if \(replyContext\.source_email_id\) data\.source_email_id = replyContext\.source_email_id;/);
  assert.match(text, /attachments = Array\.isArray\(draft\.attachments\)/);
  assert.match(text, /attachments: attachments\.map\(item => \(\{ \.\.\.item \}\)\)/);
  assert.match(text, /recipientFieldValue\(draft\.to\)/);
  assert.match(text, /recipientFieldValue\(draft\.cc\)/);
  assert.match(text, /recipientFieldValue\(draft\.bcc\)/);
  assert.match(text, /client_draft_id: capturedDraftKey,/);
  assert.match(text, /draft_revision: capturedDraftRevision,/);
  assert.match(text, /draftController\?\.revision !== capturedDraftRevision/);
  assert.match(text, /source_email_id: replyContext\.source_email_id,/);
  assert.doesNotMatch(text, /localStorage\.setItem\(activeDraftKey/);
  assert.doesNotMatch(text, /await api\.sendEmail\(/);
  assert.doesNotMatch(text, /window\.confirm\(/);
  assert.match(text, /aria-labelledby="draft-conflict-title"/);
  assert.match(text, /role="dialog"/);
  assert.match(text, /aria-modal="true"/);
  assert.match(text, /conflictCancelButton\?\.focus\(\)/);
  assert.match(text, /bind:element=\{conflictCancelButton\}/);
  assert.match(text, /event\.key === 'Escape'/);
  assert.match(text, /event\.key !== 'Tab'/);
  assert.match(text, /conflictTrigger\?\.isConnected \? conflictTrigger : conflictFallbackFocus/);
  assert.match(text, /restoreTarget\.focus\(\{ preventScroll: true \}\)/);
  assert.match(text, /bind:this=\{conflictFallbackFocus\}/);
  assert.match(text, />Keep this version</);
  assert.match(text, />Use server version</);
});
