import assert from 'node:assert/strict';
import test from 'node:test';

const storage = new Map();
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
    clear: () => storage.clear(),
    key: index => [...storage.keys()][index] ?? null,
    get length() { return storage.size; },
  },
});

const {
  createOutboundDraftRestorer,
  forgetRetainedOutboundDraft,
  loadRetainedOutboundDraft,
  outboundRecoveryDraft,
} = await import('./outboundDraftRecovery.js');

test('recovered sends use their own bounded Compose intent key', () => {
  const recovered = outboundRecoveryDraft(
    {
      draft_key: 'new',
      client_draft_id: '10000000-0000-4000-8000-000000000001',
      draft_revision: 7,
      draft_state: 'sending',
      synced_revision: 7,
      linked_send_id: '10000000-0000-4000-8000-000000000002',
      body_html: '<p>Generated</p>',
    },
    { send_id: '00000000-0000-4000-8000-000000000111' },
  );

  assert.equal(
    recovered.draft_key,
    'outbound-recovery:00000000-0000-4000-8000-000000000111',
  );
  assert.equal(recovered.body_html, '<p>Generated</p>');
  assert.equal('client_draft_id' in recovered, false);
  assert.equal('draft_revision' in recovered, false);
  assert.equal('draft_state' in recovered, false);
  assert.equal('synced_revision' in recovered, false);
  assert.equal('linked_send_id' in recovered, false);
  assert.equal(
    recovered.recovery_source_client_draft_id,
    '10000000-0000-4000-8000-000000000001',
  );
});

test('retained outbound recovery clones auth-scoped content and deletes only on request', async () => {
  const retained = {
    snapshot: {
      body_html: '<p>Retained until terminal truth</p>',
      attachments: [{ filename: 'generated.txt', bytes: new Uint8Array([1, 2, 3]) }],
    },
  };
  const calls = [];
  const durableStorage = {
    async get(userId, clientDraftId) {
      calls.push(['get', userId, clientDraftId]);
      return retained;
    },
    async delete(userId, clientDraftId) {
      calls.push(['delete', userId, clientDraftId]);
      return true;
    },
  };

  const restored = await loadRetainedOutboundDraft(durableStorage, '7', 'draft-a');
  restored.attachments[0].bytes[0] = 9;
  assert.equal(retained.snapshot.attachments[0].bytes[0], 1);
  assert.equal(await forgetRetainedOutboundDraft(durableStorage, '7', 'draft-a'), true);
  assert.deepEqual(calls, [
    ['get', '7', 'draft-a'],
    ['delete', '7', 'draft-a'],
  ]);
});

test('retained outbound recovery fails closed when browser storage is unavailable', async () => {
  const unavailable = {
    async get() { throw new Error('generated storage failure'); },
    async delete() { throw new Error('generated storage failure'); },
  };
  assert.equal(await loadRetainedOutboundDraft(unavailable, '7', 'draft-a'), null);
  assert.equal(await forgetRetainedOutboundDraft(unavailable, '7', 'draft-a'), false);
});

test('an existing composer is preserved while a recovered draft waits', () => {
  let page = 'compose';
  let draft = null;
  let queued = null;
  const restorer = createOutboundDraftRestorer({
    getPage: () => page,
    setPage: value => { page = value; },
    setDraft: value => { draft = value; },
    captureSession: () => 'session-a',
    isSessionCurrent: value => value === 'session-a',
    queueDraft: (value, session) => { queued = { value, session }; },
  });

  assert.equal(restorer({ body_html: '<p>Recovered</p>' }, { send_id: 'send-1' }), true);
  assert.equal(page, 'compose');
  assert.equal(draft, null);
  assert.equal(queued.session, 'session-a');
  assert.equal(queued.value.draft_key, 'outbound-recovery:send-1');
});

test('an automatic failure waits for review instead of hijacking another page', () => {
  let page = 'flow';
  let draft = null;
  let queued = null;
  const restorer = createOutboundDraftRestorer({
    getPage: () => page,
    setPage: value => { page = value; },
    setDraft: value => { draft = value; },
    captureSession: () => 'session-a',
    isSessionCurrent: value => value === 'session-a',
    queueDraft: value => { queued = value; },
  });

  assert.equal(restorer({ body_html: '<p>Failed A</p>' }, { send_id: 'send-a' }, 'failed'), true);
  assert.equal(page, 'flow');
  assert.equal(draft, null);
  assert.equal(queued.draft_key, 'outbound-recovery:send-a');
});

test('an intentional Undo opens its recovered draft when Compose is not active', () => {
  let page = 'inbox';
  let draft = null;
  const restorer = createOutboundDraftRestorer({
    getPage: () => page,
    setPage: value => { page = value; },
    setDraft: value => { draft = value; },
    captureSession: () => 'session-a',
    isSessionCurrent: value => value === 'session-a',
    queueDraft: () => assert.fail('Undo should open directly'),
  });

  const clientDraftId = '10000000-0000-4000-8000-000000000077';
  assert.equal(restorer(
    { body_html: '<p>Cancelled</p>', client_draft_id: clientDraftId },
    { send_id: 'send-c', client_draft_id: clientDraftId },
    'cancelled',
  ), true);
  assert.equal(page, 'compose');
  assert.equal(draft.draft_key, `client:${clientDraftId}`);
  assert.equal(draft.client_draft_id, clientDraftId);
  assert.equal(draft.recovery_source_client_draft_id, clientDraftId);
  assert.equal(draft.refresh_server_draft, true);
});

test('a recovery cannot open for a stale authenticated session', () => {
  let page = 'inbox';
  let draft = null;
  let currentSession = 'session-a';
  const restorer = createOutboundDraftRestorer({
    getPage: () => page,
    setPage: value => { page = value; },
    setDraft: value => { draft = value; },
    captureSession: () => 'session-a',
    isSessionCurrent: value => value === currentSession,
    queueDraft: () => assert.fail('stale recovery must not be queued'),
  });

  currentSession = 'session-b';
  assert.equal(restorer({ body_html: '<p>User A</p>' }, { send_id: 'send-a' }), false);

  assert.equal(page, 'inbox');
  assert.equal(draft, null);
});
