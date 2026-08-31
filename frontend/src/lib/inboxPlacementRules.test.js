import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createInboxRulePayload,
  inboxRuleUndoOperation,
  normalizeInboxRule,
  normalizeInboxRuleCandidate,
  normalizeInboxRuleMutation,
  updateInboxRulePayload,
} from './inboxPlacementRules.js';

const RULE_ID = '9a14d2a4-7832-4e37-995c-dcb085ac6ed5';
const CREATE_ID = 'c4b2a424-4834-4f0d-b104-82216418d2fd';

function rule(overrides = {}) {
  return {
    id: RULE_ID,
    account_id: 7,
    account_email: 'work@example.test',
    scope: 'sender',
    display_value: 'sender@example.test',
    placement: 'focused',
    enabled: true,
    revision: 3,
    created_at: '2026-08-31T12:00:00Z',
    updated_at: '2026-08-31T12:00:00Z',
    ...overrides,
  };
}

test('public Inbox rule IDs are strict UUID strings and display_value is required', () => {
  assert.equal(normalizeInboxRule(rule()).id, RULE_ID);
  assert.equal(normalizeInboxRule(rule()).display_value, 'sender@example.test');
  assert.throws(() => normalizeInboxRule(rule({ id: 19 })), /Inbox rule is invalid/);
  assert.throws(() => normalizeInboxRule(rule({ id: 'not-a-uuid' })), /Inbox rule is invalid/);
  assert.throws(() => normalizeInboxRule(rule({ display_value: '', display_label: 'legacy' })), /display details/);
});

test('candidate derives only server-approved non-empty scopes and matching current rules', () => {
  const candidate = normalizeInboxRuleCandidate({
    account_id: 7,
    account_email: 'work@example.test',
    anchor_email_id: 91,
    conversation_label: 'Project conversation',
    sender_address: 'sender@example.test',
    sender_domain: '',
    rules: [rule()],
  });
  assert.deepEqual(candidate.scopes.map(item => item.scope), ['conversation', 'sender']);
  assert.equal(candidate.scopes[1].current_rule.id, RULE_ID);
  assert.equal(candidate.candidate.anchor_email_id, 91);
  assert.throws(() => normalizeInboxRuleCandidate({
    account_id: 7,
    account_email: 'work@example.test',
    anchor_email_id: 91,
    conversation_label: '',
    sender_address: '',
    sender_domain: '',
    rules: [],
  }), /display details/);
});

test('create payload is exact, revision zero means absent, and updates are revisioned', () => {
  assert.deepEqual(createInboxRulePayload({
    createId: CREATE_ID,
    accountId: 7,
    anchorEmailId: 91,
    scope: 'conversation',
    placement: 'other',
  }), {
    create_id: CREATE_ID,
    account_id: 7,
    anchor_email_id: 91,
    scope: 'conversation',
    placement: 'other',
    enabled: true,
    expected_revision: 0,
  });
  assert.equal(createInboxRulePayload({
    createId: CREATE_ID,
    accountId: 7,
    anchorEmailId: 91,
    scope: 'sender',
    placement: 'other',
    currentRule: rule(),
  }).expected_revision, 3);
  assert.deepEqual(updateInboxRulePayload({ placement: 'focused', enabled: false, revision: 4 }), {
    placement: 'focused', enabled: false, revision: 4,
  });
  assert.throws(() => createInboxRulePayload({
    createId: 42,
    accountId: 7,
    anchorEmailId: 91,
    scope: 'sender',
    placement: 'other',
  }), /Rule request is invalid/);
});

test('raw mutation response combines with captured prior state for typed Undo', () => {
  const previous = rule({ placement: 'focused', revision: 3 });
  const current = rule({ placement: 'other', revision: 4 });
  const mutation = normalizeInboxRuleMutation(current, previous);
  assert.deepEqual(inboxRuleUndoOperation(mutation), {
    type: 'restore',
    ruleId: RULE_ID,
    payload: { placement: 'focused', enabled: true, revision: 4 },
  });
  const created = normalizeInboxRuleMutation(rule({ revision: 1 }), null);
  assert.deepEqual(inboxRuleUndoOperation(created), {
    type: 'delete', ruleId: RULE_ID, revision: 1,
  });
});
