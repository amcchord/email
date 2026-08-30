import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.localStorage = {
  values: new Map(),
  get length() { return this.values.size; },
  getItem(key) { return this.values.get(key) ?? null; },
  key(index) { return [...this.values.keys()][index] ?? null; },
  removeItem(key) { this.values.delete(key); },
  setItem(key, value) { this.values.set(key, String(value)); },
};

const sources = [];
globalThis.EventSource = class FakeEventSource {
  constructor(url, options) {
    this.url = url;
    this.options = options;
    this.listeners = new Map();
    this.closed = false;
    sources.push(this);
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  emit(type, payload) {
    this.listeners.get(type)?.({ data: JSON.stringify(payload) });
  }

  close() {
    this.closed = true;
  }
};

const { get } = await import('svelte/store');
const { transitionAuthenticatedSession } = await import('./stores.js');
const { lastEvent, startRealtime, stopRealtime } = await import('./realtime.js');

test('realtime events and reconnects from a prior identity are ignored', () => {
  transitionAuthenticatedSession({ id: 501, username: 'generated-a' });
  startRealtime();
  assert.equal(sources.length, 1);
  assert.equal(sources[0].url, '/api/events/stream');
  assert.equal(sources[0].options.withCredentials, true);

  sources[0].emit('new_emails', { account_id: 71 });
  assert.deepEqual(get(lastEvent), { type: 'new_emails', account_id: 71 });

  transitionAuthenticatedSession({ id: 502, username: 'generated-b' });
  assert.equal(get(lastEvent), null);
  sources[0].emit('emails_updated', { account_id: 71 });
  assert.equal(get(lastEvent), null);

  // A stale connection error may close itself, but cannot schedule an
  // identity-A reconnect after the epoch has moved to B.
  sources[0].onerror();
  assert.equal(sources[0].closed, true);
  assert.equal(sources.length, 1);

  startRealtime();
  assert.equal(sources.length, 2);
  sources[1].emit('sync_complete', { account_id: 72 });
  assert.deepEqual(get(lastEvent), { type: 'sync_complete', account_id: 72 });

  transitionAuthenticatedSession(null);
  sources[1].emit('new_emails', { account_id: 72 });
  assert.equal(get(lastEvent), null);
  stopRealtime();
});
