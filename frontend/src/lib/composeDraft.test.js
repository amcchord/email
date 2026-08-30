import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  clearUnscopedComposeStorage,
  composeDraftHasContent,
  composeLastAccountStorageKey,
  composeDraftStorageKey,
  composeReplyContext,
} from './composeDraft.js';

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

test('Compose persists the latest edit before navigation disposes its session guard', async () => {
  const text = await readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8');
  const cleanup = text.match(/return \(\) => \{([\s\S]*?)\n\s*\};\n\s*\}\);/)?.[1] || '';

  assert.ok(cleanup.includes('if (autosaveReady) persistLocalDraft();'));
  assert.ok(cleanup.indexOf('persistLocalDraft()') < cleanup.indexOf('composeData.set(null)'));
  assert.ok(cleanup.indexOf('persistLocalDraft()') < cleanup.indexOf('sessionGuard?.dispose()'));
  assert.doesNotMatch(text, /onDestroy\(/);
});

test('Compose hands one restorable draft to the durable send controller', async () => {
  const text = await readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8');

  assert.match(text, /const restoreDraft = \{\s*\.\.\.data,[\s\S]*attachments: attachments\.map/);
  assert.match(text, /await submitOutboundSend\(data, \{[\s\S]*onAccepted: releaseEditor,[\s\S]*onRestore: restoreEditor/);
  assert.match(text, /if \(replyContext\.source_email_id\) data\.source_email_id = replyContext\.source_email_id;/);
  assert.match(text, /if \(Array\.isArray\(data\.attachments\)\) attachments = data\.attachments;/);
  assert.match(text, /recipientFieldValue\(data\.to\)/);
  assert.match(text, /recipientFieldValue\(data\.cc\)/);
  assert.match(text, /recipientFieldValue\(data\.bcc\)/);
  assert.match(text, /const capturedDraftKey = activeDraftKey;/);
  assert.match(text, /const capturedDraftFingerprint = persistedDraftFingerprint\(draftSnapshot\(\)\);/);
  assert.match(text, /removeCapturedDraftIfUnchanged\(capturedDraftKey, capturedDraftFingerprint\);\s*if \(!sessionGuard\?\.isCurrent\(\)\) return;/);
  assert.match(text, /persistedDraftFingerprint\(stored\) === fingerprint/);
  assert.match(text, /source_email_id: replyContext\.source_email_id,/);
  assert.doesNotMatch(text, /await api\.sendEmail\(/);
});
