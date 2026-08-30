import assert from 'node:assert/strict';
import test from 'node:test';
import {
  actionPastTense,
  actionRemovesFromMailbox,
  applyEmailAction,
  canUndoAction,
  captureInboxAction,
  idempotencyKey,
  optimisticInboxAction,
  remainingUndoMs,
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

  const restored = restoreInboxAction(optimistic, snapshot);

  assert.deepEqual(restored[0], original[0]);
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
});
