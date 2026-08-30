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

async function waitForCall(calls, url) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (calls.includes(url)) return;
    await Promise.resolve();
  }
  assert.fail(`Timed out waiting for ${url}`);
}

test('deferred refresh is drained before logout and the next login', { concurrency: false }, async t => {
  const originalFetch = globalThis.fetch;
  const refresh = deferred();
  const logoutResponse = deferred();
  const calls = [];
  let unauthorizedCalls = 0;
  transitionAuthEpoch({ id: 701 });
  setUnauthorizedHandler(() => { unauthorizedCalls += 1; });

  globalThis.fetch = async url => {
    const path = String(url);
    calls.push(path);
    if (path === '/api/generated-cookie-race' || path === '/api/generated-during-logout') {
      return response(401, { detail: 'expired' });
    }
    if (path === '/api/auth/refresh') return refresh.promise;
    if (path === '/api/auth/logout') return logoutResponse.promise;
    if (path === '/api/auth/login') {
      return response(200, { user: { id: 702, username: 'generated-b' } });
    }
    throw new Error(`Unexpected request: ${path}`);
  };

  t.after(async () => {
    refresh.resolve(response(401, { detail: 'cleanup' }));
    logoutResponse.resolve(response(200, { message: 'cleanup' }));
    await api.logout().catch(() => {});
    globalThis.fetch = originalFetch;
    setUnauthorizedHandler(null);
    transitionAuthEpoch(null);
  });

  const staleRequest = api.get('/generated-cookie-race');
  await waitForCall(calls, '/api/auth/refresh');

  const logout = api.logout();
  assert.equal(api.logout(), logout);
  const login = api.login('generated-b', 'generated-password');
  await assert.rejects(
    api.get('/generated-during-logout'),
    error => error.code === 'auth_logout_in_progress' && error.name === 'AbortError',
  );
  assert.equal(unauthorizedCalls, 0);
  await Promise.resolve();
  assert.deepEqual(calls, [
    '/api/generated-cookie-race',
    '/api/auth/refresh',
    '/api/generated-during-logout',
  ]);

  refresh.resolve(response(200, { user: { id: 701 } }));
  await waitForCall(calls, '/api/auth/logout');
  assert.equal(calls.includes('/api/auth/login'), false);

  logoutResponse.resolve(response(200, { message: 'logged out' }));
  await logout;
  const loginResult = await login;

  assert.equal(loginResult.user.id, 702);
  assert.deepEqual(calls, [
    '/api/generated-cookie-race',
    '/api/auth/refresh',
    '/api/generated-during-logout',
    '/api/generated-cookie-race',
    '/api/auth/logout',
    '/api/auth/login',
  ]);
  await assert.rejects(
    staleRequest,
    error => error.code === 'auth_logout_in_progress' && error.name === 'AbortError',
  );
  assert.equal(unauthorizedCalls, 0);
});
