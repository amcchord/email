import assert from 'node:assert/strict';
import test from 'node:test';

import {
  composeDraftHasContent,
  composeDraftStorageKey,
  composeReplyContext,
} from './composeDraft.js';

test('new, reply, thread, and forward drafts use isolated local keys', () => {
  const keys = [
    composeDraftStorageKey(null),
    composeDraftStorageKey({ in_reply_to: '<generated-reply@example.test>' }),
    composeDraftStorageKey({ thread_id: 'generated-thread-12' }),
    composeDraftStorageKey({ draft_key: 'forward:1:313' }),
  ];

  assert.equal(new Set(keys).size, keys.length);
  assert.equal(keys[0], 'composeLocalDraftV2:new');
  assert.ok(keys.every(key => key.startsWith('composeLocalDraftV2:')));
});

test('draft key normalization bounds storage identifiers without merging intent types', () => {
  const forward = composeDraftStorageKey({ draft_key: `forward:${'a/b '.repeat(100)}` });
  const reply = composeDraftStorageKey({ draft_key: `reply:${'a/b '.repeat(100)}` });

  assert.ok(forward.length <= 'composeLocalDraftV2:'.length + 240);
  assert.doesNotMatch(forward, /[ /]/);
  assert.notEqual(forward, reply);
});

test('reply metadata alone keeps a handoff draft recoverable', () => {
  assert.equal(composeDraftHasContent({}), false);
  assert.equal(composeDraftHasContent({ body_html: '<p>Generated draft</p>' }), true);
  assert.equal(composeDraftHasContent({ in_reply_to: '<generated@example.test>' }), true);
  assert.equal(composeDraftHasContent({ thread_id: 'generated-thread' }), true);

  assert.deepEqual(composeReplyContext({
    in_reply_to: '<generated@example.test>',
    thread_id: 'generated-thread',
  }), {
    in_reply_to: '<generated@example.test>',
    references: '<generated@example.test>',
    thread_id: 'generated-thread',
  });
});
