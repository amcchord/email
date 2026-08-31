# Saved Views / Custom Splits Release — 2026-08-31

## Outcome

The mail client now has deterministic, user-owned Saved Views as a first-class
Email workflow. A valid structured search can be named, scoped to all accounts
or one exact connected account, reopened from the Sidebar or command palette,
edited, reordered, and explicitly deleted. It closes the durable Custom Split
gap without Gmail mutation, AI classification, cached membership, or a second
Inbox result authority.

Exact application/runtime commit:
`a3f02a3a0ba07226f653c8d0986874ac12404bd4`.

## Durable contract

- Additive Alembic revision `a0b1c2d3e4f5`, directly from
  `f9a0b1c2d3e4`; no backfill.
- At most twelve rows per user. Each row contains only public/client UUIDs,
  owner, optional exact account, normalized name, validated query, position,
  revision, and timestamps.
- `GET/POST /api/saved-views`, `PUT/DELETE /api/saved-views/{id}`, and
  `POST /api/saved-views/reorder` are browser-session authenticated and always
  `private, no-store`.
- Create and exact PUT replay are idempotent. Owner-row locking serializes
  quota, names, positions, and mutations. Stale revisions or order snapshots
  return 409; foreign/missing views and accounts share 404.
- An account-scoped view is cascade-deleted with its account. Invalid scope is
  never coerced to all accounts.
- Search parsing is the existing 512-character bounded parser. Saved Views do
  not store results, message IDs, counts, content, or provider state.

## User experience

- Saved Views sits inside Email navigation with `0/12` capacity, clear loading,
  empty, retry, unavailable-account, and active states.
- The current structured search exposes **Save view**, **Saved**, or
  **Save changes** according to exact account+query identity.
- Opening a view applies account, `ALL` mailbox, structured query, and Inbox as
  one session snapshot. Search text never enters the navigation URL or browser
  storage.
- Command palette entries open each available view; `G V` opens/focuses the
  first-class section. Mobile controls remain at least 44px and the editor is a
  viewport-bound bottom sheet at 390x844.
- The editor owns explicit Create/Save, move up/down, Cancel, focus trapping,
  Escape, conflict reload, and a two-step permanent delete. Successful delete
  reloads authoritative compacted positions and revisions before another
  mutation can run.
- Auth changes purge every Saved View store and invalidate late responses.

## Review and verification

- Backend focused/head checks: 91 passed during implementation.
- Frontend focused checks: 7 passed after the final two P1 fixes.
- Generated fixture self-test proved CRUD/reorder, exact account/user isolation,
  idempotent create/PUT, 404/409/422 behavior, held-session provenance, private
  audit redaction, and zero sends/provider/mail/calendar/external calls.
- One independent P0/P1 review found the stale survivor revisions after
  deletion; the focused fix and regression passed. No other P0/P1 remained.
- Generated browser acceptance passed desktop and 390x844 create/open/modified,
  edit/rename/reorder/delete, transient retry, conflict recovery, stale-session
  isolation, `G V`, command palette, query-free URLs, and zero external or
  provider/mail/calendar writes. The mobile run caught and drove the off-canvas
  editor fix before release.
- Disposable PostgreSQL passed
  `f9 -> a0 -> f9 -> a0`; final current state was `a0b1c2d3e4f5 (head)`.
- One consolidated post-freeze gate passed 782 backend tests with 75 expected
  skips, all 516 frontend tests, and a 616-module production build.

Generated-only visual evidence:

```text
/Users/austinmcchord/Development/Email-release-evidence/saved-views-2026-08-31/
  desktop-editor.png
  desktop-saved-views-list.png
  mobile-editor-390x844.png
```

## Production result

- GitHub `main` and production application/runtime were fast-forwarded to exact
  `a3f02a3a0ba07226f653c8d0986874ac12404bd4`.
- Protected pre-a0 backup:
  `/var/backups/mailapp/maildb-pre-saved-views-20260831T1522Z.dump`,
  1,384,127,964 bytes, `postgres:postgres`, mode `0600`, SHA-256
  `c96ce925388b0eb97e64e987af6085c27549b744967dd1ef417a2e64dbf89476`;
  `pg_restore --list` passed.
- Production upgraded exactly `f9a0b1c2d3e4 -> a0b1c2d3e4f5`, replaced only
  `mailapp`, then built/published the 616-module frontend. Workers, cron, TUI,
  Caddy, PostgreSQL, and Redis were not restarted.
- The retired API process reached the known 90-second graceful-stop timeout.
  Replacement PID 2170998 is active with `NRestarts=0` and no warning-or-higher
  entries after its 15:25:49 UTC start boundary.
- All seven checked services and public/local health are healthy. Anonymous
  access is 401 with `private, no-store`; production has zero Saved View rows.
- Signed-in browser QA was read-only and showed `Saved Views 0/12` with the
  truthful empty instruction. It opened no mail and created no view or
  mail/calendar/provider mutation.

## Rollback boundary

Before any Saved View row exists, the table can be downgraded to f9 and the
application/frontend can be reverted. Once a user creates a view, downgrade
drops user-authored definitions and is data-lossy. Normal recovery should keep
a0, preserve rows, and roll application code forward. The protected pre-a0 dump
is the disaster-recovery boundary, not a routine application rollback.

## Follow-on boundary

Provider rules, notifications, badges, shared views, AI-maintained membership,
and cached counts are deliberately outside this release. Each changes the data
or mutation model and requires a separately owned milestone.
