import assert from 'node:assert/strict';
import test from 'node:test';

import {
  canActOnInboxEmails,
  createLatestRequestGuard,
  inboxDatasetKey,
} from './inboxDataset.js';

test('only the newest overlapping request remains current', () => {
  const requests = createLatestRequestGuard();
  const first = requests.begin();
  const second = requests.begin();

  assert.equal(requests.isCurrent(first), false);
  assert.equal(requests.isCurrent(second), true);
});

test('invalidating a request prevents a late result from being accepted', () => {
  const requests = createLatestRequestGuard();
  const request = requests.begin();

  requests.invalidate();

  assert.equal(requests.isCurrent(request), false);
});

test('the inbox dataset key changes for every result-shaping control', () => {
  const baseline = {
    mailbox: 'INBOX',
    accountId: null,
    search: '',
    smartFilter: null,
    hideIgnored: false,
    pageSize: 50,
  };

  const variants = [
    { mailbox: 'SENT' },
    { accountId: 7 },
    { search: 'quarterly report' },
    { smartFilter: { type: 'needs_reply' } },
    { smartFilter: { type: 'ai_category', value: 'urgent' } },
    { hideIgnored: true },
    { pageSize: 100 },
  ];

  for (const variant of variants) {
    assert.notEqual(
      inboxDatasetKey({ ...baseline, ...variant }),
      inboxDatasetKey(baseline),
    );
  }
});

test('equivalent smart-filter objects produce the same dataset key', () => {
  assert.equal(
    inboxDatasetKey({ smartFilter: { type: 'ai_category', value: 'urgent' } }),
    inboxDatasetKey({ smartFilter: { type: 'ai_category', value: 'urgent' } }),
  );
});

test('actions require an authoritative dataset and a visible email', () => {
  const base = {
    authoritative: true,
    visibleEmailIds: [10, 11],
  };

  assert.equal(canActOnInboxEmails({ ...base, emailIds: [10, 11] }), true);
  assert.equal(canActOnInboxEmails({ ...base, emailIds: [12] }), false);
  assert.equal(canActOnInboxEmails({ ...base, authoritative: false, emailIds: [10] }), false);
});

test('a loaded direct-open preview is actionable without authorizing arbitrary ids', () => {
  const directOpen = {
    authoritative: true,
    visibleEmailIds: [10, 11],
    selectedEmailId: 99,
    selectedDetailId: 99,
  };

  assert.equal(canActOnInboxEmails({ ...directOpen, emailIds: [99] }), true);
  assert.equal(canActOnInboxEmails({ ...directOpen, emailIds: [98] }), false);
  assert.equal(canActOnInboxEmails({ ...directOpen, selectedDetailId: 98, emailIds: [99] }), false);
});
