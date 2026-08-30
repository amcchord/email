import assert from 'node:assert/strict';
import test from 'node:test';

import {
  addPendingReplyId,
  capturedReplyStillActive,
  isCurrentFlowThreadRequest,
  newestThreadMessage,
  reconcileNeedsReplyRemoval,
  removePendingReplyId,
} from './flow/replyActionState.js';

test('newest thread message follows the configured thread order', () => {
  const messages = [
    { id: 'newest', message_id_header: '<newest@example.test>' },
    { id: 'middle', message_id_header: '<middle@example.test>' },
    { id: 'oldest', message_id_header: '<oldest@example.test>' },
  ];

  assert.equal(newestThreadMessage(messages, 'newest_first')?.id, 'newest');
  assert.equal(newestThreadMessage([...messages].reverse(), 'oldest_first')?.id, 'newest');
  assert.equal(newestThreadMessage([], 'newest_first'), null);
  assert.equal(newestThreadMessage(null, 'oldest_first'), null);
});

test('Flow accepts thread data only for the newest matching reply identity', () => {
  const current = {
    requestedGeneration: 8,
    currentGeneration: 8,
    replyViewOpen: true,
    requestedEmailId: 202,
    activeEmailId: 202,
    requestedThreadId: 'generated-thread-b',
    activeThreadId: 'generated-thread-b',
    requestedSource: 'needs_reply',
    activeSource: 'needs_reply',
  };

  assert.equal(isCurrentFlowThreadRequest(current), true);
  assert.equal(isCurrentFlowThreadRequest({ ...current, requestedGeneration: 7 }), false);
  assert.equal(isCurrentFlowThreadRequest({ ...current, activeEmailId: 201 }), false);
  assert.equal(isCurrentFlowThreadRequest({ ...current, activeThreadId: 'generated-thread-a' }), false);
  assert.equal(isCurrentFlowThreadRequest({ ...current, activeSource: 'thread' }), false);
  assert.equal(isCurrentFlowThreadRequest({ ...current, replyViewOpen: false }), false);
});

test('pending reply mutation ids reject duplicate submission until completion', () => {
  const first = addPendingReplyId([], 101);
  const duplicate = addPendingReplyId(first, 101);

  assert.deepEqual(first, [101]);
  assert.equal(duplicate, first);
  assert.deepEqual(removePendingReplyId(first, 101), []);
});

test('delayed completion for A removes only A after navigation to B', () => {
  const result = reconcileNeedsReplyRemoval({
    emails: [{ id: 101 }, { id: 102 }, { id: 103 }],
    total: 3,
    removedId: 101,
    activeEmailId: 102,
    activeIndex: 1,
  });

  assert.deepEqual(result.emails.map(email => email.id), [102, 103]);
  assert.equal(result.activeEmailId, 102);
  assert.equal(result.activeIndex, 0);
  assert.equal(result.total, 2);
  assert.equal(result.removed, true);
});

test('removing the active reply advances from the captured position', () => {
  const result = reconcileNeedsReplyRemoval({
    emails: [{ id: 101 }, { id: 102 }, { id: 103 }],
    total: 3,
    removedId: 102,
    activeEmailId: 102,
    activeIndex: 1,
  });

  assert.deepEqual(result.emails.map(email => email.id), [101, 103]);
  assert.equal(result.activeEmailId, 103);
  assert.equal(result.activeIndex, 1);
});

test('delayed A completion cannot close or clear newer cross-source reply B', () => {
  const newerReply = { id: 202, draft: 'Keep this generated B draft' };
  const shouldClose = capturedReplyStillActive(201, newerReply.id);
  const preservedReply = shouldClose ? null : newerReply;

  assert.equal(shouldClose, false);
  assert.deepEqual(preservedReply, newerReply);
  assert.equal(capturedReplyStillActive(201, 201), true);
});

test('last needs-reply A completion preserves newer cross-source B and its draft', () => {
  const newerReply = { id: 202, draft: 'Keep this generated cross-source draft' };
  const result = reconcileNeedsReplyRemoval({
    emails: [{ id: 201 }],
    total: 1,
    removedId: 201,
    activeEmailId: newerReply.id,
    activeIndex: 0,
  });
  const preservedReply = result.activeEmailId === newerReply.id ? newerReply : null;

  assert.deepEqual(result.emails, []);
  assert.equal(result.total, 0);
  assert.equal(result.activeEmailId, newerReply.id);
  assert.equal(result.removed, true);
  assert.deepEqual(preservedReply, newerReply);
});
