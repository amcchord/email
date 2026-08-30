import assert from 'node:assert/strict';
import test from 'node:test';
import { get } from 'svelte/store';
import {
  canUndoOutboundSend,
  createOutboundSendController,
  normalizeOutboundSendOperation,
  remainingOutboundUndoMs,
} from './outboundSend.js';

const NOW = Date.parse('2026-08-30T16:00:00.000Z');

function serverOperation(overrides = {}) {
  return {
    send_id: '00000000-0000-4000-8000-000000000111',
    idempotency_key: '00000000-0000-4000-8000-000000000222',
    account_id: 7,
    source_email_id: 81,
    state: 'staged',
    execute_after: '2026-08-30T16:00:10.000Z',
    undo_until: '2026-08-30T16:00:10.000Z',
    next_attempt_at: null,
    attempt_count: 0,
    max_attempts: 8,
    can_undo: true,
    can_retry: false,
    error_code: null,
    error_message: null,
    created_at: '2026-08-30T16:00:00.000Z',
    updated_at: '2026-08-30T16:00:00.000Z',
    sent_at: null,
    failed_at: null,
    cancelled_at: null,
    ...overrides,
  };
}

function missingError() {
  const error = new Error('Not found');
  error.status = 404;
  return error;
}

function testController(transport, options = {}) {
  const session = { generation: 1, userId: 'user-a' };
  return createOutboundSendController({
    transport,
    captureSession: () => session,
    isSessionCurrent: candidate => candidate === session,
    now: () => NOW,
    schedule: () => 1,
    cancel: () => {},
    notify: () => {},
    randomUUID: () => '00000000-0000-4000-8000-000000000222',
    ...options,
  });
}

test('normalization exposes only safe lifecycle fields and honors server retry authority', () => {
  const normalized = normalizeOutboundSendOperation(serverOperation({
    state: 'failed',
    can_undo: false,
    can_retry: true,
    attempt_count: 3,
    max_attempts: 8,
    to: ['private@example.com'],
    subject: 'private subject',
    body_html: '<p>private body</p>',
    attachments: [{ filename: 'private.pdf' }],
  }));

  assert.equal(normalized.can_retry, true);
  assert.equal(normalized.can_undo, false);
  assert.equal(normalized.source_email_id, 81);
  assert.equal(normalized.attempt_count, 3);
  assert.equal(normalized.max_attempts, 8);
  assert.equal('retryable' in normalized, false);
  assert.equal('to' in normalized, false);
  assert.equal('subject' in normalized, false);
  assert.equal('body_html' in normalized, false);
  assert.equal('attachments' in normalized, false);
});

test('normalization retains only a valid durable draft identity for recovery', () => {
  const valid = '10000000-0000-4000-8000-000000000001';
  assert.equal(
    normalizeOutboundSendOperation(serverOperation({ client_draft_id: valid })).client_draft_id,
    valid,
  );
  assert.equal(
    normalizeOutboundSendOperation(serverOperation({ client_draft_id: '../shared-draft' })).client_draft_id,
    null,
  );
});

test('a state without a server id remains explicitly reconciling', () => {
  const operation = normalizeOutboundSendOperation({
    idempotency_key: 'client-key',
    state: 'sent',
  });

  assert.equal(operation.state, 'reconciling');
  assert.equal(operation.client_only, true);
});

test('Undo Send uses the authoritative deadline and server can_undo flag', () => {
  const staged = normalizeOutboundSendOperation(serverOperation());
  assert.equal(remainingOutboundUndoMs(staged, NOW), 10_000);
  assert.equal(canUndoOutboundSend(staged, NOW), true);
  assert.equal(canUndoOutboundSend({ ...staged, can_undo: false }, NOW), false);
  assert.equal(canUndoOutboundSend({ ...staged, state: 'processing' }, NOW), false);
});

test('one logical submit creates one key, offers deadline-bound Undo, and restores on cancel', async () => {
  const notices = [];
  const callbackStates = [];
  const restored = [];
  let createKey = null;
  const transport = {
    create: async (_payload, key) => {
      createKey = key;
      return serverOperation({ idempotency_key: key });
    },
    lookupByIdempotency: async () => { throw missingError(); },
    get: async () => serverOperation(),
    undo: async () => serverOperation({
      idempotency_key: createKey,
      state: 'cancelled',
      can_undo: false,
      cancelled_at: '2026-08-30T16:00:02.000Z',
      updated_at: '2026-08-30T16:00:02.000Z',
    }),
  };
  let uuidCalls = 0;
  const controller = testController(transport, {
    randomUUID: () => {
      uuidCalls += 1;
      return '00000000-0000-4000-8000-000000000222';
    },
    notify: (...args) => notices.push(args),
  });

  const accepted = [];
  const operation = await controller.submit({ body_html: '<p>hello</p>' }, {
    onAccepted: item => accepted.push(item.state),
    onStateChange: item => callbackStates.push(item.state),
    onRestore: (item, reason) => restored.push([item.state, reason]),
  });

  assert.equal(uuidCalls, 1);
  assert.equal(operation.state, 'staged');
  assert.deepEqual(accepted, ['staged']);
  assert.deepEqual(callbackStates, ['staged']);
  assert.equal(notices[0][0], 'Email queued to send');
  assert.equal(notices[0][2], 10_000);
  assert.equal(notices[0][3].actionLabel, 'Undo');
  assert.equal(notices.some(([message]) => message === 'Email sent'), false);
  assert.equal(controller.getLatestReversible()?.send_id, operation.send_id);

  await notices[0][3].onAction();

  assert.deepEqual(restored, [['cancelled', 'cancelled']]);
  assert.equal(get(controller)[0].state, 'cancelled');
});

test('a lost POST is looked up and replayed only with the same key', async () => {
  const createKeys = [];
  let createCalls = 0;
  const transport = {
    create: async (_payload, key) => {
      createCalls += 1;
      createKeys.push(key);
      if (createCalls === 1) throw new TypeError('Failed to fetch');
      return serverOperation({ idempotency_key: key });
    },
    lookupByIdempotency: async () => { throw missingError(); },
    get: async () => serverOperation(),
  };
  let uuidCalls = 0;
  const controller = testController(transport, {
    randomUUID: () => {
      uuidCalls += 1;
      return '00000000-0000-4000-8000-000000000333';
    },
  });

  const operation = await controller.submit({ subject: 'hello' });

  assert.equal(operation.state, 'staged');
  assert.equal(uuidCalls, 1);
  assert.equal(createCalls, 2);
  assert.deepEqual(createKeys, [
    '00000000-0000-4000-8000-000000000333',
    '00000000-0000-4000-8000-000000000333',
  ]);
});

test('bounded unresolved POST becomes do-not-resend reconciliation until server confirms sent', async () => {
  const notices = [];
  const sent = [];
  let lookupResult = null;
  let createCalls = 0;
  let lookupCalls = 0;
  const transport = {
    create: async () => {
      createCalls += 1;
      throw new TypeError('Network connection lost');
    },
    lookupByIdempotency: async key => {
      lookupCalls += 1;
      if (!lookupResult) throw missingError();
      return { ...lookupResult, idempotency_key: key };
    },
    get: async () => lookupResult,
  };
  const controller = testController(transport, {
    maxCreateReplays: 1,
    notify: (...args) => notices.push(args),
  });

  const uncertain = await controller.submit({ to: ['private@example.com'] }, {
    onSent: operation => sent.push(operation.state),
  });

  assert.equal(createCalls, 2);
  assert.equal(lookupCalls, 2);
  assert.equal(uncertain.state, 'reconciling');
  assert.equal(uncertain.client_only, true);
  assert.match(notices.at(-1)[0], /do not resend/i);
  assert.equal(notices.some(([message]) => message === 'Email sent'), false);

  lookupResult = serverOperation({
    state: 'sent',
    can_undo: false,
    sent_at: '2026-08-30T16:00:05.000Z',
    updated_at: '2026-08-30T16:00:05.000Z',
  });
  const confirmed = await controller.refreshOperation(uncertain);

  assert.equal(confirmed.state, 'sent');
  assert.deepEqual(sent, ['sent']);
  assert.equal(notices.filter(([message]) => message === 'Email sent').length, 1);
});

test('session A completion cannot publish callbacks, operations, or toasts into session B', async () => {
  let current = { generation: 1, userId: 'A' };
  let releaseCreate;
  const createGate = new Promise(resolve => { releaseCreate = resolve; });
  const notices = [];
  let accepted = 0;
  const transport = {
    create: async () => createGate,
    lookupByIdempotency: async () => { throw missingError(); },
    get: async () => serverOperation(),
  };
  const controller = createOutboundSendController({
    transport,
    captureSession: () => current,
    isSessionCurrent: snapshot => snapshot === current,
    sessionKey: snapshot => `${snapshot.generation}:${snapshot.userId}`,
    randomUUID: () => '00000000-0000-4000-8000-000000000444',
    notify: (...args) => notices.push(args),
    schedule: () => 1,
    cancel: () => {},
  });

  const submission = controller.submit({}, { onAccepted: () => { accepted += 1; } });
  current = { generation: 2, userId: 'B' };
  releaseCreate(serverOperation());

  await assert.rejects(submission, error => error.code === 'auth_session_changed');
  assert.equal(accepted, 0);
  assert.deepEqual(notices, []);
  assert.deepEqual(get(controller), []);
});

test('async callback failures are contained and never change delivery truth', async () => {
  const transport = {
    create: async () => serverOperation(),
    lookupByIdempotency: async () => { throw missingError(); },
    get: async () => serverOperation(),
  };
  const controller = testController(transport);

  const operation = await controller.submit({}, {
    onAccepted: async () => { throw new Error('caller failed'); },
    onStateChange: async () => { throw new Error('caller failed'); },
  });
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(operation.state, 'staged');
  assert.equal(get(controller)[0].state, 'staged');
});

test('recent failed operations remain metadata-only and retry follows can_retry', async () => {
  let retried = 0;
  const failed = serverOperation({
    state: 'failed',
    can_undo: false,
    can_retry: true,
    failed_at: '2026-08-30T16:01:00.000Z',
    updated_at: '2026-08-30T16:01:00.000Z',
    error_code: 'provider_unavailable',
    error_message: 'Provider temporarily unavailable',
    to: ['private@example.com'],
    body_text: 'private body',
  });
  const transport = {
    create: async () => serverOperation(),
    lookupByIdempotency: async () => failed,
    get: async () => failed,
    listRecent: async () => ({ operations: [failed] }),
    retry: async () => {
      retried += 1;
      return serverOperation({
        state: 'retry_wait',
        can_undo: false,
        can_retry: false,
        attempt_count: 3,
        next_attempt_at: '2026-08-30T16:02:00.000Z',
        updated_at: '2026-08-30T16:01:01.000Z',
      });
    },
  };
  const controller = testController(transport);

  await controller.loadRecent();
  const visible = get(controller)[0];
  assert.equal(visible.can_retry, true);
  assert.equal('to' in visible, false);
  assert.equal('body_text' in visible, false);

  const next = await controller.retry(visible.send_id);
  assert.equal(retried, 1);
  assert.equal(next.state, 'retry_wait');
});

test('recent unexpired staged send rehydrates actionable Undo with truthful cancel copy', async () => {
  const notices = [];
  const staged = serverOperation();
  const transport = {
    create: async () => staged,
    lookupByIdempotency: async () => staged,
    get: async () => staged,
    listRecent: async () => [staged],
    undo: async () => serverOperation({
      state: 'cancelled',
      can_undo: false,
      cancelled_at: '2026-08-30T16:00:02.000Z',
      updated_at: '2026-08-30T16:00:02.000Z',
    }),
  };
  const controller = testController(transport, {
    notify: (...args) => notices.push(args),
  });

  await controller.loadRecent();

  assert.equal(notices.length, 1);
  assert.equal(notices[0][0], 'Email queued to send');
  assert.equal(notices[0][2], 10_000);
  assert.equal(notices[0][3].actionLabel, 'Undo');

  await notices[0][3].onAction();

  assert.equal(notices.at(-1)[0], 'Send cancelled');
  assert.equal(notices.some(([message]) => /draft restored/i.test(message)), false);
});

test('recent staged send can attach reload recovery before Undo', async () => {
  const notices = [];
  const restored = [];
  const clientDraftId = '10000000-0000-4000-8000-000000000001';
  const staged = serverOperation({ client_draft_id: clientDraftId });
  const transport = {
    create: async () => staged,
    lookupByIdempotency: async () => staged,
    get: async () => staged,
    listRecent: async () => [staged],
    undo: async () => serverOperation({
      client_draft_id: clientDraftId,
      state: 'cancelled',
      can_undo: false,
      cancelled_at: '2026-08-30T16:00:02.000Z',
      updated_at: '2026-08-30T16:00:02.000Z',
    }),
  };
  const controller = testController(transport, {
    notify: (...args) => notices.push(args),
  });

  const operations = await controller.loadRecent();
  assert.equal(controller.attachCallbacks(operations[0], {
    onRestore: (operation, reason) => restored.push([
      operation.client_draft_id,
      reason,
    ]),
  }), true);

  await notices[0][3].onAction();
  assert.deepEqual(restored, [[clientDraftId, 'cancelled']]);
  assert.equal(notices.at(-1)[0], 'Send cancelled; recovering draft');
});

test('recent terminal history never re-toasts old sent or failed operations', async () => {
  const notices = [];
  const transport = {
    create: async () => serverOperation(),
    lookupByIdempotency: async () => { throw missingError(); },
    get: async () => serverOperation(),
    listRecent: async () => [
      serverOperation({
        state: 'sent',
        can_undo: false,
        sent_at: '2026-08-30T15:55:00.000Z',
        updated_at: '2026-08-30T15:55:00.000Z',
      }),
      serverOperation({
        send_id: '00000000-0000-4000-8000-000000000999',
        idempotency_key: '00000000-0000-4000-8000-000000000998',
        state: 'failed',
        can_undo: false,
        can_retry: true,
        failed_at: '2026-08-30T15:56:00.000Z',
        updated_at: '2026-08-30T15:56:00.000Z',
      }),
    ],
  };
  const controller = testController(transport, {
    notify: (...args) => notices.push(args),
  });

  await controller.loadRecent();

  assert.deepEqual(notices, []);
  assert.deepEqual(get(controller).map(operation => operation.state), ['failed', 'sent']);
});
