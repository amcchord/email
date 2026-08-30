const ACCOUNT_OAUTH_MESSAGES = Object.freeze({
  invalid_state: 'Your Google reconnection session expired. Please try again.',
  configuration_error: 'Google authorization is not configured. Ask an administrator to check Settings.',
  session_expired: 'This app account is no longer available. Sign in and try again.',
  access_denied: 'Google access was not granted. Nothing was changed.',
  authorization_failed: 'Google could not start authorization. Please try again.',
  token_exchange_failed: 'Google could not complete authorization. Please reconnect and try again.',
  profile_lookup_failed: 'Google authorized access, but the account profile could not be verified.',
  no_email: 'Google did not provide an email address for this account.',
  not_allowed: 'That Google account is not on the allowed list.',
  calendar_scope_missing: 'Calendar access was not granted. Reconnect and allow Calendar access.',
  required_scopes_missing: 'Required Gmail access was not granted. Reconnect and approve all requested Gmail access.',
  account_not_found: 'The account being reconnected is no longer available.',
  account_mismatch: 'The selected Google account does not match the account being reconnected.',
  account_taken: 'That Google account is already connected to another user.',
  refresh_token_missing: 'Google did not provide durable access. Reconnect and approve access again.',
  account_update_failed: 'Authorization succeeded, but the account could not be updated. Please try again.',
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
});

export function accountOAuthOutcome(urlValue) {
  const url = new URL(urlValue, 'https://mail.example.test');
  const result = url.searchParams.get('oauth');
  const error = url.searchParams.get('oauth_error');
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
