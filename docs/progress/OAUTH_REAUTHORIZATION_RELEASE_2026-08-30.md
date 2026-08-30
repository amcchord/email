# Google OAuth Reauthorization Reliability Release — 2026-08-30

## Outcome

Google account and Calendar reauthorization no longer ends on a raw
`{"detail":"Internal Server Error"}` response. The production traceback was
inspected through a redacting filter and identified the exact provider error:
the token exchange was missing its PKCE code verifier. No authorization code,
token, credential, mailbox content, or private log was copied into this
workspace or document.

This release carries the verifier securely across the browser redirect, binds
reauthorization to the intended app user and Google account, validates the
actual Calendar and functional Gmail grants plus durable refresh access, and
always returns expected provider outcomes to a visible app screen with
actionable copy.

## Root Cause

`google-auth-oauthlib` 1.3 generates a PKCE verifier when it creates the Google
authorization URL. The app then constructed a separate `Flow` object in the
callback without restoring that verifier. Google correctly rejected the token
exchange with `invalid_grant`.

The same audit found related callback problems that would have remained after
the narrow verifier fix:

- account callbacks depended on a 15-minute app access cookie even though an
  OAuth round trip may outlive it;
- reauthorization state did not identify the intended account, while Google's
  `login_hint` is only advisory;
- requested scopes were stored as though granted, and Calendar health was
  cleared without verifying the actual Calendar scope;
- a missing refresh token could be presented as success when no usable stored
  refresh token existed;
- provider cancellation produced a FastAPI 422 because `code` was required;
- provider, profile, and persistence failures escaped as raw API errors;
- every callback targeted `tab=accounts`, but Settings uses `profile`, so even
  successful callbacks could land on a blank Settings body;
- reauthorization success was mislabeled as a new account connection and
  Calendar initiators were sent away from Calendar.

## Backend Changes

- Added `backend/services/google_oauth.py` as the shared PKCE flow boundary.
  Every Google authorization flow now receives an explicit RFC 7636 verifier;
  implicit process-local verifier generation is disabled.
- Account connect/reauthorize state now includes an encrypted verifier, user
  id, one-time nonce, bounded return page, and target account id for
  reauthorization. A short-lived HttpOnly, SameSite=Lax, Secure-in-production
  nonce cookie binds the callback to the browser that started the flow.
- The account callback no longer depends on the short-lived access cookie. It
  verifies signed state, expiry, and nonce first, then loads the active app
  user named by that state. The nonce cookie is deleted on every outcome.
- Reauthorization verifies that Google's returned email matches the bound
  account before changing any credentials or health state. Account connection
  also enforces the configured account allowlist.
- The callback stores Google's actual granted scopes and requires
  `calendar.readonly` plus Gmail send, modify, and labels capabilities before
  changing credentials or clearing Calendar reauthorization health. Partial
  granular-consent grants fail closed.
- Repeat consent preserves a decryptable stored refresh token when Google
  omits a replacement. New connections and existing accounts with no durable
  refresh token now fail closed.
- Cancellation, missing code, invalid/expired state, nonce mismatch, missing
  configuration, token exchange failure, profile lookup failure, absent email,
  disallowed/mismatched/taken accounts, missing Calendar or required Gmail
  scopes, missing refresh access, missing app users/accounts, and persistence
  failures all produce a sanitized local HTTP 303 redirect. Database mutation,
  flush, status creation, and commit share one rollback boundary; persistence
  logs include only app user id and exception class, never provider or SQL
  parameter detail. Provider descriptions and sensitive OAuth values are never
  reflected into the redirect.
- Google login uses the same explicit PKCE flow. Its verifier is stored in a
  separate encrypted HttpOnly cookie, restored during callback, deleted on all
  terminal outcomes, and covered by safe login error copy.
- The connect callback origin is normalized before appending its path, avoiding
  a double slash when the configured origin has a trailing slash.

No schema change, migration, mailbox operation, Google grant mutation, or AI
model/service change is part of this implementation.

## Frontend Changes

- Calendar starts reauthorization with a bounded `return_page=calendar`, so a
  successful callback returns to the workflow that initiated it. Other
  account reconnect actions retain the Settings default.
- The app shell consumes `oauth=connected|reauthorized` and sanitized
  `oauth_error` results centrally, displays an accessible success/error toast,
  removes only the consumed OAuth parameters with `replaceState`, preserves
  unrelated route parameters, and immediately refreshes account health after
  success.
- Connection and reconnection have distinct success copy.
- Every callback error code has stable, actionable user-facing text; unknown
  values fall back to a safe generic message.
- Settings normalizes the legacy `tab=accounts` value to `profile` and rejects
  unknown tab values instead of rendering a blank content body.
- Google login now explains invalid/expired state, cancellation,
  configuration, exchange, profile, email, and allowlist failures instead of
  leaving an opaque callback response.

## Regression Coverage

Fifteen generated backend cases cover:

- an explicit verifier producing an S256 challenge and being restored on the
  callback-side flow;
- encrypted state round-tripping verifier, nonce, target account, and return
  page without exposing the plaintext verifier;
- user cancellation without a code;
- token-exchange failure with no code, verifier, provider detail, or state in
  the redirect;
- nonce mismatch rejection before any database read;
- successful bound Calendar reauthorization with refresh-token preservation;
- statement-aware `(account_id, user_id)` selection that preserves a decoy
  account;
- wrong-Google-account rejection without mutation;
- missing Calendar and partial Gmail grants;
- no usable refresh token;
- profile lookup exceptions and missing-email profiles; and
- forced new-account flush failure with rollback plus redirect/log redaction.

Four frontend tests cover accurate success copy, actionable error copy,
one-time URL cleanup with unrelated query preservation, safe login fallbacks,
and the Calendar return-page API contract.

## Verification

- `make setup`: passed in the isolated worktree using Python 3.13 and the
  locked frontend dependencies; npm reported zero vulnerabilities.
- `make check`: passed.
  - Backend: 318 passed, 4 opt-in PostgreSQL tests skipped.
  - Frontend: 117 passed.
  - Production frontend: 503 modules transformed successfully.
- `node --check scripts/qa/generated_search_server.mjs`: passed.
- `git diff --check`: passed.
- Generated in-app browser QA:
  - Calendar success landed at `?page=calendar`, removed the OAuth result, and
    announced `Google account reconnected successfully`.
  - Account mismatch landed at `?page=admin&tab=profile`, visibly rendered the
    Profile & Accounts section, removed the error parameter, and announced the
    exact mismatch without exposing identity or provider detail.
  - Both exact mobile frames reported inner/client/scroll width 375 px,
    812 px height, and no horizontal overflow.
  - The generated harness recorded zero mailbox mutations and zero unknown
    routes.
- Exact 375×812 screenshot artifacts are stored in the task visualization
  directory as `oauth-success-calendar-375-toast.png` and
  `oauth-error-profile-375-toast.png`.

All test accounts and authorization values use generated `.example.test`
fixtures. No real Google callback was replayed, and no real email was opened or
changed.

## Deployment

Application release `1ded3ccba22b0d300123a080fe25adae77dcc8df` was pushed to
GitHub `main` and `codex/oauth-reauthorization`, then deployed by fast-forwarding
the clean `/opt/mail` checkout to that exact commit. The locked frontend
packages were installed with zero reported vulnerabilities, the 503-module
production frontend was rebuilt as `mailapp`, and only `mailapp` was restarted.

Post-deploy verification found exact clean Git alignment, all seven checked
services active, zero reported restarts across mailapp/workers/TUI/Caddy,
healthy public API and frontend responses, zero warning-or-higher mailapp log
entries in the deploy window, and a generated empty callback returning a
sanitized HTTP 303 to Profile & Accounts with `oauth_error=invalid_state`.
No migration, dependency lock, production data, Google grant, configuration,
mailbox, worker, Caddy, systemd, or AI file/service changed.

## User-Test Path

After deployment, start Reauthorize again from Calendar. Approve the requested
Google access. A successful flow should return to Calendar with a green
`Google account reconnected successfully` notification. The one-time code from
the failed attempt must not be reused.
