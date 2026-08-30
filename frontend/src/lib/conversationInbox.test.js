import assert from 'node:assert/strict';
import test from 'node:test';

import {
  actionScopeForEmails,
  defaultThreadMessageId,
  nextConversationFocus,
  normalizeConversationList,
  normalizeConversationSummary,
} from './conversationInbox.js';

const conversation = {
  conversation_key: '7:thread-generated',
  account_id: 7,
  account_email: 'owner@example.test',
  anchor_email_id: 42,
  gmail_thread_id: 'thread-generated',
  labels: ['INBOX', 'STARRED'],
  unread_count: 2,
  star_state: 'some',
  member_count: 3,
  matched_count: 1,
};

test('conversation summaries retain an anchor while exposing aggregate row state', () => {
  const row = normalizeConversationSummary(conversation);
  assert.equal(row.id, 42);
  assert.equal(row.is_read, false);
  assert.equal(row.is_starred, true);
  assert.equal(row.is_trash, false);
  assert.equal(row.conversation_scope, true);
});

test('aggregate placement labels never overwrite the matching anchor mailbox state', () => {
  const row = normalizeConversationSummary({
    ...conversation,
    labels: ['INBOX', 'SENT', 'TRASH'],
    is_draft: false,
    is_sent: false,
    is_trash: false,
    is_spam: false,
  });

  assert.equal(row.is_sent, false);
  assert.equal(row.is_trash, false);
  assert.equal(row.is_spam, false);
});

test('conversation list totals remain conversation totals', () => {
  const result = normalizeConversationList({ conversations: [conversation], total: 9, page: 1, page_size: 50, total_pages: 1 });
  assert.equal(result.emails.length, 1);
  assert.equal(result.total, 9);
});

test('conversation scope is sent only when every selected anchor is a conversation row', () => {
  const row = normalizeConversationSummary(conversation);
  assert.equal(actionScopeForEmails([42], [row]), 'conversations');
  assert.equal(actionScopeForEmails([42, 99], [row, { id: 99 }]), null);
});

test('focus advances to the next remaining conversation and then the previous one', () => {
  const rows = [{ id: 1 }, { id: 2 }, { id: 3 }];
  assert.equal(nextConversationFocus(rows, 2, [2]), 3);
  assert.equal(nextConversationFocus(rows, 3, [3]), 2);
  assert.equal(nextConversationFocus([{ id: 1 }], 1, [1]), null);
});

test('thread reader starts at the oldest unread message or the latest message', () => {
  assert.equal(defaultThreadMessageId({ emails: [{ id: 1, is_read: true }, { id: 2, is_read: false }, { id: 3, is_read: false }] }), 2);
  assert.equal(defaultThreadMessageId({ emails: [{ id: 1, is_read: true }, { id: 2, is_read: true }] }), 2);
});
