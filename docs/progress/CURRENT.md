# Current Status

Last updated: 2026-08-30

## Active Objective

Eliminate wrong-sender and recipient-envelope ambiguity across Inbox and Flow
reply workflows. Resolve the exact active source account without first-account
fallback, derive Reply/Reply All recipients once, and make the visible
From/To/Cc envelope identical to the send payload. Use generated two-account
fixtures only and preserve the separately owned AI-provider worktree.

## Baseline

- Production and GitHub `main` include OAuth application release
  `1ded3ccba22b0d300123a080fe25adae77dcc8df`. The production frontend was built
  from that release. Public health is `ok`, all seven checked services are
  active, the five application-edge services report zero restarts, and the
  post-deploy mailapp warning-or-higher count is zero. Alembic remains at
  `z7a8b9c0d1e2 (head)`; this release contains no schema change.
- The original AI worktree remains clean at `41d2898` on
  `codex/openai-anthropic-model-support` and has not been edited by this work.
- The reply-envelope slice is isolated in
  `/Users/austinmcchord/Development/Email-reply-envelope-integrity` on
  `codex/reply-envelope-integrity`, based on GitHub `main` at `2b534f3`.
- The deployed remote-content release was developed in the isolated worktree
  `/Users/austinmcchord/Development/Email-remote-content-controls` on
  `codex/remote-content-controls`.
- A validated 1.38 GB custom-format backup remains protected at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`, mode
  `0600`, owned by `postgres`. This OAuth candidate has no schema work.

This is a point-in-time snapshot. Run `make remote-status` before relying on
live state.

## Deployed Remote-Content Scope

- Sender-controlled images, media, stylesheet links, remote CSS, legacy
  backgrounds, SVG resource references, tracking pings, and similar resources
  are blocked by default in Inbox, standalone/subscription reading, and Flow.
- A shared `EmailHtmlFrame` keeps all reading surfaces on one sanitizer, CSP,
  no-referrer, theme, resize, and link-opening contract.
- Sender markup is parsed in a detached template owned by a CSP-locked hidden
  frame before DOMPurify touches it, closing the pre-sanitization preload gap.
- A visible in-flow privacy notice explains the risk and provides a
  message-scoped `Load directly once` action. The display can be hidden again,
  but network requests already made cannot be undone. Direct loading is not
  presented as private or proxy-protected.
- External styles, fonts, pings, SVG references, scripts, frames, forms,
  relative/same-host resources, and active content remain blocked even after
  the direct one-message opt-in.
- Missing remote and unresolved CID images use deliberate accessible
  placeholders instead of browser broken-image chrome.
- Forwarded and restored compose HTML drops sender styles and every
  auto-loading remote resource before entering either the basic or rich editor.
- A generated localhost matrix and request beacon cover Inbox, standalone,
  Flow, Compose/Forward, embedded raster data, desktop, dark mode, and exact
  375 px layouts without accessing real mail.

## Verification State

- The reply-envelope candidate passes `make check`: 325 backend tests passed,
  4 opt-in PostgreSQL tests skipped, 132 frontend tests passed, and the
  504-module production frontend built.
- Generated two-account browser QA verifies distinct Reply/Reply All, exact
  second-account From identity behind a first-account decoy, deduplicated
  external To/Cc recipients, Active Thread provenance, actionable unknown-
  source failure, stable draft identity, and a fully visible exact-375 action
  layout.
- The final browser-readable audit contains only exact account-scoped GETs,
  zero mutation attempts, zero accepted mutations, and zero unknown routes.
- Independent architecture, competitive UX, and QA rereviews report no
  remaining release blockers.

- The OAuth release candidate passes `make check`: 318 backend tests, 4 opt-in
  PostgreSQL skips, 117 frontend tests, and a successful 503-module production
  build.
- Generated OAuth QA verifies success and account-mismatch callbacks on
  desktop and exact 375×812 mobile layouts, with sanitized one-time results,
  visible Calendar/Profile landings, no overflow, zero mailbox mutations, and
  zero unknown routes.
- Production `/api/health` and `/` return HTTP 200, while a generated empty
  callback returns a sanitized HTTP 303 to Profile & Accounts with
  `oauth_error=invalid_state` instead of a raw API response.
- The prior remote-content release remains covered by its existing generated
  browser matrix and request audit.
- Generated browser QA records zero remote resource requests before permission,
  zero resource requests for safe embedded raster content, and only expected
  no-referrer image/media requests after the explicit local-fixture opt-in.
- Generated mailbox mutation and unknown-route audits are empty. Forwarded
  content retains readable text but contains no sender URL, image, media,
  stylesheet, style block, or SVG resource.
- Desktop 1440×900, exact mobile 375×812, and dark Flow screenshots are saved
  beside the release record. Mobile controls are 44 px and the document has no
  horizontal overflow.
- Permission clears across generated A → B → A navigation. Live theme changes
  update CSS variables without repeating the seven approved no-referrer
  requests. The captured audit is `REMOTE_CONTENT_QA_AUDIT_2026-08-30.json`.

## Known Constraints and Follow-ups

- `Load directly once` permits direct requests. It can disclose IP address,
  device details, and approximate view time; the UI says so. Hiding the content
  later cannot undo those requests. A hardened owned proxy/resource
  manifest is required before adding private-loading claims, persistent sender
  exceptions, or automatic image display.
- CID attachment metadata is parsed but not exposed/re-written into owned
  inline-resource URLs, so those images currently use an intentional
  `Inline image unavailable` placeholder. Add an owned CID manifest/endpoint
  before changing the default policy.
- Spam does not yet have a separate policy flag because the current global
  behavior already blocks remote content everywhere. Any future trust/global
  preference must keep Spam fail-closed.
- The audit found an existing blind-SSRF path in AI Markdown image validation
  (`backend/services/chat.py`). That file belongs to the concurrent AI effort
  and was deliberately not changed here. Coordinate that P0 fix with the AI
  owner before expanding AI image behavior.
- Subscription sender favicons still use a third-party Google favicon request;
  that separate non-message network path should be removed or proxied.
- Compose/send still lacks a durable client-keyed lost-response contract, so
  irreversible Send remains outside the command palette.

## Next Safe Action

Commit and push the validated reply-envelope release, deploy the exact commit
with a frontend rebuild and only the required `mailapp` restart, then verify
health, service state, logs, and the public UI. The prior OAuth release still
awaits a fresh user reauthorization; its failed one-time authorization code
must not be reused.
