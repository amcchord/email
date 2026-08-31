import assert from 'node:assert/strict';
import test from 'node:test';
import {
  commitRecipientInput,
  formatMailbox,
  mailboxIdentity,
  normalizeMailbox,
  normalizeRecipientSuggestion,
  normalizeRecipientSuggestions,
  parseMailbox,
  parseMailboxList,
  pendingMailboxHasOpenSyntax,
  splitMailboxList,
} from './recipientField.js';


test('quoted display-name commas stay inside one mailbox while pasted lists split safely', () => {
  const source = '"Doe, Jane" <Jane@Example.COM>, John Smith <john@example.com>; third@example.net\nlast@example.org';
  assert.deepEqual(splitMailboxList(source), [
    '"Doe, Jane" <Jane@Example.COM>',
    'John Smith <john@example.com>',
    'third@example.net',
    'last@example.org',
  ]);
  assert.deepEqual(parseMailboxList(source), {
    mailboxes: [
      '"Doe, Jane" <Jane@example.com>',
      'John Smith <john@example.com>',
      'third@example.net',
      'last@example.org',
    ],
    invalid: [],
  });
});


test('mailboxes normalize names and domains without losing escaped display names', () => {
  assert.equal(formatMailbox({ name: '  Jane   Doe  ', address: 'Jane@EXAMPLE.com' }), 'Jane Doe <Jane@example.com>');
  assert.equal(formatMailbox({ name: 'Doe, "JJ"', address: 'jane@example.com' }), '"Doe, \\"JJ\\"" <jane@example.com>');
  assert.equal(normalizeMailbox('"Doe, \\"JJ\\"" <jane@EXAMPLE.com>'), '"Doe, \\"JJ\\"" <jane@example.com>');
  assert.deepEqual(parseMailbox('Jane Doe <jane@example.com>'), {
    address: 'jane@example.com',
    name: 'Jane Doe',
    mailbox: 'Jane Doe <jane@example.com>',
    identity: 'jane@example.com',
  });
  assert.equal(mailboxIdentity('JANE@Example.com'), 'jane@example.com');
});


test('invalid and header-like input fails closed while valid siblings remain available', () => {
  assert.equal(normalizeMailbox('not-an-email'), null);
  assert.equal(normalizeMailbox('person@localhost'), null);
  assert.equal(normalizeMailbox('josé@example.com'), null);
  assert.equal(normalizeMailbox('bad\r\nBcc: hidden@example.com'), null);
  assert.equal(normalizeMailbox('Jane <jane@example.com> trailing'), null);
  assert.deepEqual(parseMailboxList('valid@example.com, broken, other@example.com'), {
    mailboxes: ['valid@example.com', 'other@example.com'],
    invalid: ['broken'],
  });
  assert.equal(pendingMailboxHasOpenSyntax('"Doe, Jane'), true);
  assert.equal(pendingMailboxHasOpenSyntax('Jane <jane@example.com'), true);
  assert.equal(pendingMailboxHasOpenSyntax('Jane <jane@example.com>'), false);
});


test('committing recipients detects duplicates in the active and sibling fields', () => {
  const result = commitRecipientInput('New <new@example.com>, DUP@example.com, copy@example.com, bad', {
    recipients: ['Existing <dup@example.com>'],
    recipientCollections: [['Copy <copy@example.com>']],
    field: 'to',
  });
  assert.deepEqual(result, {
    recipients: ['Existing <dup@example.com>', 'New <new@example.com>'],
    added: ['New <new@example.com>'],
    duplicates: ['DUP@example.com', 'copy@example.com'],
    invalid: ['bad'],
  });
});


test('the optional duplicate callback can enforce integration-specific ownership rules', () => {
  const result = commitRecipientInput('blocked@example.com, allowed@example.com', {
    field: 'bcc',
    isDuplicate: ({ identity, field }) => field === 'bcc' && identity === 'blocked@example.com',
  });
  assert.deepEqual(result.added, ['allowed@example.com']);
  assert.deepEqual(result.duplicates, ['blocked@example.com']);
});


test('suggestions accept common loader shapes and exclude committed identities', () => {
  assert.deepEqual(normalizeRecipientSuggestion({
    email: 'jane@EXAMPLE.com', display_name: 'Jane Doe', source: 'history',
  }), {
    email: 'jane@EXAMPLE.com',
    display_name: 'Jane Doe',
    source: 'history',
    address: 'jane@example.com',
    name: 'Jane Doe',
    mailbox: 'Jane Doe <jane@example.com>',
    identity: 'jane@example.com',
    label: 'Jane Doe',
    detail: 'jane@example.com',
  });
  assert.deepEqual(normalizeRecipientSuggestions({ suggestions: [
    'existing@example.com',
    { email: 'new@example.com', name: 'New Person' },
    { address: 'NEW@example.com', name: 'Duplicate New' },
    { email: 'bad' },
  ] }, { recipients: ['existing@example.com'] }).map(item => item.mailbox), [
    'New Person <new@example.com>',
  ]);
});
