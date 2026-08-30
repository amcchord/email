const ACCOUNT_OAUTH_MESSAGES = Object.freeze({
  invalid_state: 'Your Google reconnection session expired. Please try again.',
  configuration_error: 'Google authorization is not configured. Ask an administrator to check Settings.',
  session_expired: 'This app account is no longer available. Ask an administrator for help, then try again.',
  access_denied: 'Google access was not granted. Nothing was changed.',
  authorization_failed: 'Google could not start authorization. Please try again.',
  token_exchange_failed: 'Google could not complete authorization. Please reconnect and try again.',
  profile_lookup_failed: 'Google authorized access, but the account profile could not be verified. Reconnect and try again.',
  no_email: 'Google did not provide an email address for this account. Choose a different Google account and try again.',
  not_allowed: 'That Google account is not on the allowed list. Choose an authorized account or ask an administrator for help.',
  calendar_scope_missing: 'Calendar access was not granted. Reconnect and allow Calendar access.',
  required_scopes_missing: 'Required Gmail access was not granted. Reconnect and approve all requested Gmail access.',
  account_not_found: 'The account being reconnected is no longer available. Connect it again from Profile & Accounts.',
  account_mismatch: 'The selected Google account does not match the account being reconnected. Reconnect and select the account shown in Profile & Accounts.',
  account_taken: 'That Google account is already connected to another user. Choose a different account or ask an administrator for help.',
  refresh_token_missing: 'Google did not provide durable access. Reconnect and approve access again.',
  account_update_failed: 'Authorization succeeded, but the account could not be updated. Please try again.',
});

// Callback URLs from releases before the sanitized `oauth_error` contract used
// a generic `error` parameter. Consume only values that those releases emitted;
// other features may legitimately own an unrelated `error` query parameter.
const LEGACY_ACCOUNT_OAUTH_ERRORS = Object.freeze({
  invalid_state: 'invalid_state',
  invalid_user: 'session_expired',
  account_taken: 'account_taken',
  not_allowed: 'not_allowed',
});

const LOGIN_OAUTH_MESSAGES = Object.freeze({
  invalid_state: 'Your Google sign-in session expired. Please try again.',
  configuration_error: 'Google sign-in is not configured. Ask an administrator for help.',
  access_denied: 'Google sign-in was cancelled.',
  authorization_failed: 'Google could not start sign-in. Please try again.',
  token_exchange_failed: 'Google could not complete sign-in. Please try again.',
  profile_lookup_failed: 'Google signed you in, but your profile could not be verified.',
  no_email: 'Google did not provide an email address. Please try again.',
  not_allowed: 'Your Google account is not authorized to access this system.',
  account_update_failed: 'Google sign-in succeeded, but your app account could not be updated. Please try again.',
});

export function accountOAuthOutcome(urlValue) {
  const url = new URL(urlValue, 'https://mail.example.test');
  const result = url.searchParams.get('oauth');
  const oauthError = url.searchParams.get('oauth_error');
  const legacyErrorValue = url.searchParams.get('error');
  const legacyError = Object.hasOwn(LEGACY_ACCOUNT_OAUTH_ERRORS, legacyErrorValue)
    ? LEGACY_ACCOUNT_OAUTH_ERRORS[legacyErrorValue]
    : null;
  const error = oauthError || legacyError;
  const legacyConnected = url.searchParams.get('connected') === 'true';
  if (!result && !error && !legacyConnected) return null;

  let message;
  let type;
  if (error) {
    message = ACCOUNT_OAUTH_MESSAGES[error] || 'Google authorization could not be completed. Please try again.';
    type = 'error';
  } else {
    message = result === 'reauthorized'
      ? 'Google account reconnected successfully'
      : 'Google account connected successfully';
    type = 'success';
  }

  for (const key of ['oauth', 'oauth_error', 'connected']) url.searchParams.delete(key);
  if (legacyError) url.searchParams.delete('error');
  return {
    message,
    type,
    location: `${url.pathname}${url.search}${url.hash}`,
  };
}

export function googleLoginErrorMessage(code) {
  if (!code) return '';
  return LOGIN_OAUTH_MESSAGES[code] || 'Google sign-in could not be completed. Please try again.';
}
