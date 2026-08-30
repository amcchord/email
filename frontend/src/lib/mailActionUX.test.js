import assert from 'node:assert/strict';
import test from 'node:test';
import {
  actionPastTense,
  actionRemovesFromMailbox,
  applyEmailAction,
  canUndoAction,
  captureInboxAction,
  createMailActionSubmissionQueue,
  failedMailActionRequestIds,
  hasNewFailedMailActions,
  idempotencyKey,
  isMailActionNetworkError,
  optimisticInboxAction,
  remainingUndoMs,
  rollbackEmailAction,
  rollbackThreadAction,
  restoreInboxAction,
} from './mailActionUX.js';

const email = (id, labels = ['INBOX', 'UNREAD']) => ({
  id,
  labels,
  is_read: !labels.includes('UNREAD'),
  is_starred: labels.includes('STARRED'),
  is_trash: labels.includes('TRASH'),
  is_spam: labels.includes('SPAM'),
});

test('archive removes immediately and focuses the adjacent row', () => {
  const result = optimisticInboxAction({
    emails: [email(1), email(2), email(3)],
    selectedId: 2,
    emailIds: [2],
    action: 'archive',
    mailbox: 'INBOX',
  });

  assert.deepEqual(result.emails.map(item => item.id), [1, 3]);
  assert.equal(result.selectedId, 3);
  assert.equal(result.removed, true);
});

test('removing the last row focuses the previous row', () => {
  const result = optimisticInboxAction({
    emails: [email(1), email(2)],
    selectedId: 2,
    emailIds: [2],
    action: 'trash',
    mailbox: 'INBOX',
  });

  assert.deepEqual(result.emails.map(item => item.id), [1]);
  assert.equal(result.selectedId, 1);
});

test('rollback restores only the failed target around other accepted removals', () => {
  const original = [email(1), email(2), email(3), email(4)];
  const first = captureInboxAction(original, 2, [2]);
  const afterTwoActions = original.filter(item => ![2, 3].includes(item.id));

  const restored = restoreInboxAction(afterTwoActions, first);

  assert.deepEqual(restored.map(item => item.id), [1, 2, 4]);
});

test('rollback replaces an optimistic in-place flag update exactly', () => {
  const original = [email(1), email(2)];
  const snapshot = captureInboxAction(original, 1, [1]);
  const optimistic = original.map(item => item.id === 1 ? applyEmailAction(item, 'star') : item);

  const restored = restoreInboxAction(optimistic, snapshot, 'star');

  assert.deepEqual(restored[0], original[0]);
});

test('older rollback preserves a newer optimistic change on the same email', () => {
  const original = email(1);
  const afterStar = applyEmailAction(original, 'star');
  const afterNewerRead = applyEmailAction(afterStar, 'mark_read');

  const rolledBack = rollbackEmailAction(afterNewerRead, original, 'star');

  assert.equal(rolledBack.is_starred, false);
  assert.equal(rolledBack.is_read, true);
  assert.deepEqual(rolledBack.labels, ['INBOX']);
});

test('conversation rollback restores only its aggregate while preserving newer intent', () => {
  const original = {
    ...email(1),
    conversation_scope: true,
    member_count: 3,
    unread_count: 2,
    star_state: 'none',
    label_coverage: { Project: 'some' },
  };
  const afterStar = applyEmailAction(original, 'star');
  const afterNewerRead = applyEmailAction(afterStar, 'mark_read');

  const rolledBack = rollbackEmailAction(afterNewerRead, original, 'star');

  assert.equal(rolledBack.star_state, 'none');
  assert.equal(rolledBack.unread_count, 0);
  assert.equal(rolledBack.is_starred, false);
  assert.equal(rolledBack.is_read, true);
});

test('thread rollback restores the failed delta while preserving a newer message action', () => {
  const before = { thread_id: 'generated-thread', emails: [email(1), email(2)] };
  const afterStar = {
    ...before,
    emails: before.emails.map(message => applyEmailAction(message, 'star')),
  };
  const afterNewerRead = {
    ...afterStar,
    emails: afterStar.emails.map(message => applyEmailAction(message, 'mark_read')),
  };

  const rolledBack = rollbackThreadAction(afterNewerRead, before, 'star');

  assert.ok(rolledBack.emails.every(message => message.is_starred === false));
  assert.ok(rolledBack.emails.every(message => message.is_read === true));
});

test('older in-place rollback never resurrects a row removed by a newer action', () => {
  const original = [email(1), email(2)];
  const starSnapshot = captureInboxAction(original, 1, [1]);

  const restored = restoreInboxAction([email(2)], starSnapshot, 'star', false);

  assert.deepEqual(restored.map(item => item.id), [2]);
});

test('rollback of the removal itself restores the missing row', () => {
  const original = [email(1), email(2)];
  const archiveSnapshot = captureInboxAction(original, 1, [1]);

  const restored = restoreInboxAction([email(2)], archiveSnapshot, 'archive', true);

  assert.deepEqual(restored.map(item => item.id), [1, 2]);
});

test('per-email submissions preserve invocation order while unrelated mail stays parallel', async () => {
  const queue = createMailActionSubmissionQueue();
  const order = [];
  let releaseFirst;
  const firstGate = new Promise(resolve => { releaseFirst = resolve; });

  const first = queue.enqueue([1], async () => {
    order.push('first-start');
    await firstGate;
    order.push('first-end');
  });
  const second = queue.enqueue([1], async () => { order.push('second'); });
  const unrelated = queue.enqueue([2], async () => { order.push('unrelated'); });

  await unrelated;
  assert.deepEqual(order, ['first-start', 'unrelated']);
  releaseFirst();
  await Promise.all([first, second]);
  assert.deepEqual(order, ['first-start', 'unrelated', 'first-end', 'second']);
});

test('an in-flight action that becomes uncertain keeps already-queued newer intent blocked', async () => {
  const queue = createMailActionSubmissionQueue();
  const order = [];
  let makeUncertain;
  let releaseUncertain;
  const first = queue.enqueue([1], async queueControl => {
    await new Promise((resolve, reject) => {
      makeUncertain = () => {
        releaseUncertain = queueControl.hold();
        order.push('uncertain');
        reject(new Error('outcome unknown'));
      };
    });
  });
  while (!makeUncertain) await new Promise(resolve => setImmediate(resolve));

  const newer = queue.enqueue([1], async () => { order.push('newer-unstar'); });
  const unrelated = queue.enqueue([2], async () => { order.push('unrelated'); });
  const firstRejected = assert.rejects(first, /outcome unknown/);
  makeUncertain();

  await Promise.all([firstRejected, unrelated]);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(order, ['uncertain', 'unrelated']);
  releaseUncertain();
  await newer;
  assert.deepEqual(order, ['uncertain', 'unrelated', 'newer-unstar']);
});

test('archive remains visible in All Mail while its Inbox label is removed', () => {
  const result = optimisticInboxAction({
    emails: [email(7)],
    selectedId: 7,
    emailIds: [7],
    action: 'archive',
    mailbox: 'ALL',
  });

  assert.equal(result.emails.length, 1);
  assert.deepEqual(result.emails[0].labels, ['UNREAD']);
  assert.equal(result.selectedId, 7);
});

test('label actions keep flags and canonical labels aligned', () => {
  const inconsistent = { ...email(1, ['INBOX']), is_read: false };
  const starred = applyEmailAction(inconsistent, 'star');
  const read = applyEmailAction(starred, 'mark_read');
  const spam = applyEmailAction(read, 'spam');

  assert.equal(starred.is_starred, true);
  assert.equal(starred.is_read, true);
  assert.equal(read.is_read, true);
  assert.equal(read.labels.includes('UNREAD'), false);
  assert.equal(spam.is_spam, true);
  assert.equal(spam.labels.includes('INBOX'), false);
});

test('mailbox removal rules preserve starred and all-mail results', () => {
  assert.equal(actionRemovesFromMailbox('archive', 'INBOX'), true);
  assert.equal(actionRemovesFromMailbox('archive', 'STARRED'), false);
  assert.equal(actionRemovesFromMailbox('trash', 'STARRED'), true);
  assert.equal(actionRemovesFromMailbox('untrash', 'TRASH'), true);
  assert.equal(actionRemovesFromMailbox('unspam', 'SPAM'), true);
  assert.equal(actionRemovesFromMailbox('remove_label', 'Label_12', 'Label_12'), true);
  assert.equal(actionRemovesFromMailbox('remove_label', 'Label_13', 'Label_12'), false);
});

test('undo eligibility is server-deadline and state driven', () => {
  const now = Date.parse('2026-08-30T12:00:00Z');
  const operation = { state: 'staged', undo_until: '2026-08-30T12:00:10Z' };

  assert.equal(remainingUndoMs(operation.undo_until, now), 10_000);
  assert.equal(canUndoAction(operation, now), true);
  assert.equal(canUndoAction({ ...operation, state: 'processing' }, now), false);
  assert.equal(canUndoAction(operation, now + 11_000), false);
});

test('client idempotency keys come from the supplied secure UUID source', () => {
  assert.equal(idempotencyKey(() => 'generated-uuid'), 'generated-uuid');
  assert.equal(actionPastTense('archive', 2), '2 emails archived');
  assert.equal(actionPastTense('archive', 2, '', 'conversation'), '2 conversations archived');
});

test('ambiguous action failures are recognized as network outcomes', () => {
  assert.equal(isMailActionNetworkError(new TypeError('Failed to fetch')), true);
  assert.equal(isMailActionNetworkError(new Error('HTTP 500')), false);
});

test('only newly failed durable operations require inbox reconciliation', () => {
  const operations = [
    { request_id: 'known', items: [{ state: 'failed' }] },
    { request_id: 'new', items: [{ state: 'applied' }, { state: 'failed' }] },
    { request_id: 'active', items: [{ state: 'retry_wait' }] },
  ];

  assert.deepEqual([...failedMailActionRequestIds(operations)], ['known', 'new']);
  assert.equal(hasNewFailedMailActions(operations, new Set(['known'])), true);
  assert.equal(hasNewFailedMailActions(operations, new Set(['known', 'new'])), false);
});
