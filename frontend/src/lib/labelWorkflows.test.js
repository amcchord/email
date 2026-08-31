import assert from 'node:assert/strict';
import test from 'node:test';
import {
  expandVisibleLabelTargets,
  labelActionForMode,
  labelMembership,
  mergeLabelCatalog,
  normalizeUserLabels,
  resolveLabelAccount,
  safeLabelColor,
  visibleUserLabels,
} from './labelWorkflows.js';
import {
  actionPastTense,
  applyEmailAction,
  captureInboxAction,
  optimisticInboxAction,
  rollbackEmailAction,
  restoreInboxAction,
} from './mailActionUX.js';

const accounts = [
  { id: 1, email: 'one@example.com' },
  { id: 2, email: 'two@example.com' },
];
const labels = [
  { id: 12, account_id: 1, gmail_label_id: 'Label_12', name: 'Receipts', label_type: 'user', color_bg: '#dbeafe' },
  { id: 11, account_id: 1, gmail_label_id: 'Label_11', name: 'Action', label_type: 'user' },
  { id: 13, account_id: 2, gmail_label_id: 'Label_13', name: 'Other account', label_type: 'user' },
  { id: 14, account_id: 1, gmail_label_id: 'INBOX', name: 'Inbox', label_type: 'system' },
  { id: -1, account_id: 1, gmail_label_id: 'Label_bad', name: 'Bad', label_type: 'user' },
];

const email = (id, extra = {}) => ({
  id,
  account_email: 'one@example.com',
  gmail_thread_id: `thread-${id}`,
  labels: ['INBOX', 'UNREAD'],
  is_read: false,
  is_starred: false,
  is_trash: false,
  is_spam: false,
  ...extra,
});

test('selection resolves one account and refuses mixed or unresolvable account selections', () => {
  assert.deepEqual(resolveLabelAccount([email(1)], accounts), {
    state: 'single', accountId: 1, accountEmail: 'one@example.com', message: '',
  });
  assert.equal(resolveLabelAccount([
    email(1),
    email(2, { account_email: 'two@example.com' }),
  ], accounts).state, 'mixed');
  assert.equal(resolveLabelAccount([email(3, { account_email: 'missing@example.com' })], accounts).state, 'unknown');
});

test('catalog filtering is account-scoped, user-only, stable, and merge-safe', () => {
  assert.deepEqual(normalizeUserLabels(labels, 1).map(label => label.name), ['Action', 'Receipts']);
  const merged = mergeLabelCatalog(labels, [
    { id: 15, account_id: 1, gmail_label_id: 'Label_15', name: 'New', label_type: 'user' },
  ], 1);
  assert.deepEqual(merged.map(label => label.id), [13, 15]);
});

test('membership selects remove only when every selected email has the label', () => {
  const withLabel = email(1, { labels: ['INBOX', 'Label_12'] });
  const withoutLabel = email(2);
  assert.equal(labelMembership([withLabel], 'Label_12'), 'all');
  assert.equal(labelMembership([withLabel, withoutLabel], 'Label_12'), 'some');
  assert.equal(labelActionForMode('apply', 'all'), 'remove_label');
  assert.equal(labelActionForMode('apply', 'some'), 'add_label');
  assert.equal(labelActionForMode('move', 'none'), 'move_to_label');
});

test('conversation membership preserves a partially applied label', () => {
  assert.equal(labelMembership([email(1, {
    conversation_scope: true,
    labels: ['INBOX', 'Label_12'],
    label_coverage: { Label_12: 'some' },
  })], 'Label_12'), 'some');
});

test('visible thread expansion is account-aware and deduplicated', () => {
  const visible = [
    email(1, { gmail_thread_id: 'shared' }),
    email(2, { gmail_thread_id: 'shared' }),
    email(3, { gmail_thread_id: 'other' }),
    email(4, { gmail_thread_id: 'shared', account_email: 'two@example.com' }),
  ];
  assert.deepEqual(expandVisibleLabelTargets([1], visible), [1, 2]);
});

test('blank thread identities remain isolated label targets', () => {
  const rows = [
    email(1, { gmail_thread_id: ' ' }),
    email(2, { gmail_thread_id: ' ' }),
  ];

  assert.deepEqual(expandVisibleLabelTargets([1], rows), [1]);
});

test('label projection updates flags, removes moves only from Inbox, and rolls back safely', () => {
  const original = email(1);
  assert.deepEqual(applyEmailAction(original, 'add_label', { gmailLabelId: 'Label_12' }).labels, ['INBOX', 'UNREAD', 'Label_12']);
  assert.deepEqual(
    applyEmailAction(email(1, { labels: ['INBOX', 'Label_12'] }), 'remove_label', { gmailLabelId: 'Label_12' }).labels,
    ['INBOX'],
  );
  const inboxMove = optimisticInboxAction({
    emails: [original, email(2)], selectedId: 1, emailIds: [1], action: 'move_to_label', mailbox: 'INBOX', gmailLabelId: 'Label_12',
  });
  assert.deepEqual(inboxMove.emails.map(item => item.id), [2]);
  const retainedMove = optimisticInboxAction({
    emails: [original], selectedId: 1, emailIds: [1], action: 'move_to_label', mailbox: 'ALL', gmailLabelId: 'Label_12',
  });
  assert.deepEqual(retainedMove.emails[0].labels, ['UNREAD', 'Label_12']);

  const customLabelRemoval = optimisticInboxAction({
    emails: [email(1, { labels: ['Label_12'] }), email(2, { labels: ['Label_12'] })],
    selectedId: 1,
    emailIds: [1],
    action: 'remove_label',
    mailbox: 'Label_12',
    gmailLabelId: 'Label_12',
  });
  assert.equal(customLabelRemoval.removed, true);
  assert.deepEqual(customLabelRemoval.emails.map(item => item.id), [2]);
  assert.equal(customLabelRemoval.selectedId, 2);

  const retainedLabelRemoval = optimisticInboxAction({
    emails: [email(1, { labels: ['Label_12'] })],
    selectedId: 1,
    emailIds: [1],
    action: 'remove_label',
    mailbox: 'ALL',
    gmailLabelId: 'Label_12',
  });
  assert.equal(retainedLabelRemoval.removed, false);
  assert.deepEqual(retainedLabelRemoval.emails[0].labels, []);

  const projected = retainedMove.emails[0];
  const newerStar = applyEmailAction(projected, 'star');
  const rolledBack = rollbackEmailAction(newerStar, original, 'move_to_label', { gmailLabelId: 'Label_12' });
  assert.deepEqual(rolledBack.labels, ['INBOX', 'UNREAD', 'STARRED']);

  const snapshot = captureInboxAction([original, email(2)], 1, [1]);
  const restored = restoreInboxAction([email(2)], snapshot, 'move_to_label', true, { gmailLabelId: 'Label_12' });
  assert.deepEqual(restored.map(item => item.id), [1, 2]);
});

test('chips expose catalog names/colors, collapse overflow, and reject unsafe color values', () => {
  const state = visibleUserLabels(
    email(1, { labels: ['INBOX', 'Label_11', 'Label_12'] }),
    labels,
    accounts,
    1,
  );
  assert.equal(state.labels[0].name, 'Action');
  assert.equal(state.overflow, 1);
  assert.equal(safeLabelColor('#aabbcc', 'fallback'), '#aabbcc');
  assert.equal(safeLabelColor('url(javascript:bad)', 'fallback'), 'fallback');
  assert.equal(actionPastTense('move_to_label', 3, 'Receipts'), '3 emails moved to Receipts');
  assert.equal(actionPastTense('move_to_label', 3, 'Receipts', 'conversation'), '3 conversations moved to Receipts');
});
