import assert from 'node:assert/strict';
import test from 'node:test';

import { newComposeIntent } from './composeDraft.js';
import { createDraftSessionController, DRAFT_SESSION_STATES, draftStatusView } from './draftSession.js';
import { createMemoryDraftStorage } from './draftStorage.js';

function uuidFactory(start = 0) {
  let counter = start;
  return () => `20000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function fakeTimers() {
  let nextId = 0;
  const pending = new Map();
  return {
    setTimeout(callback, delay) {
      const id = ++nextId;
      pending.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) { pending.delete(id); },
    runNext() {
      const entry = [...pending.entries()].sort((a, b) => a[1].delay - b[1].delay)[0];
      if (!entry) return false;
      pending.delete(entry[0]);
      entry[1].callback();
      return true;
    },
    get size() { return pending.size; },
  };
}

function controllerOptions(overrides = {}) {
  const randomUUID = overrides.randomUUID || uuidFactory();
  return {
    userId: 7,
    storage: overrides.storage || createMemoryDraftStorage(),
    randomUUID,
    timers: overrides.timers || fakeTimers(),
    now: overrides.now || (() => '2026-08-30T12:00:00.000Z'),
    isOnline: overrides.isOnline || (() => true),
    captureSession: overrides.captureSession || (() => ({ generation: 1, userId: 7 })),
    isSessionCurrent: overrides.isSessionCurrent || (() => true),
    api: overrides.api || {},
    onDiscard: overrides.onDiscard,
    onUndoDiscard: overrides.onUndoDiscard,
  };
}

test('the public state machine exposes every required durable lifecycle state', () => {
  assert.deepEqual(DRAFT_SESSION_STATES, [
    'pristine', 'dirty', 'local-only', 'saving', 'synced', 'offline',
    'reconciling', 'failed', 'conflict', 'discard-pending', 'discarded',
  ]);
  assert.equal(draftStatusView({ status: 'reconciling' }).message, 'Checking draft status… Don’t save again.');
  assert.equal(draftStatusView({ status: 'saving' }).live, 'off');
  assert.equal(draftStatusView({ status: 'failed' }).role, 'alert');
});

test('two new intents retain independent identities, namespaces, revisions, and content', async () => {
  const randomUUID = uuidFactory();
  const storage = createMemoryDraftStorage();
  const firstIntent = newComposeIntent({}, { randomUUID });
  const secondIntent = newComposeIntent({}, { randomUUID });
  const first = createDraftSessionController(controllerOptions({ storage, randomUUID, isOnline: () => false }));
  const second = createDraftSessionController(controllerOptions({ storage, randomUUID, isOnline: () => false }));

  await first.create({ intent: firstIntent });
  first.update({ subject: 'Generated A', body_html: '<p>A</p>' });
  await first.flush();
  await second.create({ intent: secondIntent });
  second.update({ subject: 'Generated B', body_html: '<p>B</p>' });
  await second.flush();

  assert.notEqual(first.clientDraftId, second.clientDraftId);
  assert.notEqual(first.storageNamespace, second.storageNamespace);
  assert.equal(first.revision, 1);
  assert.equal(second.revision, 1);
  assert.equal((await storage.get(7, first.clientDraftId)).snapshot.subject, 'Generated A');
  assert.equal((await storage.get(7, second.clientDraftId)).snapshot.subject, 'Generated B');
});

test('a lost save response reconciles by owned client identity and mutation without replay', async () => {
  const randomUUID = uuidFactory();
  const storage = createMemoryDraftStorage();
  let accepted;
  let saves = 0;
  let lookups = 0;
  const controller = createDraftSessionController(controllerOptions({
    storage,
    randomUUID,
    api: {
      async saveDraft(payload) {
        saves += 1;
        accepted = { ...payload, draft_id: 'provider-generated-1' };
        throw new TypeError('generated lost response');
      },
      async getComposeDraft(clientDraftId) {
        lookups += 1;
        assert.equal(clientDraftId, accepted.client_draft_id);
        return accepted;
      },
    },
  }));
  await controller.create({ intent: newComposeIntent({}, { randomUUID }) });
  controller.update({ to: ['generated@example.test'], body_html: '<p>Generated</p>' });
  await controller.flush();

  assert.equal(saves, 1);
  assert.equal(lookups, 1);
  assert.equal(controller.getState().status, 'synced');
  assert.equal(controller.getState().server.draft_id, 'provider-generated-1');
});

test('a 202-style pending response remains saving until GET reports provider synced', async () => {
  const randomUUID = uuidFactory();
  const timers = fakeTimers();
  let serverState = 'pending';
  let accepted;
  const controller = createDraftSessionController(controllerOptions({
    randomUUID,
    timers,
    api: {
      async saveDraft(payload) {
        accepted = payload;
        return { ...payload, state: 'pending', synced_revision: 0 };
      },
      async getComposeDraft() {
        return {
          ...accepted,
          state: serverState,
          synced_revision: serverState === 'synced' ? accepted.revision : 0,
        };
      },
    },
  }));
  await controller.create({ intent: newComposeIntent({}, { randomUUID }) });
  controller.update({ body_html: '<p>Generated pending</p>' });
  await controller.flush();
  assert.equal(controller.getState().status, 'saving');
  assert.equal(controller.getState().syncedRevision, 0);

  serverState = 'synced';
  assert.equal(timers.runNext(), true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(controller.getState().status, 'synced');
  assert.equal(controller.getState().syncedRevision, 1);
});

test('offline content and attachment bytes survive controller disposal and reload', async () => {
  const randomUUID = uuidFactory();
  const storage = createMemoryDraftStorage();
  const intent = newComposeIntent({}, { randomUUID });
  const first = createDraftSessionController(controllerOptions({ storage, randomUUID, isOnline: () => false }));
  await first.create({ intent });
  first.update({ body_html: '<p>Offline</p>', attachments: [] });
  const importId = first.beginAttachmentImport({ filename: 'generated.bin' });
  assert.equal(first.getState().canSend, false);
  first.completeAttachmentImport(importId, {
    filename: 'generated.bin',
    bytes: new Uint8Array([12, 34, 56, 255]),
  });
  await first.flush();
  assert.equal(first.getState().status, 'offline');
  first.dispose();

  const restored = createDraftSessionController(controllerOptions({ storage, randomUUID, isOnline: () => false }));
  await restored.load({ clientDraftId: intent.client_draft_id, intent });
  assert.equal(restored.getState().snapshot.body_html, '<p>Offline</p>');
  assert.deepEqual(
    [...restored.getState().snapshot.attachments[0].bytes],
    [12, 34, 56, 255],
  );
  assert.equal(restored.getState().status, 'offline');
});

test('conflicts preserve local content until an explicit resolution', async () => {
  const randomUUID = uuidFactory();
  let conflict = true;
  const controller = createDraftSessionController(controllerOptions({
    randomUUID,
    api: {
      async saveDraft(payload) {
        if (conflict) {
          const error = new Error('generated conflict');
          error.status = 409;
          error.detail = {
            server_revision: 4,
            server_snapshot: { subject: 'Server version', body_html: '<p>Server</p>' },
          };
          throw error;
        }
        return { ...payload, draft_id: 'provider-conflict-resolved' };
      },
    },
  }));
  await controller.create({ intent: newComposeIntent({}, { randomUUID }) });
  controller.update({ subject: 'Local version', body_html: '<p>Local</p>' });
  await controller.flush();
  assert.equal(controller.getState().status, 'conflict');
  assert.equal(controller.getState().snapshot.subject, 'Local version');
  assert.equal(controller.getState().canSend, false);

  conflict = false;
  await controller.resolveConflict('server');
  assert.equal(controller.getState().status, 'synced');
  assert.equal(controller.getState().snapshot.subject, 'Server version');
  assert.equal(controller.revision, 5);
});

test('server discard starts immediately, Undo is authoritative, and bytes scrub only after GET confirms discarded', async () => {
  const randomUUID = uuidFactory();
  const timers = fakeTimers();
  const storage = createMemoryDraftStorage();
  const discarded = [];
  const undone = [];
  let serverState = 'discard_pending';
  let discardCalls = 0;
  let undoCalls = 0;
  const controller = createDraftSessionController(controllerOptions({
    randomUUID,
    timers,
    storage,
    isOnline: () => false,
    api: {
      async discardComposeDraft(clientDraftId, mutationId) {
        discardCalls += 1;
        assert.ok(clientDraftId);
        assert.ok(mutationId);
        serverState = 'discard_pending';
        return {
          client_draft_id: clientDraftId,
          state: 'discard_pending',
          discard_undo_until: '2026-08-30T12:00:05.000Z',
          can_undo_discard: true,
          mutation_id: mutationId,
        };
      },
      async undoComposeDraftDiscard(clientDraftId, mutationId) {
        undoCalls += 1;
        assert.ok(clientDraftId);
        assert.ok(mutationId);
        serverState = 'pending';
        return { client_draft_id: clientDraftId, state: 'pending', revision: controller.revision };
      },
      async getComposeDraft(clientDraftId) {
        return {
          client_draft_id: clientDraftId,
          state: serverState,
          revision: controller.revision,
          discarded_at: serverState === 'discarded' ? '2026-08-30T12:00:05.000Z' : null,
          discard_undo_until: '2026-08-30T12:00:05.000Z',
          can_undo_discard: serverState === 'discard_pending',
        };
      },
    },
    onDiscard: event => discarded.push(event),
    onUndoDiscard: event => undone.push(event),
  }));
  await controller.create({ intent: newComposeIntent({}, { randomUUID }) });
  controller.update({ body_html: '<p>Generated</p>', attachments: [{ bytes: new Uint8Array([9, 8, 7]) }] });
  await controller.flush();

  await controller.discard({ delayMs: 5000 });
  assert.equal(discardCalls, 1);
  assert.equal(controller.getState().status, 'discard-pending');
  assert.equal(await controller.undoDiscard(), true);
  assert.equal(undoCalls, 1);
  assert.equal(controller.getState().status, 'offline');
  assert.equal(undone.length, 1);
  assert.equal(timers.size, 0);

  await controller.discard({ delayMs: 5000 });
  assert.equal(discardCalls, 2);
  const pendingRecord = await storage.get(7, controller.clientDraftId);
  assert.equal(pendingRecord.snapshot.attachments.length, 1);
  serverState = 'discarded';
  assert.equal(timers.runNext(), true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(controller.getState().status, 'discarded');
  const record = await storage.get(7, controller.clientDraftId);
  assert.deepEqual(record.snapshot, {});
  assert.ok(record.tombstone.finalized_at);
  assert.equal(discarded.length, 1);
});

test('a late A completion updates only A storage and never clobbers active B state', async () => {
  const randomUUID = uuidFactory();
  const storage = createMemoryDraftStorage();
  const firstSave = deferred();
  let saveCount = 0;
  const controller = createDraftSessionController(controllerOptions({
    randomUUID,
    storage,
    api: {
      saveDraft(payload) {
        saveCount += 1;
        if (saveCount === 1) return firstSave.promise;
        return Promise.resolve({ ...payload, draft_id: 'provider-b' });
      },
    },
  }));
  const intentA = newComposeIntent({}, { randomUUID });
  const intentB = newComposeIntent({}, { randomUUID });
  await controller.create({ intent: intentA });
  controller.update({ subject: 'A', body_html: '<p>A</p>' });
  const flushingA = controller.flush();
  await Promise.resolve();

  await controller.create({ intent: intentB, initialSnapshot: { subject: 'B', body_html: '<p>B</p>' } });
  firstSave.resolve({
    client_draft_id: intentA.client_draft_id,
    revision: 1,
    mutation_id: (await storage.get(7, intentA.client_draft_id)).mutation_id,
    draft_id: 'provider-a',
  });
  await flushingA;

  assert.equal(controller.clientDraftId, intentB.client_draft_id);
  assert.equal(controller.getState().snapshot.subject, 'B');
  assert.equal(controller.getState().server.draft_id, undefined);
  assert.equal((await storage.get(7, intentA.client_draft_id)).server.draft_id, 'provider-a');
});

test('responses from a stale authenticated session are suppressed before storage or UI commit', async () => {
  const randomUUID = uuidFactory();
  const storage = createMemoryDraftStorage();
  const response = deferred();
  let generation = 1;
  const controller = createDraftSessionController(controllerOptions({
    randomUUID,
    storage,
    captureSession: () => ({ generation }),
    isSessionCurrent: captured => captured.generation === generation,
    api: { saveDraft: () => response.promise },
  }));
  const intent = newComposeIntent({}, { randomUUID });
  await controller.create({ intent });
  controller.update({ subject: 'A', body_html: '<p>A</p>' });
  const pending = controller.flush();
  await Promise.resolve();
  generation = 2;
  response.resolve({
    client_draft_id: intent.client_draft_id,
    revision: 1,
    draft_id: 'must-not-commit',
  });
  await pending;

  assert.equal(controller.getState().status, 'saving');
  assert.equal((await storage.get(7, intent.client_draft_id)).server.draft_id, undefined);
});

test('attachment errors gate Send and expose actionable status copy', async () => {
  const randomUUID = uuidFactory();
  const controller = createDraftSessionController(controllerOptions({ randomUUID }));
  await controller.create({ intent: newComposeIntent({}, { randomUUID }) });
  const id = controller.beginAttachmentImport({ filename: 'generated.pdf' });
  controller.failAttachmentImport(id, new Error('generated read error'));

  assert.equal(controller.getState().canSend, false);
  assert.equal(draftStatusView(controller.getState()).message, 'Couldn’t add generated.pdf');
  assert.equal(draftStatusView(controller.getState()).retry, true);
  controller.clearAttachmentError(id);
  assert.equal(controller.getState().canSend, true);
});
