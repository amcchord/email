import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createMemoryDraftStorage,
  draftStorageNamespace,
  migrateLegacyScopedDrafts,
} from './draftStorage.js';

function uuidFactory() {
  let counter = 0;
  return () => `10000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
}

function fakeLocalStorage(entries) {
  const values = new Map(entries);
  return {
    get length() { return values.size; },
    key(index) { return [...values.keys()][index] ?? null; },
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, value); },
    removeItem(key) { values.delete(key); },
    values,
  };
}

test('memory storage preserves attachment bytes and isolates authenticated users', async () => {
  const storage = createMemoryDraftStorage();
  const bytes = new Uint8Array([0, 1, 127, 128, 255]);
  await storage.put({
    user_id: 7,
    client_draft_id: '10000000-0000-4000-8000-000000000001',
    intent_key: 'new:generated-one',
    revision: 1,
    status: 'local-only',
    updated_at: '2026-08-30T12:00:00.000Z',
    snapshot: { attachments: [{ filename: 'generated.bin', bytes }] },
  });

  const restored = await storage.get(7, '10000000-0000-4000-8000-000000000001');
  assert.deepEqual([...restored.snapshot.attachments[0].bytes], [...bytes]);
  restored.snapshot.attachments[0].bytes[0] = 99;
  assert.equal((await storage.get(7, restored.client_draft_id)).snapshot.attachments[0].bytes[0], 0);
  assert.equal(await storage.get(8, restored.client_draft_id), null);
  assert.equal(draftStorageNamespace(7, 'reply:account:thread'), 'draft:user:7:intent:reply%3Aaccount%3Athread');
});

test('scoped local drafts migrate only for their authenticated owner after durable storage succeeds', async () => {
  const legacy = fakeLocalStorage([
    ['composeLocalDraftV3:user:7:new', JSON.stringify({
      to: 'generated@example.test',
      body_html: '<p>Generated legacy body</p>',
      saved_at: '2026-08-30T12:00:00.000Z',
    })],
    ['composeLocalDraftV3:user:7:broken', '{not-json'],
    ['composeLocalDraftV3:user:8:new', JSON.stringify({ body_html: '<p>Other user</p>' })],
  ]);
  const storage = createMemoryDraftStorage();
  const result = await migrateLegacyScopedDrafts({
    storage,
    localStorage: legacy,
    userId: 7,
    randomUUID: uuidFactory(),
    now: () => '2026-08-30T12:01:00.000Z',
  });

  assert.equal(result.migrated.length, 1);
  assert.equal(result.failed.length, 1);
  assert.equal(legacy.values.has('composeLocalDraftV3:user:7:new'), false);
  assert.equal(legacy.values.has('composeLocalDraftV3:user:7:broken'), true);
  assert.equal(legacy.values.has('composeLocalDraftV3:user:8:new'), true);
  const [record] = await storage.list(7);
  assert.equal(record.snapshot.body_html, '<p>Generated legacy body</p>');
  assert.equal(record.status, 'local-only');
});

test('a failed durable migration preserves the legacy value', async () => {
  const key = 'composeLocalDraftV3:user:7:new';
  const legacy = fakeLocalStorage([[key, JSON.stringify({ subject: 'Generated' })]]);
  const storage = {
    async findByLegacyKey() { return null; },
    async put() { throw new Error('generated quota failure'); },
  };
  const result = await migrateLegacyScopedDrafts({
    storage,
    localStorage: legacy,
    userId: 7,
    randomUUID: uuidFactory(),
  });

  assert.equal(result.failed.length, 1);
  assert.equal(legacy.values.has(key), true);
});
