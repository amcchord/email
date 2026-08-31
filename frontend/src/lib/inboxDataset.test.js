import assert from 'node:assert/strict';
import test from 'node:test';

import {
  canActOnInboxEmails,
  createDatasetActionReconciler,
  createInitialDirectOpenGuard,
  createLatestRequestGuard,
  inboxDatasetKey,
  normalizeInboxDatasetSnapshot,
  selectedBooleanState,
} from './inboxDataset.js';

test('a direct-open intent survives selection invalidation until the first authoritative dataset', () => {
  const intent = createInitialDirectOpenGuard();

  assert.equal(intent.capture(313), 313);
  assert.equal(intent.capture(null), 313, 'an overlapping refresh cannot erase the pending intent');
  assert.equal(intent.commit(false), null, 'a non-authoritative result keeps the intent pending');
  assert.equal(intent.commit(true), 313);
  assert.equal(intent.capture(314), null, 'later dataset refreshes do not revive initial-navigation state');
  assert.equal(intent.commit(true), null);
});

test('a direct-open intent rejects invalid message ids', () => {
  const intent = createInitialDirectOpenGuard();

  assert.equal(intent.capture(0), null);
  assert.equal(intent.capture(-1), null);
  assert.equal(intent.capture('not-an-id'), null);
  assert.equal(intent.capture(Number.MAX_SAFE_INTEGER + 1), null);
});

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

test('active search broadens to regular mail while preserving account scope', () => {
  const snapshot = normalizeInboxDatasetSnapshot({
    mailbox: 'INBOX',
    accountId: 7,
    search: '  subject:"Quarterly & Planning"  ',
    smartFilter: { type: 'ai_category', value: 'urgent' },
    hideIgnored: true,
    pageSize: 50,
  });

  assert.equal(snapshot.mailbox, 'ALL');
  assert.equal(snapshot.accountId, 7);
  assert.equal(snapshot.search, 'subject:"Quarterly & Planning"');
  assert.equal(snapshot.smartFilter, null);
  assert.equal(snapshot.hideIgnored, false);
});

test('Split Inbox is inactive outside the literal unfiltered Inbox', () => {
  const smartFilter = { type: 'needs_reply' };
  const snapshot = normalizeInboxDatasetSnapshot({
    mailbox: 'SENT',
    search: '',
    smartFilter,
    hideIgnored: true,
  });

  assert.equal(snapshot.mailbox, 'SENT');
  assert.equal(snapshot.smartFilter, smartFilter);
  assert.equal(snapshot.hideIgnored, false);
});

test('Split Inbox stays active for the literal unfiltered Inbox', () => {
  const snapshot = normalizeInboxDatasetSnapshot({
    mailbox: 'INBOX',
    hideIgnored: true,
  });

  assert.equal(snapshot.mailbox, 'INBOX');
  assert.equal(snapshot.smartFilter, null);
  assert.equal(snapshot.hideIgnored, true);
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

test('accepted actions coalesce while preserving a trailing authoritative refresh', async () => {
  let currentKey = 'search-a';
  let releaseFirst;
  const firstRefresh = new Promise(resolve => { releaseFirst = resolve; });
  const calls = [];
  const reconciler = createDatasetActionReconciler({
    isCurrent: key => key === currentKey,
    refresh: async key => {
      calls.push(key);
      if (calls.length === 1) await firstRefresh;
    },
  });

  const running = reconciler.request('search-a');
  await Promise.resolve();
  await Promise.resolve();
  reconciler.request('search-a');
  releaseFirst();
  await running;

  assert.deepEqual(calls, ['search-a', 'search-a']);

  currentKey = 'search-b';
  await reconciler.request('search-a');
  assert.deepEqual(calls, ['search-a', 'search-a']);
});

test('selected boolean state distinguishes uniform and mixed search results', () => {
  const rows = [
    { id: 1, is_trash: true },
    { id: 2, is_trash: false },
    { id: 3, is_trash: true },
  ];

  assert.equal(selectedBooleanState(rows, new Set([1, 3]), 'is_trash'), true);
  assert.equal(selectedBooleanState(rows, new Set([2]), 'is_trash'), false);
  assert.equal(selectedBooleanState(rows, new Set([1, 2]), 'is_trash'), null);
});
