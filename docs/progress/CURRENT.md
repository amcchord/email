# Current Status

Last updated: 2026-08-30

## Active Objective

Pause for production user testing of the deployed remote-content privacy
controls. Preserve the clean, separately owned AI-provider worktree, keep all
mail rendering and mutation QA on generated messages, and do not open or
change real production mail.

## Baseline

- Production and GitHub `main` include remote-content application release
  `9b9730a68c65de2b7ee9910c0d2c3bd70939e273` and its documentation closeout.
  The running frontend assets were built from that application release. Public
  health is `ok`, all seven checked services are active with zero restarts, and
  Alembic remains at `z7a8b9c0d1e2 (head)`.
- The original AI worktree remains clean at `41d2898` on
  `codex/openai-anthropic-model-support` and has not been edited by this work.
- The deployed remote-content release was developed in the isolated worktree
  `/Users/austinmcchord/Development/Email-remote-content-controls` on
  `codex/remote-content-controls`.
- A validated 1.38 GB custom-format backup remains protected at
  `/var/backups/mailapp/maildb-pre-product-polish-20260830T1031Z.dump`, mode
  `0600`, owned by `postgres`. This frontend-only candidate has no schema work.

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

- `make check` passes: 303 backend tests, 4 opt-in PostgreSQL skips, 113
  frontend tests, and a successful 502-module production build.
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

Pause here for production user testing. After the user resumes work, coordinate
the AI Markdown image SSRF fix with the AI work owner, then design the owned
remote-resource manifest/proxy and CID mapping as a separately reviewed backend
security release.
