# Personal Snippets Release — 2026-08-30

## Outcome

Personal Snippets is complete at application commit
`1397160c2318d4d48997e800dbda20c536d8b0d5`. Every signed-in user can manage a
private library under Settings → Writing and insert a saved rich or plain-text
reply from Compose, the reader, or Flow with `Cmd/Ctrl+;`.

## Product behavior

- Search ranks exact shortcuts before names and body content. Arrow keys,
  Enter, Escape, Tab containment, trigger focus restoration, and a responsive
  bottom sheet make the picker usable without a pointer.
- The picker owns the active keyboard context, so modifier keys cannot fall
  through to Send or Send & Archive while it is open.
- Rich insertion restores the captured caret or selection, sanitizes stored
  HTML again at the editor boundary, and remains one Undo step. Plain editors
  insert the normalized text fallback without replacing surrounding content.
- Settings supports search, create, edit, revision conflicts, deletion, dirty
  close confirmation, retryable errors, empty/loading states, and narrow-screen
  editing. A create retry retains one UUID through the editor session.

## Durable and private contract

- Additive Alembic revision `d7e8f9a0b1c2` creates `personal_snippets` directly
  from production head `c6d7e8f9a0b1`. Records are owner-scoped, capped at 250
  per user, and uniquely constrained by owner/public UUID and owner/shortcut.
- Creates use a stable browser UUID. Exact lost-response create and update
  replays return the committed record; divergent UUID reuse, duplicate
  shortcuts, and stale revisions fail with 409.
- Replace is full and revision checked. Delete is revision checked,
  non-disclosing for foreign/missing identifiers, and idempotent after a lost
  successful response.
- Selecting a snippet copies sanitized content into the draft. Later edits or
  deletion never change an existing draft. No snippet body enters metadata-only
  fixture audits or ordinary service logs.

## Safety and verification

- Real mail and calendars remained read-only. Browser mutations used only the
  localhost generated-provider fixture and `.example.test` identities.
- Generated fixture verification covered CRUD, exact replays, divergent and
  stale conflicts, cross-user non-disclosure, hostile HTML, reset reseeding,
  and content-free audit output. It recorded zero unexpected mutations, unknown
  routes, external network calls, or provider sends.
- Browser QA covered Settings management, search/Enter insertion, one-step
  Undo, hostile-markup sanitization, desktop and 390×844 layouts, 44-pixel
  targets, and zero console warnings/errors.
- Independent release review found no P0. Its two P1 findings—unstable create
  retry identity and picker shortcut propagation—were fixed before the final
  gate.
- Final `make check`: 727 backend tests passed with 66 expected skips; all 448
  frontend tests passed; Vite transformed 595 production modules. The exact
  disposable PostgreSQL `c6 → d7 → c6 → d7` migration roundtrip and focused
  database lifecycle test passed before code freeze.

## Deployment and rollback

Deployment requires a validated pre-d7 PostgreSQL backup, a Git fast-forward,
frontend production build, `alembic upgrade head`, and replacement of only
`mailapp`. The migration is additive and requires no backfill. A downgrade to
`c6d7e8f9a0b1` drops every user-created snippet and is intentionally data-lossy;
normal rollback should retain d7 and roll application Git/frontend back unless
the table itself must be removed with explicit acceptance of that data loss.

## Production result

- GitHub and production deployed exact application/runtime
  `1397160c2318d4d48997e800dbda20c536d8b0d5`; production was exact and clean
  through pre-closeout commit `af235f6b8cbb079c7e2e7f6316bf52ce840fa316`.
- The protected pre-d7 backup is
  `/var/backups/mailapp/maildb-pre-personal-snippets-20260831T0247Z.dump`,
  1,383,786,224 bytes, `postgres:postgres`, mode `0600`, SHA-256
  `4fa32da76f8f3a8beab329aa20423d50abe1b0ba182f8ab7cabdc27fe6794bd8`.
- Production upgraded exactly `c6d7e8f9a0b1 → d7e8f9a0b1c2`, replaced only
  `mailapp`, and built 595 frontend modules. The retired process hit the known
  graceful-stop timeout; replacement PID 2137416 is active with `NRestarts=0`
  and no warning-or-higher entries after its startup boundary.
- All seven checked services are active, public health is `ok`, anonymous
  snippet access is 401, and the aggregate new-table count is zero. Signed-in
  read-only browser QA loaded Settings → Writing without creating or inserting
  real content.
