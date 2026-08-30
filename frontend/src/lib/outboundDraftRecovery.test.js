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
  outboundRecoveryDraft,
} = await import('./outboundDraftRecovery.js');

test('recovered sends use their own bounded Compose intent key', () => {
  const recovered = outboundRecoveryDraft(
    { draft_key: 'new', body_html: '<p>Generated</p>' },
    { send_id: '00000000-0000-4000-8000-000000000111' },
  );

  assert.equal(
    recovered.draft_key,
    'outbound-recovery:00000000-0000-4000-8000-000000000111',
  );
  assert.equal(recovered.body_html, '<p>Generated</p>');
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

  assert.equal(restorer({ body_html: '<p>Cancelled</p>' }, { send_id: 'send-c' }, 'cancelled'), true);
  assert.equal(page, 'compose');
  assert.equal(draft.draft_key, 'outbound-recovery:send-c');
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
