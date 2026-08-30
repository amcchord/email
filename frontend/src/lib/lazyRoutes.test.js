import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AUTHENTICATED_PAGES,
  createLazyRouteCache,
  createLazyRouteCoordinator,
  normalizeAuthenticatedPage,
} from './lazyRoutes.js';

test('authenticated page normalization accepts known pages and safely falls back to Flow', () => {
  assert.ok(AUTHENTICATED_PAGES.includes('flow'));
  assert.ok(AUTHENTICATED_PAGES.includes('inbox'));
  assert.ok(AUTHENTICATED_PAGES.includes('at-a-glance'));
  assert.equal(normalizeAuthenticatedPage('calendar'), 'calendar');
  assert.equal(normalizeAuthenticatedPage('at-a-glance'), 'at-a-glance');
  assert.equal(normalizeAuthenticatedPage('standalone-email'), 'flow');
  assert.equal(normalizeAuthenticatedPage('unknown'), 'flow');
  assert.equal(normalizeAuthenticatedPage(null), 'flow');
});

test('lazy route cache deduplicates pending imports and keeps successful components warm', async () => {
  let resolveImport;
  let importCount = 0;
  const component = { name: 'GeneratedFlowComponent' };
  const cache = createLazyRouteCache({
    flow: {
      load: () => {
        importCount += 1;
        return new Promise(resolve => { resolveImport = resolve; });
      },
    },
  });

  const first = cache.load('flow');
  const second = cache.load('flow');
  assert.equal(first, second);
  assert.equal(importCount, 0, 'the import begins in a microtask');
  await Promise.resolve();
  assert.equal(importCount, 1);

  resolveImport({ default: component });
  assert.equal(await first, component);
  assert.equal(await cache.load('flow'), component);
  assert.equal(cache.peek('flow'), component);
  assert.equal(importCount, 1);
});

test('lazy route cache evicts a rejected import so retry can recover', async () => {
  let importCount = 0;
  const component = { name: 'GeneratedCalendarComponent' };
  const cache = createLazyRouteCache({
    calendar: {
      load: async () => {
        importCount += 1;
        if (importCount === 1) throw new Error('generated transient chunk failure');
        return { default: component };
      },
    },
  });

  await assert.rejects(cache.load('calendar'), /generated transient chunk failure/);
  assert.equal(cache.peek('calendar'), null);
  assert.equal(await cache.load('calendar'), component);
  assert.equal(importCount, 2);
});

test('a superseded pending import cannot overwrite the newer retry result', async () => {
  const resolvers = [];
  const cache = createLazyRouteCache({
    todos: {
      load: () => new Promise(resolve => resolvers.push(resolve)),
    },
  });

  const olderRequest = cache.load('todos');
  await Promise.resolve();
  const retryRequest = cache.load('todos', { retry: true });
  await Promise.resolve();

  const newerComponent = { name: 'GeneratedNewerTodosComponent' };
  const olderComponent = { name: 'GeneratedOlderTodosComponent' };
  resolvers[1]({ default: newerComponent });
  assert.equal(await retryRequest, newerComponent);
  assert.equal(cache.peek('todos'), newerComponent);

  resolvers[0]({ default: olderComponent });
  assert.equal(await olderRequest, olderComponent);
  assert.equal(cache.peek('todos'), newerComponent);
});

test('route coordinator ignores a stale import that resolves after newer navigation', async () => {
  const resolvers = new Map();
  const states = [];
  const coordinator = createLazyRouteCoordinator({
    peek: () => null,
    load: key => new Promise(resolve => resolvers.set(key, resolve)),
    onState: state => states.push(state),
  });

  const flowRequest = coordinator.open('flow');
  const inboxRequest = coordinator.open('inbox');
  resolvers.get('inbox')({ name: 'GeneratedInboxComponent' });
  assert.equal(await inboxRequest, 'ready');
  resolvers.get('flow')({ name: 'GeneratedFlowComponent' });
  assert.equal(await flowRequest, 'stale');

  assert.deepEqual(states.map(state => `${state.key}:${state.status}`), [
    'flow:loading',
    'inbox:loading',
    'inbox:ready',
  ]);
});

test('route coordinator exposes an error and then a ready state on retry', async () => {
  let attempt = 0;
  const states = [];
  const coordinator = createLazyRouteCoordinator({
    peek: () => null,
    load: async (_key, options) => {
      attempt += 1;
      assert.equal(options.retry, attempt === 2);
      if (attempt === 1) throw new Error('generated route failure');
      return { name: 'GeneratedRecoveredComponent' };
    },
    onState: state => states.push(state),
  });

  assert.equal(await coordinator.open('calendar'), 'error');
  assert.match(states.at(-1).error.message, /generated route failure/);
  assert.equal(await coordinator.open('calendar', { retry: true }), 'ready');
  assert.equal(states.at(-1).status, 'ready');
  assert.equal(states.at(-1).component.name, 'GeneratedRecoveredComponent');
});
