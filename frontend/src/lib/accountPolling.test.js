import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.localStorage = {
  values: new Map(),
  getItem(key) { return this.values.get(key) ?? null; },
  setItem(key, value) { this.values.set(key, String(value)); },
};

const { get } = await import('svelte/store');
const {
  accounts,
  accountsLoadError,
  accountsLoaded,
  forceSyncPoll,
  startSyncPolling,
  stopSyncPolling,
} = await import('./stores.js');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('stopping account polling invalidates a late identity response', async () => {
  const pending = deferred();
  startSyncPolling(() => pending.promise);
  stopSyncPolling();
  pending.resolve([{ id: 1, email: 'old-session@example.test' }]);
  await pending.promise;
  await Promise.resolve();

  assert.deepEqual(get(accounts), []);
  assert.equal(get(accountsLoaded), false);
});

test('a new polling generation cannot be overwritten by the old session', async () => {
  const oldPending = deferred();
  const newPending = deferred();
  startSyncPolling(() => oldPending.promise);
  startSyncPolling(() => newPending.promise);
  newPending.resolve([{ id: 2, email: 'new-session@example.test' }]);
  await newPending.promise;
  await Promise.resolve();
  oldPending.resolve([{ id: 1, email: 'old-session@example.test' }]);
  await oldPending.promise;
  await Promise.resolve();

  assert.deepEqual(get(accounts).map(account => account.id), [2]);
  stopSyncPolling();
});

test('forced refresh coalesces with an in-flight account read', async () => {
  const pending = deferred();
  let calls = 0;
  startSyncPolling(() => {
    calls += 1;
    return pending.promise;
  });
  const forced = forceSyncPoll();
  assert.equal(calls, 1);
  pending.resolve([]);
  await forced;
  stopSyncPolling();
});

test('account load failure is retryable and clears only after authoritative success', async () => {
  let calls = 0;
  startSyncPolling(async () => {
    calls += 1;
    if (calls === 1) throw new Error('temporary account read failure');
    return [{ id: 3, email: 'recovered@example.test' }];
  });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(get(accountsLoaded), false);
  assert.match(get(accountsLoadError), /temporary/);

  await forceSyncPoll();
  assert.equal(get(accountsLoaded), true);
  assert.equal(get(accountsLoadError), '');
  assert.deepEqual(get(accounts).map(account => account.id), [3]);
  stopSyncPolling();
});

test('logout then same-document login starts a clean account authority generation', async () => {
  const oldPending = deferred();
  startSyncPolling(() => oldPending.promise);
  stopSyncPolling();
  startSyncPolling(async () => [{ id: 4, email: 'new-login@example.test' }]);
  await Promise.resolve();
  await Promise.resolve();
  oldPending.resolve([{ id: 1, email: 'old-login@example.test' }]);
  await oldPending.promise;
  await Promise.resolve();
  assert.deepEqual(get(accounts).map(account => account.id), [4]);
  stopSyncPolling();
});
