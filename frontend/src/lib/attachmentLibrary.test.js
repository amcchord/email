import assert from 'node:assert/strict';
import test from 'node:test';

import {
  attachmentParentAnchorForAccount,
  attachmentTransferItem,
  createAttachmentParentIntent,
  createAttachmentQueryPayload,
  normalizeAttachmentQueryResponse,
} from './attachmentLibrary.js';

const ACCOUNT_ID = 17;

function item(overrides = {}) {
  return {
    account_id: ACCOUNT_ID,
    attachment_id: 91,
    email_id: 701,
    filename: 'quarterly-report.pdf',
    content_type: 'application/pdf',
    size_bytes: 4096,
    message_date: '2026-08-30T12:00:00Z',
    sender_name: 'Jordan Example',
    sender_address: 'jordan@example.test',
    subject: 'Quarterly report',
    is_sent: false,
    ...overrides,
  };
}

test('attachment query payload exposes only the frozen bounded contract', () => {
  assert.deepEqual(createAttachmentQueryPayload({
    accountId: ACCOUNT_ID,
    query: '  report  ',
    kind: 'document',
    direction: 'received',
    cursor: 'opaque-cursor',
    pageSize: 25,
  }), {
    account_id: ACCOUNT_ID,
    query: 'report',
    kind: 'document',
    direction: 'received',
    cursor: 'opaque-cursor',
    page_size: 25,
  });
  assert.throws(() => createAttachmentQueryPayload({ accountId: ACCOUNT_ID, kind: 'video' }), /kind/);
  assert.throws(() => createAttachmentQueryPayload({ accountId: ACCOUNT_ID, direction: 'both' }), /direction/);
  assert.throws(() => createAttachmentQueryPayload({ accountId: ACCOUNT_ID, pageSize: 51 }), /page_size/);
  assert.throws(() => createAttachmentQueryPayload({ accountId: ACCOUNT_ID, query: 'x'.repeat(257) }), /query/);
  assert.throws(() => createAttachmentQueryPayload({ accountId: ACCOUNT_ID, query: 'bad\u0000query' }), /query/);
});

test('attachment batches are exact-account, metadata-only, unique, and keyset coherent', () => {
  const normalized = normalizeAttachmentQueryResponse({
    account_id: ACCOUNT_ID,
    items: [item()],
    next_cursor: 'next-page',
    has_more: true,
  }, { accountId: ACCOUNT_ID });

  assert.deepEqual(normalized.items[0], item());
  assert.equal('body_html' in normalized.items[0], false);
  assert.equal('snippet' in normalized.items[0], false);
  assert.throws(() => normalizeAttachmentQueryResponse({
    account_id: ACCOUNT_ID,
    items: [item({ account_id: 99 })],
    next_cursor: null,
    has_more: false,
  }, { accountId: ACCOUNT_ID }), /requested account/);
  assert.throws(() => normalizeAttachmentQueryResponse({
    account_id: ACCOUNT_ID,
    items: [item({ body: 'must not cross the boundary' })],
    next_cursor: null,
    has_more: false,
  }, { accountId: ACCOUNT_ID }), /unexpected fields/);
  assert.throws(() => normalizeAttachmentQueryResponse({
    account_id: ACCOUNT_ID,
    items: [item(), item()],
    next_cursor: null,
    has_more: false,
  }, { accountId: ACCOUNT_ID }), /duplicate/);
  assert.throws(() => normalizeAttachmentQueryResponse({
    account_id: ACCOUNT_ID,
    items: [item()],
    next_cursor: null,
    has_more: true,
  }, { accountId: ACCOUNT_ID }), /pagination/);

  const nullable = normalizeAttachmentQueryResponse({
    account_id: ACCOUNT_ID,
    items: [item({
      size_bytes: null,
      message_date: null,
      sender_name: null,
      sender_address: null,
      subject: null,
    })],
    next_cursor: null,
    has_more: false,
  }, { accountId: ACCOUNT_ID });
  assert.equal(nullable.items[0].sender_address, null);
  assert.equal(nullable.items[0].size_bytes, null);
});

test('transfer adapters and parent navigation retain only exact account-owned identifiers', () => {
  assert.deepEqual(attachmentTransferItem(item(), { accountId: ACCOUNT_ID }), {
    id: 91,
    email_id: 701,
    account_id: ACCOUNT_ID,
    filename: 'quarterly-report.pdf',
    content_type: 'application/pdf',
    size_bytes: 4096,
  });
  const intent = createAttachmentParentIntent(item(), { accountId: ACCOUNT_ID });
  assert.deepEqual(intent, { account_id: ACCOUNT_ID, email_id: 701 });
  assert.equal(attachmentParentAnchorForAccount(intent, ACCOUNT_ID), 701);
  assert.throws(() => attachmentParentAnchorForAccount(intent, 99), /active account/);
});
