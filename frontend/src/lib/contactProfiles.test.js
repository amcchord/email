import assert from 'node:assert/strict';
import test from 'node:test';

import {
  contactComposeIntent,
  contactConversationAnchorForAccount,
  contactConversationNavigationIntent,
  createContactProfilePayload,
  createContactQueryPayload,
  normalizeContactProfileResponse,
  normalizeContactQueryResponse,
} from './contactProfiles.js';

const ACCOUNT_ID = 17;
const CONTACT_KEY = 'a'.repeat(64);

function contact(overrides = {}) {
  return {
    account_id: ACCOUNT_ID,
    contact_key: CONTACT_KEY,
    name: 'Jordan Example',
    address: 'jordan@example.test',
    formatted: 'Jordan Example <jordan@example.test>',
    relationship: 'bidirectional',
    observed_message_count: 9,
    observed_received_count: 5,
    observed_sent_count: 4,
    observed_conversation_count: 3,
    observed_first_at: '2026-08-01T12:00:00Z',
    observed_last_at: '2026-08-30T12:00:00Z',
    observed_last_received_at: '2026-08-30T12:00:00Z',
    observed_last_sent_at: '2026-08-29T12:00:00Z',
    ...overrides,
  };
}

function coverage() {
  return {
    rows_scanned: 4000,
    row_limit: 4000,
    history_may_be_truncated: true,
    observed_oldest_at: '2026-01-01T00:00:00Z',
    observed_newest_at: '2026-08-30T12:00:00Z',
  };
}

test('contact query normalization is exact-account, bounded, and content-free', () => {
  const normalized = normalizeContactQueryResponse({
    account_id: ACCOUNT_ID,
    page: 1,
    page_size: 50,
    total: 1,
    total_pages: 1,
    coverage: coverage(),
    contacts: [contact({ subject: 'must never render', body_html: '<p>sentinel</p>' })],
  }, { accountId: ACCOUNT_ID });

  assert.equal(normalized.account_id, ACCOUNT_ID);
  assert.equal(normalized.contacts[0].address, 'jordan@example.test');
  assert.equal(normalized.contacts[0].account_id, ACCOUNT_ID);
  assert.equal('subject' in normalized.contacts[0], false);
  assert.equal('body_html' in normalized.contacts[0], false);
  assert.equal(normalized.coverage.history_may_be_truncated, true);
});

test('contact responses reject wrong accounts, malformed mailboxes, keys, and duplicates', () => {
  const response = {
    account_id: ACCOUNT_ID,
    page: 1,
    page_size: 50,
    total: 1,
    total_pages: 1,
    coverage: coverage(),
    contacts: [contact()],
  };

  assert.throws(() => normalizeContactQueryResponse(response, { accountId: 99 }), /requested account/);
  assert.throws(() => normalizeContactQueryResponse({ ...response, contacts: [contact({ account_id: 99 })] }, { accountId: ACCOUNT_ID }), /requested account/);
  assert.throws(() => normalizeContactQueryResponse({ ...response, contacts: [contact({ contact_key: 'short' })] }, { accountId: ACCOUNT_ID }), /contact_key/);
  assert.throws(() => normalizeContactQueryResponse({ ...response, contacts: [contact({ formatted: 'other@example.test' })] }, { accountId: ACCOUNT_ID }), /mailbox/);
  assert.throws(() => normalizeContactQueryResponse({ ...response, contacts: [contact(), contact()] }, { accountId: ACCOUNT_ID }), /duplicate/);
});

test('profile normalization retains only exact recent account-authoritative pointers', () => {
  const normalized = normalizeContactProfileResponse({
    account_id: ACCOUNT_ID,
    contact: contact(),
    recent_conversations: [{
      account_id: ACCOUNT_ID,
      anchor_email_id: 701,
      thread_id: 'generated-thread-7',
      observed_last_at: '2026-08-30T12:00:00Z',
      observed_message_count: 3,
      direction: 'bidirectional',
      subject: 'must never render',
    }],
  }, { accountId: ACCOUNT_ID, contactKey: CONTACT_KEY });

  assert.deepEqual(normalized.recent_conversations[0], {
    account_id: ACCOUNT_ID,
    anchor_email_id: 701,
    thread_id: 'generated-thread-7',
    observed_last_at: '2026-08-30T12:00:00Z',
    observed_message_count: 3,
    direction: 'bidirectional',
  });
  assert.throws(() => normalizeContactProfileResponse({
    account_id: ACCOUNT_ID,
    contact: contact(),
    recent_conversations: [{
      account_id: 99,
      anchor_email_id: 701,
      thread_id: null,
      observed_last_at: '2026-08-30T12:00:00Z',
      observed_message_count: 1,
      direction: 'inbound_only',
    }],
  }, { accountId: ACCOUNT_ID, contactKey: CONTACT_KEY }), /requested account/);
});

test('query/profile payloads expose only the frozen bounded contract', () => {
  assert.deepEqual(createContactQueryPayload({
    accountId: ACCOUNT_ID,
    query: '  Jordan  ',
    relationship: 'inbound_only',
    page: 2,
    pageSize: 25,
  }), {
    account_id: ACCOUNT_ID,
    query: 'Jordan',
    relationship: 'inbound_only',
    page: 2,
    page_size: 25,
  });
  assert.deepEqual(createContactProfilePayload({ accountId: ACCOUNT_ID, contactKey: CONTACT_KEY }), {
    account_id: ACCOUNT_ID,
    contact_key: CONTACT_KEY,
    recent_limit: 8,
  });
  assert.throws(() => createContactProfilePayload({
    accountId: ACCOUNT_ID,
    contactKey: CONTACT_KEY,
    recentLimit: 21,
  }), /recent_limit/);
  assert.throws(() => createContactQueryPayload({ accountId: ACCOUNT_ID, relationship: 'frequent' }), /relationship/);
});

test('contact actions create one exact Compose recipient and one exact Inbox intent', () => {
  const compose = contactComposeIntent(ACCOUNT_ID, contact());
  assert.equal(compose.account_id, ACCOUNT_ID);
  assert.deepEqual(compose.to, ['Jordan Example <jordan@example.test>']);
  assert.deepEqual(compose.cc || [], []);
  assert.deepEqual(compose.bcc || [], []);

  assert.deepEqual(contactConversationNavigationIntent({
    account_id: ACCOUNT_ID,
    anchor_email_id: 701,
    thread_id: null,
    observed_last_at: '2026-08-30T12:00:00Z',
    observed_message_count: 1,
    direction: 'outbound_only',
  }), {
    account_id: ACCOUNT_ID,
    anchor_email_id: 701,
    thread_id: null,
    observed_last_at: '2026-08-30T12:00:00Z',
    observed_message_count: 1,
    direction: 'outbound_only',
  });

  const directOpen = {
    account_id: ACCOUNT_ID,
    anchor_email_id: 701,
    thread_id: 'generated-thread-7',
    observed_last_at: '2026-08-30T12:00:00Z',
    observed_message_count: 3,
    direction: 'bidirectional',
  };
  assert.equal(contactConversationAnchorForAccount(directOpen, ACCOUNT_ID), 701);
  assert.throws(() => contactConversationAnchorForAccount(directOpen, 99), /active account/);
});
