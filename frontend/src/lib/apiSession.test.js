import assert from 'node:assert/strict';
import test from 'node:test';

import { api, setUnauthorizedHandler } from './api.js';
import { transitionAuthEpoch } from './authSession.js';

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function response(status, payload = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

test('a response from the prior identity cannot refresh or sign out the next identity', { concurrency: false }, async t => {
  const originalFetch = globalThis.fetch;
  const pending = deferred();
  const calls = [];
  let unauthorizedCalls = 0;
  transitionAuthEpoch({ id: 301 });
  setUnauthorizedHandler(() => { unauthorizedCalls += 1; });
  globalThis.fetch = async url => {
    calls.push(String(url));
    return pending.promise;
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
    setUnauthorizedHandler(null);
    transitionAuthEpoch(null);
  });

  const request = api.get('/generated-session-resource');
  transitionAuthEpoch({ id: 302 });
  pending.resolve(response(401, { detail: 'old session expired' }));

  await assert.rejects(request, error => error.code === 'auth_session_changed');
  assert.deepEqual(calls, ['/api/generated-session-resource']);
  assert.equal(unauthorizedCalls, 0);
});

test('an in-flight refresh cannot retry an old request after identity changes', { concurrency: false }, async t => {
  const originalFetch = globalThis.fetch;
  const refresh = deferred();
  const refreshStarted = deferred();
  const calls = [];
  let unauthorizedCalls = 0;
  transitionAuthEpoch({ id: 311 });
  setUnauthorizedHandler(() => { unauthorizedCalls += 1; });
  globalThis.fetch = async url => {
    calls.push(String(url));
    if (String(url) === '/api/auth/refresh') {
      refreshStarted.resolve();
      return refresh.promise;
    }
    return response(401, { detail: 'expired' });
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
    setUnauthorizedHandler(null);
    transitionAuthEpoch(null);
  });

  const request = api.get('/generated-refresh-resource');
  await refreshStarted.promise;
  transitionAuthEpoch({ id: 312 });
  refresh.resolve(response(200));

  await assert.rejects(request, error => error.code === 'auth_session_changed');
  assert.deepEqual(calls, [
    '/api/generated-refresh-resource',
    '/api/auth/refresh',
  ]);
  assert.equal(unauthorizedCalls, 0);
});

test('a current session still receives one unauthorized callback when refresh fails', { concurrency: false }, async t => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  let unauthorizedCalls = 0;
  transitionAuthEpoch({ id: 321 });
  setUnauthorizedHandler(() => { unauthorizedCalls += 1; });
  globalThis.fetch = async url => {
    calls.push(String(url));
    return response(401, { detail: 'expired' });
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
    setUnauthorizedHandler(null);
    transitionAuthEpoch(null);
  });

  await assert.rejects(api.get('/generated-current-resource'), error => error.status === 401);
  assert.deepEqual(calls, [
    '/api/generated-current-resource',
    '/api/auth/refresh',
  ]);
  assert.equal(unauthorizedCalls, 1);
});

test('a raw chat stream response cannot cross an identity boundary before handoff', { concurrency: false }, async t => {
  const originalFetch = globalThis.fetch;
  const pending = deferred();
  transitionAuthEpoch({ id: 331 });
  globalThis.fetch = async () => pending.promise;
  t.after(() => {
    globalThis.fetch = originalFetch;
    transitionAuthEpoch(null);
  });

  const stream = api.chatStream('Generated stream boundary');
  transitionAuthEpoch({ id: 332 });
  pending.resolve(response(200));

  await assert.rejects(stream, error => error.code === 'auth_session_changed');
});
