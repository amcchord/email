# First-Class At a Glance Release — 2026-08-30

## Outcome

At a Glance is now a first-class authenticated application destination rather
than only a Settings section. The deployed application/runtime commit is
`945b71860e08d79e6ddeb5e3faccffe372418ff1`, based on exact shared closeout
`e4da24a37dcfcea02fa0d888315cbe4e96b89111`. The release is migration-free;
production Alembic remains `f3a4b5c6d7e8 (head)`.

The new route is directly accessible at `?page=at-a-glance`, appears as a
primary navigation tab, preloads through the shared lazy-route coordinator, and
has a global `g g` shortcut. Desktop, tablet, and narrow-screen navigation use
the same authenticated route and history/focus behavior as the other primary
application destinations.

## Product Experience

- The page projects every valid view/design/profile combination from the
  server-owned catalog. No view, design, or 16:9/9:16 compatibility list is
  hard-coded into the page.
- Authenticated previews use the canonical e-ink/browser render adapters, so
  Home Dashboard Editorial, Home Dashboard Swiss, Day Ahead Editorial, and
  Clock remain the actual current designs rather than divergent frontend
  approximations.
- The page supports landscape 16:9 and portrait 9:16 selection, refresh, an
  isolated full-size preview, and a direct handoff to the existing scoped HTML
  display links in Settings.
- Terminal health summarizes connection state, last check-in, battery level,
  predicted charge timing, trend-learning state, stale telemetry, charging,
  pending enrollment, review, and revocation without exposing raw MACs or
  scoped credentials.
- Loading, empty catalog, no-device, retryable request, partial-status, and
  preview-render failure states are explicit. Request and authenticated-session
  generations prevent a prior identity or superseded retry from publishing
  data into the page.

## Read/Management Boundary

`GET /api/terminal/experience` is owner-scoped and credential-free. It returns
only catalog metadata and the same bounded device/battery summaries used by the
management API. It does not return or mint the shared terminal code, browser
display tokens or URLs, Home Assistant values, firmware artifacts, or terminal
credentials.

`GET /api/terminal/experience/preview.png` accepts only a catalog-compatible
view/design/profile combination and renders it through the canonical adapter.
Both routes require the normal browser session, send private/no-store response
headers, and reject unknown or incompatible combinations.

Settings remains the deliberate management boundary for public display links,
link rotation, firmware schedule URLs, Home Assistant credentials, raw device
diagnostics, cadence, rename, Forget, secure revocation, enrollment, browser
firmware policy, future flashing, and OTA. The first-class route contains no
POST/PATCH/DELETE, Web Serial, binary download, flash, erase, rotate, revoke, or
Forget action.

## Verification

- The consolidated backend run passed 561 tests with 35 intentional
  PostgreSQL/external skips, including the new authenticated experience,
  credential-absence, catalog matrix, preview render, invalid-combination, and
  no-write cases.
- The consolidated frontend run passed 307 tests. The production frontend
  build transformed 526 modules and emitted a distinct At a Glance lazy chunk.
- `git diff --check` passed. The release added no dependency, database schema,
  Caddy, worker, firmware, key, credential, or environment change.
- Authenticated read-only production QA loaded the direct route, primary tab,
  catalog-driven view/design/profile controls, canonical preview, management
  handoff, and terminal health/charge notice. No terminal, mail, calendar,
  draft, or external state was mutated.

## Production Actions

- Fast-forwarded GitHub `main`, the feature branch, and clean production from
  `e4da24a37dcfcea02fa0d888315cbe4e96b89111` to runtime
  `945b71860e08d79e6ddeb5e3faccffe372418ff1`.
- Built the production frontend and restarted only `mailapp`. The retired API
  process again exceeded its 90-second graceful-stop window and systemd killed
  that old process; the replacement started active with zero automatic
  restarts.
- Verified all seven checked services active, public health `ok`, anonymous
  experience access `401`, exact clean Git, and unchanged Alembic
  `f3a4b5c6d7e8 (head)`.

## Remaining Firmware Boundary

The application feature is released, but browser device writing remains
deliberately locked. The next terminal milestone is physical E1001/E1002 RET1
enrollment, interrupted-write, three-slot recovery, rollback, revocation,
preserve-config, CA-failure, and ROM-recovery HIL. Only after that evidence may
the production Web Serial transport enter the bundle. Trusted device time/CA
validation and signed A/B OTA with pending-image validation and automatic
rollback remain later firmware milestones; E1004 remains unqualified.
