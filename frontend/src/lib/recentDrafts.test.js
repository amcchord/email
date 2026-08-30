import assert from 'node:assert/strict';
import test from 'node:test';

import {
  mergeRecentDrafts,
  recentDraftComposeData,
  recentDraftRecipients,
  recentDraftTitle,
} from './recentDrafts.js';

test('recent drafts merge local and server truth without duplicates', () => {
  const local = [{
    client_draft_id: 'draft-a',
    revision: 4,
    synced_revision: 3,
    status: 'local-only',
    updated_at: '2026-08-30T12:02:00Z',
    snapshot: {
      account_id: 7,
      source_email_id: 91,
      to: ['local@example.test'],
      subject: 'Local subject',
      body_text: 'Local safe recovery',
      attachments: [],
    },
  }, {
    client_draft_id: 'draft-local',
    revision: 1,
    status: 'offline',
    updated_at: '2026-08-30T12:03:00Z',
    snapshot: { account_id: 8, to: [], subject: '', body_text: '' },
  }];
  const server = [{
    client_draft_id: 'draft-a',
    revision: 3,
    synced_revision: 3,
    state: 'synced',
    updated_at: '2026-08-30T12:01:00Z',
    account_id: 7,
    to: ['server@example.test'],
    subject: 'Server subject',
  }, {
    client_draft_id: 'draft-server',
    revision: 2,
    state: 'synced',
    updated_at: '2026-08-30T12:04:00Z',
    account_id: 7,
    to: ['remote@example.test'],
    subject: 'Remote subject',
  }];
  const rows = mergeRecentDrafts(local, server, [{ id: 7, email: 'sender@example.test' }]);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map(row => row.client_draft_id), ['draft-server', 'draft-local', 'draft-a']);
  const merged = rows.find(row => row.client_draft_id === 'draft-a');
  assert.equal(merged.subject, 'Local subject');
  assert.equal(merged.local, true);
  assert.equal(merged.server, true);
  assert.equal(merged.conflict, false);
  assert.equal(merged.account.email, 'sender@example.test');
});

test('newer server revision is surfaced as changed elsewhere and sorted first', () => {
  const rows = mergeRecentDrafts([{
    client_draft_id: 'draft-conflict',
    revision: 2,
    status: 'synced',
    updated_at: '2026-08-30T12:00:00Z',
    snapshot: { account_id: 7, subject: 'Local', to: [] },
  }], [{
    client_draft_id: 'draft-conflict',
    revision: 10,
    state: 'synced',
    updated_at: '2026-08-30T12:01:00Z',
    account_id: 7,
    subject: 'Server',
    to: ['remote@example.test'],
  }, {
    client_draft_id: 'draft-newer-time',
    revision: 1,
    state: 'synced',
    updated_at: '2026-08-30T12:10:00Z',
    account_id: 7,
  }]);
  assert.equal(rows[0].client_draft_id, 'draft-conflict');
  assert.equal(rows[0].changed_elsewhere, true);
  assert.equal(rows[0].subject, 'Server');
  assert.deepEqual(recentDraftComposeData(rows[0]), {
    client_draft_id: 'draft-conflict',
    draft_key: 'client:draft-conflict',
    intent_key: 'route:draft-conflict',
    known_server_revision: 10,
  });
});

test('reply draft routing preserves stable source identity across Compose and offline reopen', () => {
  assert.deepEqual(recentDraftComposeData({
    client_draft_id: 'draft-reply',
    account_id: 7,
    source_email_id: 91,
    server_revision: 10,
  }), {
    client_draft_id: 'draft-reply',
    draft_key: 'client:draft-reply',
    intent_key: 'reply:7:91',
    known_server_revision: 10,
  });
});

test('discarded rows are excluded and fallback labels stay useful', () => {
  const rows = mergeRecentDrafts([], [{
    client_draft_id: 'discarded',
    state: 'discarded',
  }, {
    client_draft_id: 'reply',
    source_email_id: 9,
    state: 'synced',
    updated_at: '2026-08-30T12:00:00Z',
  }]);
  assert.equal(rows.length, 1);
  assert.equal(recentDraftTitle(rows[0]), 'Reply draft');
  assert.equal(recentDraftRecipients(rows[0]), 'No recipients');
});
