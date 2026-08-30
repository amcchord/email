# Google OAuth Callback Fail-Safe Release — 2026-08-30

## Outcome

Google account reauthorization and Google sign-in now keep users inside the
app with a sanitized, actionable result when OAuth state, provider setup,
profile lookup, database reads, persistence, token creation, or cookie
construction fails. The callback no longer has known paths that turn a
recoverable authorization problem into a raw JSON Internal Server Error page.

Application commit: `a499d9d99a2c999a714d832291742a630b291f13`.

## Reported Incident and Timeline

The reported callback carried the legacy state shape and had a ten-minute
authorization window ending at 8:40 a.m. ET. Redacted production inspection
confirmed the pre-release exception was Google's `Missing code verifier`
token-exchange rejection. The explicit-PKCE release was committed at 8:59 a.m.
ET and deployed afterward, so the supplied one-time flow began before that fix
was live.

The deployed PKCE release already gives every newly initiated flow an explicit
verifier and turns an old in-flight state into a safe `invalid_state` redirect.
This follow-up adds an exact legacy-state regression and closes the broader
exception and transaction boundaries found during independent review.

No authorization code, raw state, token, credential, mailbox content, full
production allowlist, or private log was copied into the repository or this
record.

## Backend Changes

- Signed OAuth state verification now rejects non-string tokens, non-object
  payloads, missing or non-finite expirations, and mistyped security fields.
- Account callback state requires a positive app user id, optional positive
  target account id, encrypted PKCE verifier, one-time browser nonce, and a
  bounded Calendar/Profile return target.
- Account connect/reauthorization now catches and sanitizes failures from the
  active-user lookup, credential resolution, flow construction, token
  exchange, provider profile parsing, allowlist/account reads, scope
  normalization, token encryption, status updates, flush, and commit.
- Google login has equivalent setup, provider, profile, account-read,
  persistence, token, and cookie-construction boundaries.
- Failure paths perform best-effort rollback. Logs contain only an already
  validated app user id where available and the exception class—never codes,
  state, tokens, email addresses, provider descriptions, or SQL values.
- Google login builds the complete cookie-bearing response before the sole
  database commit. A cookie failure therefore rolls back without a partial
  user/profile update; a commit failure discards the unsent response.

## Frontend Changes

- Known callback URLs from older releases (`error=invalid_state`,
  `invalid_user`, `account_taken`, and `not_allowed`) now use the same sanitized
  one-time notification path as current `oauth_error` results.
- Unknown `error` parameters remain untouched so OAuth handling cannot consume
  another feature's error state.
- Recovery copy now names a safe next step: retry, reconnect, choose the
  intended account, open Profile & Accounts, or ask an administrator.
- Google login distinguishes an app-account persistence failure from a
  provider startup failure.

## Generated Verification

- `make check` passed:
  - backend: 336 passed, 4 opt-in PostgreSQL tests skipped;
  - frontend: 135 passed;
  - production frontend: 504 modules transformed.
- The focused OAuth suite passed 26 generated cases. Coverage includes legacy
  and mistyped signed state, nonce/verifier rejection, provider setup and token
  failures, malformed profiles, allowlist/account read failures, commit and
  cookie failures, rollback, exact target-account binding, granted scopes,
  durable refresh access, and URL/log redaction.
- Three independent architecture, UX, and QA reviews found and then verified
  closure of the remaining database/setup and cookie-before-commit blockers.
- In-app browser QA at exactly 375×812 showed the legacy callback landing on
  visible Profile & Accounts with an accessible, wrapping recovery notice,
  cleaned result parameters, and no horizontal overflow.
- The generated harness recorded zero mutation attempts, zero accepted
  mutations, and zero unknown routes.

Screenshot:
`oauth-callback-followup/legacy-oauth-invalid-state-toast-375x812.png` in the
task visualization directory.

## Production Allowlist Observation

Read-only production inspection showed that the two addresses reported as
blocked match neither an exact allowlist entry nor an allowed domain. The
allowlist currently contains two entries. This is expected policy behavior,
not an OAuth exchange failure. No allowlist value was printed or changed.

The least-privilege follow-up is to add only the two exact requested addresses,
not their entire domains, after user confirmation. Each account must then start
a fresh reauthorization because Google authorization codes are one-time.

## Deployment

The release contains no schema, dependency, worker, Caddy, systemd, AI, Google
Cloud, mailbox, or mail-processing change. Deployment requires a clean
fast-forward, frontend rebuild, and restart of `mailapp` only. Production
verification will cover Git alignment, public health, service state, sanitized
generated callback behavior, and post-restart logs.
