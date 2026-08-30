import test from 'node:test';
import assert from 'node:assert/strict';

import { api } from './api.js';
import { accountOAuthOutcome, googleLoginErrorMessage } from './oauthResult.js';

test('account OAuth success is accurate and preserves the landing route', () => {
  assert.deepEqual(
    accountOAuthOutcome('https://mail.example.test/?page=calendar&oauth=reauthorized&view=week'),
    {
      message: 'Google account reconnected successfully',
      type: 'success',
      location: '/?page=calendar&view=week',
    },
  );
});

test('account OAuth errors are actionable and consumed exactly once', () => {
  assert.deepEqual(
    accountOAuthOutcome('https://mail.example.test/?page=admin&tab=profile&oauth_error=account_mismatch&keep=1'),
    {
      message: 'The selected Google account does not match the account being reconnected.',
      type: 'error',
      location: '/?page=admin&tab=profile&keep=1',
    },
  );
  assert.equal(accountOAuthOutcome('https://mail.example.test/?page=admin&tab=profile'), null);
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?oauth_error=required_scopes_missing').message,
    'Required Gmail access was not granted. Reconnect and approve all requested Gmail access.',
  );
});

test('login OAuth failures have safe fallback copy', () => {
  assert.equal(googleLoginErrorMessage('access_denied'), 'Google sign-in was cancelled.');
  assert.equal(
    googleLoginErrorMessage('generated-unknown-provider-value'),
    'Google sign-in could not be completed. Please try again.',
  );
});

test('calendar reauthorization API sends a bounded return page', async t => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  globalThis.fetch = async url => {
    requestedUrl = String(url);
    return new Response(JSON.stringify({ auth_url: 'https://accounts.example.test/generated' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  await api.reauthorizeAccount(41, { returnPage: 'calendar' });

  assert.equal(requestedUrl, '/api/accounts/41/reauthorize?return_page=calendar');
});
