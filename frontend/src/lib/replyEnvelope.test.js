import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildReplyEnvelope,
  normalizeReplyAddress,
  REPLY_ENVELOPE_MODES,
  REPLY_ENVELOPE_UNAVAILABLE,
  replyCompletionStillCurrent,
  resolveReplySourceAccount,
} from './replyEnvelope.js';

const accounts = [
  {
    id: 11,
    email: 'first-owner@example.test',
    is_active: true,
  },
  {
    id: 22,
    email: 'Second.Owner@Example.Test',
    is_active: true,
    aliases: ['second.alias@example.test'],
  },
];

function incoming(overrides = {}) {
  return {
    id: 3001,
    account_id: 22,
    account_email: ' SECOND.OWNER@example.test ',
    is_sent: false,
    from_address: 'sender@example.test',
    reply_to: null,
    to_addresses: [
      { name: 'Second owner', address: 'second.owner@example.test' },
      'FIRST-OWNER@example.test',
      'team@example.test',
    ],
    cc_addresses: [
      'Team@Example.Test',
      { name: 'Partner', address: 'partner@example.test' },
      'second.alias@example.test',
    ],
    subject: 'Generated review',
    message_id_header: '<generated-message-3001@example.test>',
    gmail_thread_id: 'generated-thread-3001',
    ...overrides,
  };
}

function sent(overrides = {}) {
  return {
    id: 3002,
    account_id: 11,
    account_email: 'first-owner@example.test',
    is_sent: true,
    from_address: 'first-owner@example.test',
    to_addresses: [
      'CLIENT@example.test',
      { name: 'Second owner decoy', address: 'second.owner@example.test' },
      'client@example.test',
      'reviewer@example.test',
    ],
    cc_addresses: [
      'Reviewer@Example.Test',
      'observer@example.test',
      'second.alias@example.test',
    ],
    bcc_addresses: ['hidden-original@example.test'],
    subject: 'Re: Generated outbound',
    message_id_header: '<generated-message-3002@example.test>',
    gmail_thread_id: 'generated-thread-3002',
    ...overrides,
  };
}

test('address normalization trims, case-folds, and accepts API/display shapes', () => {
  assert.equal(normalizeReplyAddress('  Person <Mailbox@Example.Test>  '), 'mailbox@example.test');
  assert.equal(normalizeReplyAddress({ name: 'Person', address: ' Mailbox@Example.Test ' }), 'mailbox@example.test');
  assert.equal(normalizeReplyAddress('mailto:Mailbox@Example.Test'), 'mailbox@example.test');
  assert.equal(normalizeReplyAddress('"Doe, Jane" <Jane@Example.Test>'), 'jane@example.test');
  assert.equal(normalizeReplyAddress('two@example.test,three@example.test'), null);
  assert.equal(normalizeReplyAddress('One <one@example.test>, Two <two@example.test>'), null);
  assert.equal(normalizeReplyAddress('not-a-mailbox'), null);
});

test('incoming Reply uses the exact second account and Reply-To as a send-ready envelope', () => {
  const result = buildReplyEnvelope({
    message: incoming({ reply_to: ' Support <REPLY@Example.Test> ' }),
    accounts,
    mode: REPLY_ENVELOPE_MODES.REPLY,
  });

  assert.deepEqual(result, {
    available: true,
    reason: null,
    sourceAccount: { id: 22, email: 'second.owner@example.test' },
    envelope: {
      account_id: 22,
      source_email_id: 3001,
      to: ['reply@example.test'],
      cc: [],
      bcc: [],
      subject: 'Re: Generated review',
      in_reply_to: '<generated-message-3001@example.test>',
      references: '<generated-message-3001@example.test>',
      thread_id: 'generated-thread-3001',
    },
  });
  assert.deepEqual(Object.keys(result.envelope).sort(), [
    'account_id', 'bcc', 'cc', 'in_reply_to', 'references', 'source_email_id', 'subject', 'thread_id', 'to',
  ]);
});

test('incoming Reply All dedupes and removes every owned account and alias', () => {
  const result = buildReplyEnvelope({
    message: incoming(),
    accounts,
    mode: REPLY_ENVELOPE_MODES.REPLY_ALL,
  });

  assert.equal(result.available, true);
  assert.deepEqual(result.envelope.to, ['sender@example.test', 'team@example.test']);
  assert.deepEqual(result.envelope.cc, ['partner@example.test']);
  assert.doesNotMatch(JSON.stringify(result.envelope), /first-owner|second\.owner|second\.alias/iu);
});

test('reply metadata extends the existing References chain exactly once', () => {
  const result = buildReplyEnvelope({
    message: incoming({
      references_header: '<root@example.test> <parent@example.test>',
    }),
    accounts,
  });
  const alreadyCurrent = buildReplyEnvelope({
    message: incoming({
      references_header: '<root@example.test> <generated-message-3001@example.test>',
    }),
    accounts,
  });

  assert.equal(
    result.envelope.references,
    '<root@example.test> <parent@example.test> <generated-message-3001@example.test>',
  );
  assert.equal(
    alreadyCurrent.envelope.references,
    '<root@example.test> <generated-message-3001@example.test>',
  );
});

test('reply completion rejects same-id and same-body ABA reopen races', () => {
  const completion = {
    capturedGeneration: 4,
    currentGeneration: 4,
    capturedEmailId: 317,
    currentEmailId: 317,
    capturedBody: 'Generated reply',
    currentBody: 'Generated reply',
  };

  assert.equal(replyCompletionStillCurrent(completion), true);
  assert.equal(replyCompletionStillCurrent({ ...completion, currentGeneration: 6 }), false);
  assert.equal(replyCompletionStillCurrent({ ...completion, currentEmailId: 318 }), false);
  assert.equal(replyCompletionStillCurrent({ ...completion, currentBody: 'New draft' }), false);
});

test('sent Reply targets only the first external original To recipient', () => {
  const result = buildReplyEnvelope({ message: sent(), accounts });

  assert.equal(result.available, true);
  assert.equal(result.envelope.account_id, 11);
  assert.deepEqual(result.envelope.to, ['client@example.test']);
  assert.deepEqual(result.envelope.cc, []);
});

test('sent Reply All preserves To/Cc visibility, dedupes, strips owned identities, and never copies Bcc', () => {
  const result = buildReplyEnvelope({
    message: sent(),
    accounts,
    mode: REPLY_ENVELOPE_MODES.REPLY_ALL,
  });

  assert.equal(result.available, true);
  assert.deepEqual(result.envelope.to, ['client@example.test', 'reviewer@example.test']);
  assert.deepEqual(result.envelope.cc, ['observer@example.test']);
  assert.deepEqual(result.envelope.bcc, []);
  assert.doesNotMatch(JSON.stringify(result.envelope), /hidden-original|first-owner|second\.owner|second\.alias/iu);
});

test('sent Reply All promotes an external Cc when the original To list contains only owned identities', () => {
  const result = buildReplyEnvelope({
    message: sent({
      to_addresses: ['first-owner@example.test', 'second.owner@example.test'],
      cc_addresses: ['only-external@example.test'],
    }),
    accounts,
    mode: REPLY_ENVELOPE_MODES.REPLY_ALL,
  });

  assert.equal(result.available, true);
  assert.deepEqual(result.envelope.to, ['only-external@example.test']);
  assert.deepEqual(result.envelope.cc, []);
});

test('source resolution never falls back for missing, unknown, mismatched, ambiguous, or inactive identities', () => {
  const cases = [
    [incoming({ account_id: null, account_email: null }), accounts, REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_IDENTITY_MISSING],
    [incoming({ account_id: 999, account_email: 'missing@example.test' }), accounts, REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_NOT_FOUND],
    [incoming({ account_id: 11, account_email: 'second.owner@example.test' }), accounts, REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_MISMATCH],
    [incoming(), [...accounts, { id: 33, email: 'second.owner@example.test', is_active: true }], REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_AMBIGUOUS],
    [incoming(), accounts.map(account => account.id === 22 ? { ...account, is_active: false } : account), REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_INACTIVE],
  ];

  for (const [message, accountList, reason] of cases) {
    const result = resolveReplySourceAccount({ message, accounts: accountList });
    assert.equal(result.available, false);
    assert.equal(result.reason, reason);
    assert.equal(result.envelope, null);
    assert.equal(result.sourceAccount, null);
  }
});

test('reply envelopes require a positive authoritative source message id', () => {
  for (const id of [null, undefined, 0, -1, 'not-an-id']) {
    const result = buildReplyEnvelope({ message: incoming({ id }), accounts });
    assert.equal(result.available, false);
    assert.equal(result.reason, REPLY_ENVELOPE_UNAVAILABLE.SOURCE_MESSAGE_ID_INVALID);
    assert.equal(result.envelope, null);
  }
});

test('account id or case-folded account email can independently identify the exact active source', () => {
  const byId = resolveReplySourceAccount({
    message: incoming({ account_email: null }),
    accounts,
  });
  const byEmail = resolveReplySourceAccount({
    message: incoming({ account_id: null, account_email: ' SECOND.OWNER@EXAMPLE.TEST ' }),
    accounts,
  });

  assert.deepEqual(byId.sourceAccount, { id: 22, email: 'second.owner@example.test' });
  assert.deepEqual(byEmail.sourceAccount, { id: 22, email: 'second.owner@example.test' });
});

test('invalid direction, recipient shapes, owned sender, and empty sent targets fail closed', () => {
  const cases = [
    [incoming({ is_sent: undefined }), REPLY_ENVELOPE_UNAVAILABLE.MESSAGE_DIRECTION_MISSING, REPLY_ENVELOPE_MODES.REPLY],
    [incoming({ to_addresses: ['valid@example.test', 'invalid'] }), REPLY_ENVELOPE_UNAVAILABLE.RECIPIENT_LIST_INVALID, REPLY_ENVELOPE_MODES.REPLY_ALL],
    [incoming({ from_address: 'SECOND.ALIAS@example.test' }), REPLY_ENVELOPE_UNAVAILABLE.REPLY_TARGET_IS_OWNED, REPLY_ENVELOPE_MODES.REPLY],
    [incoming({ from_address: 'invalid' }), REPLY_ENVELOPE_UNAVAILABLE.REPLY_TARGET_INVALID, REPLY_ENVELOPE_MODES.REPLY],
    [sent({ to_addresses: ['first-owner@example.test', 'second.owner@example.test'] }), REPLY_ENVELOPE_UNAVAILABLE.REPLY_TARGET_MISSING, REPLY_ENVELOPE_MODES.REPLY],
  ];

  for (const [message, reason, mode] of cases) {
    const result = buildReplyEnvelope({ message, accounts, mode });
    assert.deepEqual(result, {
      available: false,
      reason,
      sourceAccount: null,
      envelope: null,
    });
  }
});

test('malformed owned account identities and unsupported modes fail before exposing an envelope', () => {
  const badOwned = buildReplyEnvelope({
    message: incoming(),
    accounts: [...accounts, { id: 33, email: 'invalid', is_active: true }],
  });
  const badMode = buildReplyEnvelope({
    message: incoming(),
    accounts,
    mode: 'reply-sometimes',
  });

  assert.equal(badOwned.reason, REPLY_ENVELOPE_UNAVAILABLE.OWNED_IDENTITY_INVALID);
  assert.equal(badOwned.envelope, null);
  assert.equal(badMode.reason, REPLY_ENVELOPE_UNAVAILABLE.INVALID_MODE);
  assert.equal(badMode.envelope, null);
});
