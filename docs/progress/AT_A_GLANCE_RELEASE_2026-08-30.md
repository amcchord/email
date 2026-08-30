# At a Glance platform release — 2026-08-30

## Outcome

This milestone turns the existing e-ink terminal support into a shared At a
Glance platform. It adds fullscreen browser displays at exact landscape 16:9
and portrait 9:16 geometry, keeps the existing Editorial, Swiss, Day Ahead, and
Clock visual language, centralizes extension points, isolates browser secrets,
and adds conservative terminal battery guidance.

Browser flashing and OTA are deliberately not claimed here. Their safety
architecture and exit gates live in
[`../terminal/firmware-management.md`](../terminal/firmware-management.md).

## Release identity

- Base: Calendar closeout `a2c02bfcf62f0147209b365cdb918cb915d2a762`
- Application: `4c5a1febe7ba6508c74e51c1a950f7fb5ca9f124`
- Firmware roadmap: `1359a24671d3a738dfcf64b08238562b703663c9`
- Reviewed/deployed candidate: `c76cb5e67e3225ee1bb55b0e4986faa3c5c3c510`
- Schema path: `z7a8b9c0d1e2` -> `a8b9c0d1e2f3` -> `b9c0d1e2f3a4`

## Security and data impact

- Firmware continues to use the existing per-user route code.
- Each browser display receives a 192-bit token bound to one exact
  view/design/profile. The public route accepts no view override, frames are
  private-cache protected, and the Settings UI can rotate one URL at a time.
- `terminal_battery_samples` stores normalized sparse telemetry. Ingestion is
  bounded to one stored change per five minutes and active-device cleanup
  removes rows older than 90 days.
- `terminal_web_displays` stores generated view bindings and token values. Rows
  are created when the authenticated Settings screen first needs the catalog.
  No mailbox, Calendar, Google credential, or Home Assistant secret data moves
  into either table.

## Validation

- `make check`: 387 backend passed, 4 opt-in PostgreSQL tests skipped, 156
  frontend passed, and the 504-module production frontend built.
- Focused terminal/display/battery/renderer tests: 91 passed.
- Disposable PostgreSQL 17 migration rehearsal passed through upgrade,
  downgrade of the scoped-display revision, and re-upgrade to head; expected
  tables and indexes were verified.
- Generated in-app browser QA passed at exact 1280×720 and 720×1280 with no
  viewport or document overflow. Day Ahead retains its current 3:4 composition
  centered inside the portrait frame.
- Compile checks, focused import lint, and `git diff --check` passed.

## Deployment and rollback

Before migration, create and verify a protected PostgreSQL custom-format
backup. Fast-forward the clean production checkout to the exact reviewed
release, run `alembic upgrade head`, build the frontend as `mailapp`, and
restart only `mailapp`. Workers, TUI, Caddy, dependencies, and systemd units do
not change.

The safest code rollback is to return the application to `a2c02bf` while
leaving the two additive tables in place; the old code ignores them. A separate
schema downgrade would first remove browser-display tokens and then battery
history, invalidating browser links and discarding only newly collected
terminal data. It is not required for code rollback and must not be combined
with it casually.

## Post-deploy evidence

- GitHub `main` and clean production were fast-forwarded from `a2c02bf` to
  exact `c76cb5e` without rewriting history.
- Protected backup:
  `/var/backups/mailapp/maildb-pre-at-a-glance-20260830T1503Z.dump`,
  1,383,479,646 bytes, mode `0600`, owner `postgres:postgres`; `pg_restore
  --list` validation passed.
- Alembic reached `b9c0d1e2f3a4 (head)` transactionally. Both expected tables,
  the unique token index, user index, primary key, and per-view uniqueness
  constraint were present.
- The production frontend built 506 modules and only `mailapp` restarted. All
  seven checked services are active, `mailapp` reports zero restarts, and its
  post-restart warning-or-higher count is zero.
- Public health returned `ok`, `/` returned 200, unauthenticated terminal
  settings returned 401, and an unknown display credential returned 404.
- The authenticated Admin page showed five scoped browser cards with five
  distinct 32-character credentials plus battery collection/stale states. A
  live Clock display was exact 1280×720 with no overflow and remained Clock
  when an unsupported caller-side view override was appended.
- No worker, TUI, Caddy, dependency lock, systemd unit, Google/HA credential,
  mailbox, or Calendar data changed. The browser check created only the five
  intended per-user display-binding rows; no display URL was rotated.
