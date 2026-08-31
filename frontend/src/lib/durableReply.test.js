import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createDurableReplyController,
  durableReplyIntent,
  durableReplySnapshot,
  replyBodyText,
  replyTextHtml,
} from './durableReply.js';
import { createDraftSessionController } from './draftSession.js';
import { createMemoryDraftStorage } from './draftStorage.js';

const CLIENT_ID = '10000000-0000-4000-8000-000000000001';
const REMOTE_ID = '10000000-0000-4000-8000-000000000002';

function uuidFactory(start = 0) {
  let counter = start;
  return () => `30000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
}

function envelope() {
  return {
    account_id: 7,
    source_email_id: 91,
    to: ['recipient@example.test'],
    cc: [],
    bcc: [],
    subject: 'Re: Generated',
    in_reply_to: '<generated@example.test>',
    references: '<generated@example.test>',
    thread_id: 'thread-generated',
  };
}

function fakeController() {
  const calls = [];
  let state = {
    clientDraftId: CLIENT_ID,
    revision: 3,
    status: 'synced',
    snapshot: durableReplySnapshot(envelope(), { bodyHtml: '<p>Saved</p>' }),
  };
  return {
    calls,
    controller: {
      async load(options) {
        calls.push(options);
        if (options.clientDraftId) state = { ...state, clientDraftId: options.clientDraftId };
        return state;
      },
      getState: () => state,
      update(snapshot) {
        state = { ...state, snapshot };
        return state;
      },
    },
  };
}

test('reply identity and canonical snapshot freeze exact source provenance', () => {
  assert.deepEqual(durableReplyIntent({ accountId: 7, sourceEmailId: 91 }), {
    intent_key: 'reply:7:91',
    draft_key: 'reply:7:91',
  });
  assert.throws(() => durableReplyIntent({ accountId: 7 }), /source email/);
  const html = replyTextHtml('Hello <team> & "friends"\nSecond line');
  assert.equal(html, '<p>Hello &lt;team&gt; &amp; &quot;friends&quot;<br>Second line</p>');
  assert.equal(replyBodyText(html), 'Hello <team> & "friends"\nSecond line');
  const snapshot = durableReplySnapshot(envelope(), { bodyHtml: html });
  assert.equal(snapshot.account_id, 7);
  assert.equal(snapshot.source_email_id, 91);
  assert.equal(snapshot.body_text, 'Hello <team> & "friends"\nSecond line');
  assert.equal(snapshot.follow_up_reminder, 'default');
  assert.equal(snapshot.follow_up_time_zone, null);
});

test('reply snapshots preserve explicit follow-up intent through send payloads', async () => {
  const fake = fakeController();
  const owner = createDurableReplyController({
    userId: 5,
    storage: { async findByIntent() { return { client_draft_id: CLIENT_ID }; } },
    api: {},
    envelope: envelope(),
    controllerFactory: () => fake.controller,
  });
  await owner.open();
  const snapshot = owner.snapshot('<p>Reminder</p>', 'Reminder', {
    followUpReminder: 'enabled',
    followUpTimeZone: 'America/New_York',
  });
  assert.equal(snapshot.follow_up_reminder, 'enabled');
  assert.equal(snapshot.follow_up_time_zone, 'America/New_York');
  owner.controller.update(snapshot);
  assert.equal(owner.sendPayload().follow_up_reminder, 'enabled');
  assert.equal(owner.sendPayload().follow_up_time_zone, 'America/New_York');
});

test('local reply identity wins before any cross-device lookup', async () => {
  const fake = fakeController();
  let sourceLookups = 0;
  const owner = createDurableReplyController({
    userId: 5,
    storage: {
      async findByIntent(userId, intentKey) {
        assert.equal(userId, 5);
        assert.equal(intentKey, 'reply:7:91');
        return { client_draft_id: CLIENT_ID };
      },
    },
    api: { async getComposeDraftBySource() { sourceLookups += 1; } },
    envelope: envelope(),
    controllerFactory: () => fake.controller,
  });
  await owner.open();
  assert.equal(sourceLookups, 0);
  assert.equal(fake.calls[0].clientDraftId, CLIENT_ID);
});

test('server-only reply is discovered by exact source and handed to the same controller', async () => {
  const fake = fakeController();
  const owner = createDurableReplyController({
    userId: 5,
    storage: { async findByIntent() { return null; } },
    api: {
      async getComposeDraftBySource(sourceEmailId, accountId) {
        assert.deepEqual([sourceEmailId, accountId], [91, 7]);
        return { client_draft_id: REMOTE_ID };
      },
    },
    envelope: envelope(),
    controllerFactory: () => fake.controller,
  });
  await owner.open();
  assert.equal(fake.calls[0].clientDraftId, REMOTE_ID);
  assert.equal(owner.composeData().client_draft_id, REMOTE_ID);
  assert.equal(owner.sendPayload().draft_revision, 3);
  assert.equal(owner.sendPayload().source_email_id, 91);
});

test('a missing cross-device reply creates only the stable source intent', async () => {
  const fake = fakeController();
  const owner = createDurableReplyController({
    userId: 5,
    storage: { async findByIntent() { return null; } },
    api: {
      async getComposeDraftBySource() {
        const error = new Error('not found');
        error.status = 404;
        throw error;
      },
    },
    envelope: envelope(),
    controllerFactory: () => fake.controller,
  });
  await owner.open();
  assert.equal(fake.calls[0].clientDraftId, undefined);
  assert.equal(fake.calls[0].intent.intent_key, 'reply:7:91');
});

test('a first reply can open offline and retain its stable local intent', async () => {
  const fake = fakeController();
  const owner = createDurableReplyController({
    userId: 5,
    storage: { async findByIntent() { return null; } },
    api: { async getComposeDraftBySource() { throw new TypeError('offline'); } },
    envelope: envelope(),
    controllerFactory: () => fake.controller,
  });
  await owner.open();
  assert.equal(fake.calls[0].clientDraftId, undefined);
  assert.equal(fake.calls[0].intent.intent_key, 'reply:7:91');
});

test('reply opening rejects an identity transition during local intent discovery', async () => {
  const fake = fakeController();
  let session = { generation: 1, userId: '5' };
  const owner = createDurableReplyController({
    userId: 5,
    storage: {
      async findByIntent() {
        session = { generation: 2, userId: '6' };
        return { client_draft_id: CLIENT_ID };
      },
    },
    api: {},
    envelope: envelope(),
    captureSession: () => ({ ...session }),
    isSessionCurrent: captured => (
      captured.generation === session.generation && captured.userId === session.userId
    ),
    controllerFactory: () => fake.controller,
  });

  await assert.rejects(owner.open(), error => error?.code === 'draft_session_changed');
  assert.equal(fake.calls.length, 0);
});

test('reply opening never persists a remote result returned after identity handoff', async () => {
  const storage = createMemoryDraftStorage();
  let session = { generation: 1, userId: '5' };
  const owner = createDurableReplyController({
    userId: 5,
    storage,
    api: {
      async getComposeDraftBySource() {
        session = { generation: 2, userId: '6' };
        return {
          client_draft_id: REMOTE_ID,
          revision: 7,
          state: 'synced',
          account_id: 7,
          source_email_id: 91,
          to: ['user-b@example.test'],
          body_text: 'User B private content',
        };
      },
    },
    envelope: envelope(),
    captureSession: () => ({ ...session }),
    isSessionCurrent: captured => (
      captured.generation === session.generation && captured.userId === session.userId
    ),
  });

  await assert.rejects(owner.open(), error => error?.code === 'draft_session_changed');
  assert.equal(await storage.get(5, REMOTE_ID), null);
  assert.deepEqual(await storage.list(5), []);
});

test('a send-reconciling reply opens locked without attempting envelope rebase', async () => {
  let updateCalls = 0;
  const state = {
    clientDraftId: CLIENT_ID,
    revision: 3,
    status: 'reconciling',
    sendInProgress: true,
    discardInProgress: false,
    snapshot: durableReplySnapshot(envelope(), { bodyHtml: '<p>Sending</p>' }),
  };
  const controller = {
    async load() { return state; },
    getState: () => state,
    update() {
      updateCalls += 1;
      throw new Error('Send status is still being confirmed');
    },
  };
  const replyAllEnvelope = {
    ...envelope(),
    to: ['recipient@example.test', 'team@example.test'],
  };
  const owner = createDurableReplyController({
    userId: 5,
    storage: {
      async findByIntent() { return { client_draft_id: CLIENT_ID }; },
    },
    api: {},
    envelope: replyAllEnvelope,
    controllerFactory: () => controller,
  });

  const opened = await owner.open();
  assert.equal(opened.status, 'reconciling');
  assert.equal(opened.sendInProgress, true);
  assert.equal(updateCalls, 0);
});

test('reopening as Reply All refreshes recipients without losing saved content', async () => {
  const storage = createMemoryDraftStorage();
  const randomUUID = uuidFactory();
  const controllerFactory = options => createDraftSessionController({
    ...options,
    randomUUID,
    isOnline: () => false,
  });
  const first = createDurableReplyController({
    userId: 5,
    storage,
    api: {},
    envelope: envelope(),
    controllerFactory,
  });
  await first.open();
  first.controller.update(first.snapshot('<p>Saved body</p>'));
  await first.controller.flush();

  const replyAllEnvelope = {
    ...envelope(),
    to: ['recipient@example.test', 'team@example.test'],
    cc: ['observer@example.test'],
  };
  const reopened = createDurableReplyController({
    userId: 5,
    storage,
    api: {},
    envelope: replyAllEnvelope,
    controllerFactory,
  });
  await reopened.open();
  assert.deepEqual(reopened.controller.getState().snapshot.to, replyAllEnvelope.to);
  assert.deepEqual(reopened.controller.getState().snapshot.cc, replyAllEnvelope.cc);
  assert.equal(reopened.controller.getState().snapshot.body_html, '<p>Saved body</p>');
});

test('a concurrent first-save loser adopts the exact source winner before resolving', async () => {
  const storage = createMemoryDraftStorage();
  const randomUUID = uuidFactory(20);
  const winnerId = REMOTE_ID;
  let winnerVisible = false;
  const winner = {
    client_draft_id: winnerId,
    draft_id: 'provider-winner',
    account_id: 7,
    source_email_id: 91,
    revision: 1,
    synced_revision: 1,
    state: 'synced',
    to: ['winner@example.test'],
    cc: [],
    bcc: [],
    subject: 'Re: Generated',
    body_html: '<p>Remote winner</p>',
    body_text: 'Remote winner',
    attachments: [],
  };
  const savedIds = [];
  const api = {
    async getComposeDraftBySource() {
      if (!winnerVisible) {
        const missing = new Error('not found');
        missing.status = 404;
        throw missing;
      }
      return winner;
    },
    async saveDraft(payload) {
      savedIds.push(payload.client_draft_id);
      if (payload.client_draft_id !== winnerId) {
        winnerVisible = true;
        const conflict = new Error('source exists');
        conflict.status = 409;
        conflict.code = 'draft_source_exists';
        conflict.detail = { code: 'draft_source_exists' };
        throw conflict;
      }
      return { ...winner, ...payload, state: 'synced', synced_revision: payload.revision };
    },
  };
  const owner = createDurableReplyController({
    userId: 5,
    storage,
    api,
    envelope: envelope(),
    controllerFactory: options => createDraftSessionController({ ...options, randomUUID }),
  });
  await owner.open();
  const losingId = owner.controller.clientDraftId;
  owner.controller.update(owner.snapshot('<p>Keep local</p>'));
  await owner.controller.flush();
  assert.equal(owner.controller.getState().status, 'conflict');
  assert.equal(owner.controller.clientDraftId, winnerId);
  assert.equal(await storage.get(5, losingId), null);
  await assert.rejects(
    owner.controller.markSending(true),
    /Resolve the draft conflict before sending/,
  );
  assert.equal(owner.controller.getState().sending, false);

  await owner.controller.resolveConflict('local');
  assert.equal(owner.controller.getState().status, 'synced');
  assert.equal(owner.controller.getState().snapshot.body_html, '<p>Keep local</p>');
  assert.deepEqual(savedIds, [losingId, winnerId]);
});

test('a local reply keeps its UUID while the source winner is sending or being discarded', async () => {
  for (const winnerState of ['sending', 'discard_pending']) {
    const storage = createMemoryDraftStorage();
    const randomUUID = uuidFactory(winnerState === 'sending' ? 30 : 40);
    const winnerId = REMOTE_ID;
    let occupied = true;
    let winnerVisible = false;
    const winner = {
      client_draft_id: winnerId,
      draft_id: `provider-${winnerState}`,
      account_id: 7,
      source_email_id: 91,
      revision: 1,
      synced_revision: 1,
      state: winnerState,
      to: ['winner@example.test'],
      cc: [],
      bcc: [],
      subject: 'Re: Generated',
      body_html: '<p>Remote terminal draft</p>',
      body_text: 'Remote terminal draft',
      attachments: [],
    };
    const savedIds = [];
    const api = {
      async getComposeDraftBySource() {
        if (!occupied || !winnerVisible) {
          const missing = new Error('not found');
          missing.status = 404;
          throw missing;
        }
        return winner;
      },
      async saveDraft(payload) {
        savedIds.push(payload.client_draft_id);
        if (occupied && payload.client_draft_id !== winnerId) {
          winnerVisible = true;
          const conflict = new Error('source exists');
          conflict.status = 409;
          conflict.code = 'draft_source_exists';
          conflict.detail = { code: 'draft_source_exists' };
          throw conflict;
        }
        return { ...payload, state: 'synced', synced_revision: payload.revision };
      },
    };
    const owner = createDurableReplyController({
      userId: 5,
      storage,
      api,
      envelope: envelope(),
      controllerFactory: options => createDraftSessionController({ ...options, randomUUID }),
    });
    await owner.open();
    const losingId = owner.controller.clientDraftId;
    owner.controller.update(owner.snapshot(`<p>Keep local after ${winnerState}</p>`));
    await owner.controller.flush();

    assert.equal(owner.controller.getState().status, 'conflict');
    assert.equal(owner.controller.clientDraftId, losingId);
    assert.ok(await storage.get(5, losingId));

    occupied = false;
    await owner.controller.resolveConflict('local');
    assert.equal(owner.controller.getState().status, 'synced');
    assert.equal(owner.controller.clientDraftId, losingId);
    assert.deepEqual(savedIds, [losingId, losingId]);
  }
});
