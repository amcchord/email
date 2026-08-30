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
      message: 'The selected Google account does not match the account being reconnected. Reconnect and select the account shown in Profile & Accounts.',
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

test('known legacy account OAuth errors use sanitized copy and preserve routing state', () => {
  assert.deepEqual(
    accountOAuthOutcome('https://mail.example.test/?page=admin&tab=accounts&error=invalid_state&keep=1#accounts'),
    {
      message: 'Your Google reconnection session expired. Please try again.',
      type: 'error',
      location: '/?page=admin&tab=accounts&keep=1#accounts',
    },
  );
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?page=admin&error=invalid_user').message,
    'This app account is no longer available. Ask an administrator for help, then try again.',
  );
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?page=admin&error=account_taken').message,
    'That Google account is already connected to another user. Choose a different account or ask an administrator for help.',
  );
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?page=admin&error=not_allowed').message,
    'That Google account is not on the allowed list. Choose an authorized account or ask an administrator for help.',
  );
});

test('unrelated error parameters are not consumed as OAuth callback results', () => {
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?page=calendar&error=calendar_filter_invalid'),
    null,
  );
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?page=calendar&error=toString'),
    null,
  );
  assert.deepEqual(
    accountOAuthOutcome('https://mail.example.test/?page=calendar&oauth=reauthorized&error=calendar_filter_invalid&view=week'),
    {
      message: 'Google account reconnected successfully',
      type: 'success',
      location: '/?page=calendar&error=calendar_filter_invalid&view=week',
    },
  );
});

test('account OAuth error messages provide a recovery step without provider detail', () => {
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?oauth_error=profile_lookup_failed').message,
    'Google authorized access, but the account profile could not be verified. Reconnect and try again.',
  );
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?oauth_error=no_email').message,
    'Google did not provide an email address for this account. Choose a different Google account and try again.',
  );
  assert.equal(
    accountOAuthOutcome('https://mail.example.test/?oauth_error=account_not_found').message,
    'The account being reconnected is no longer available. Connect it again from Profile & Accounts.',
  );
});

test('login OAuth failures have safe fallback copy', () => {
  assert.equal(googleLoginErrorMessage('access_denied'), 'Google sign-in was cancelled.');
  assert.equal(
    googleLoginErrorMessage('account_update_failed'),
    'Google sign-in succeeded, but your app account could not be updated. Please try again.',
  );
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
