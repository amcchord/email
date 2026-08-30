import assert from 'node:assert/strict';
import test from 'node:test';

import { createLazyEditorCache } from './lazyEditor.js';

test('editor cache deduplicates a pending import and keeps the component warm', async () => {
  let importCount = 0;
  let resolveImport;
  const component = { name: 'GeneratedRichEditor' };
  const cache = createLazyEditorCache(() => {
    importCount += 1;
    return new Promise(resolve => { resolveImport = resolve; });
  });

  const first = cache.load();
  const second = cache.load();
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(importCount, 1);

  resolveImport({ default: component });
  assert.equal(await first, component);
  assert.equal(await cache.load(), component);
  assert.equal(cache.peek(), component);
  assert.equal(importCount, 1);
});

test('editor cache evicts a rejected import so a later request can recover', async () => {
  let importCount = 0;
  const component = { name: 'GeneratedRecoveredEditor' };
  const cache = createLazyEditorCache(async () => {
    importCount += 1;
    if (importCount === 1) throw new Error('generated editor failure');
    return { default: component };
  });

  await assert.rejects(cache.load(), /generated editor failure/);
  assert.equal(cache.peek(), null);
  assert.equal(await cache.load(), component);
  assert.equal(importCount, 2);
});

test('an older editor request cannot replace a successful explicit retry', async () => {
  const resolvers = [];
  const cache = createLazyEditorCache(
    () => new Promise(resolve => resolvers.push(resolve)),
  );

  const older = cache.load();
  await Promise.resolve();
  const retry = cache.load({ retry: true });
  await Promise.resolve();

  const newerComponent = { name: 'GeneratedNewerEditor' };
  const olderComponent = { name: 'GeneratedOlderEditor' };
  resolvers[1]({ default: newerComponent });
  assert.equal(await retry, newerComponent);
  assert.equal(cache.peek(), newerComponent);

  resolvers[0]({ default: olderComponent });
  assert.equal(await older, olderComponent);
  assert.equal(cache.peek(), newerComponent);
});

test('editor cache rejects a module without a default component', async () => {
  const cache = createLazyEditorCache(async () => ({}));
  await assert.rejects(cache.load(), /default component export/);
  assert.equal(cache.peek(), null);
});
