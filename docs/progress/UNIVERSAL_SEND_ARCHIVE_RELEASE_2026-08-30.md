# Universal Send & Archive Release — 2026-08-30

## Outcome

Universal Send & Archive is complete at application commit
`c7171466d075fc74f12ccb47fb2ee2d27ec830a6`. Full Compose and inline reader
replies share an accessible Send options modal with immediate Send & Archive,
scheduled archive-after-delivery, and `Cmd/Ctrl+Shift+Enter`. New messages and
ordinary Send remain unchanged.

## Durable contract

- The browser may request the option only from one exact positive source email
  with complete account/thread/Message-ID/References provenance.
- HTTP 202 means the existing outbound outbox owns the immutable intent. The
  archive flag is retained with that intent and visible as a safe response
  boolean without exposing message content.
- Only provider-confirmed delivery can stage the deterministic
  conversation-scoped archive action. Reconciliation repeats the same action;
  Undo, scheduled cancellation, and delivery failure never archive.
- If Gmail history removes the validated source before a later delivery, the
  archive is a safe no-op and the confirmed send still becomes terminal.
- Undo/cancel reopens and refreshes the original durable draft identity, so an
  exact-source reply cannot conflict with an invented recovery draft.

## UI and recovery

- The first modal action is Send & Archive only for a verified reply. Scheduled
  choices expose an independent “Archive conversation after delivery” option.
- Escape is contained by the modal and restores focus to the options trigger.
  Failed inline submissions return false so the modal stays open.
- Accepted copy explicitly says archive waits for confirmed delivery. Scheduled
  status survives reload; recovered drafts never remember Send & Archive as a
  default.

## Safety and verification

- Real mail/calendar QA remained read-only. All mutations used localhost-only
  `.example.test` accounts; the fixture rejects any other domain.
- Generated self-test proved Undo archives 0, scheduled cancel archives 0,
  confirmed generated delivery archives 1, external network calls 0, and no
  unexpected mutations or unknown routes.
- Browser QA verified new-message fail-closed behavior, reply modal layout and
  focus, Escape containment, scheduled intent, and generated Undo. Screenshot:
  `universal-send-archive-desktop.png` in the task visualization artifacts.
- Independent review found no P0. Its two P1 and two P2 findings were fixed
  before the final gate.
- Final `make check`: 715 backend passed with 56 expected skips; all 422
  frontend tests passed; Vite transformed 588 production modules.

## Deployment and rollback

This release is migration-free and preserves production Alembic head
`c6d7e8f9a0b1`. Deployment requires a Git fast-forward, frontend production
build, and replacement of `mailapp` because the outbound response/service
changed. Rollback is a Git fast-forward to the prior runtime plus frontend
rebuild and API replacement; no database downgrade or data rewrite is needed.

## Production result

GitHub `main` and production received exact application/runtime commit
`c7171466d075fc74f12ccb47fb2ee2d27ec830a6`. Production built 588 modules and
replaced only `mailapp`; the known graceful-stop timeout affected the retired
process, while the replacement is active with zero automatic restarts. All
seven checked services and public health are healthy, Alembic remains
`c6d7e8f9a0b1 (head)`, production Git is clean, and anonymous outbound history
returns 401.
