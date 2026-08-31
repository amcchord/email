# First-class Contacts Release — 2026-08-31

## Outcome

The Mail Client now has a first-class, responsive Contacts workspace built
from already-synchronized correspondence metadata. It is intentionally a
bounded relationship projection—not a writable address book—and therefore
requires no Google Contacts permission, provider call, new table, backfill, or
Alembic revision.

## User-facing changes

- Contacts is the first item under More, available from the command palette and
  the `G P` navigation shortcut.
- One exact connected account is selected at a time. Search and relationship
  filters cover all, two-way, received-only, and sent-only correspondents.
- The desktop workspace presents a contact list beside a relationship profile.
  Narrow screens use a focused list-to-profile transition with a visible Back
  action and return focus to the originating row.
- Profiles show normalized name/address, observed relationship dates/counts,
  recent content-free conversation pointers, and the bounded corpus coverage.
  The UI says “observed” and discloses when older relationships may be absent.
- Email opens one new Compose intent using the exact account and one canonical
  To recipient. A recent interaction opens only the exact account-owned anchor
  or thread after Inbox dataset authority is ready.
- Loading, empty, unavailable, Retry, pagination, keyboard navigation, and
  responsive states are explicit. Avatars use local initials; no remote image
  or tracking request is introduced.

## Backend and privacy contract

- `POST /api/contacts/query` returns an account-exact page of normalized
  relationship summaries and explicit coverage.
- `POST /api/contacts/profile` resolves one opaque contact key and returns the
  same summary plus up to 20 recent metadata-only conversation pointers.
- Both routes require the web session, verify that the account is active and
  owned by the current user, use non-disclosing 404s, and return
  `Cache-Control: private, no-store`.
- Search and opaque keys remain in POST bodies rather than URLs.
- The service selects at most the newest 4,000 eligible metadata rows from one
  account before aggregation. Draft, Spam, Trash, Bcc-only contacts, and every
  address owned by the signed-in user are excluded.
- Responses never include subject, snippet, body, Bcc, labels, attachments, AI
  output, digests, or raw headers. The same mailbox in two accounts receives
  different opaque HMAC identities.
- Mailbox admission matches the strict client boundary: maximum address/local/
  domain lengths, dot and label rules, and bounded formatted output. Invalid
  or sender-controlled poison metadata is skipped; RFC 2047 expansion that
  would exceed the response contract falls back to the safe normalized bare
  address without losing the valid contact.

## Exact navigation safety

- Query/profile responses are normalized as untrusted input. Mixed-account,
  malformed, duplicate, wrong-key, or wrong-anchor responses fail closed.
- Contact-to-Inbox authority is one session-only object containing exact
  account, anchor, thread, direction, date, and observed count. It is cleared
  on every authenticated-session transition.
- Inbox restores that anchor only after the requested account dataset becomes
  authoritative. This avoids cold lazy-route selection loss and prevents a
  stale account response from becoming reader authority.
- Off-page exact threads render chronologically with a synthetic local summary
  marked `conversation_scope: false`, so loading a thread does not imply that
  a broader list conversation was selected for action.
- Opening an already-read generated conversation caused no mark-read or other
  fixture mutation. Production acceptance remains read-only and will not open
  real mail.

## Changed implementation areas

### Backend

- `backend/services/contact_profiles.py` — bounded corpus query, normalized
  projection, opaque identities, deterministic ranking, strict mailbox
  admission, profile lookup, and content-free recent pointers.
- `backend/schemas/contact.py` — frozen request/response shapes and limits.
- `backend/routers/contacts.py` — authenticated query/profile endpoints and
  private no-store response policy.
- `backend/main.py` — Contacts router registration.
- `backend/tests/test_contact_profiles.py` — projection, privacy, ranking,
  account/key/profile, route/auth/no-store, SQL-bound, and poison-metadata
  regressions.

### Frontend

- `frontend/src/pages/Contacts.svelte` — complete responsive list/profile
  workspace and all user states/actions.
- `frontend/src/lib/contactProfiles.js` and tests — strict response
  normalization, bounded payloads, display helpers, and exact Compose/Inbox
  intents.
- `frontend/src/lib/api.js`, `lazyRoutes.js`, `shortcutDefaults.js`, and
  `stores.js` — POST API methods, lazy route, shortcuts, and session-only
  contact conversation authority.
- `TopBar.svelte`, `Layout.svelte`, `CommandPalette.svelte`, and
  `KeyboardShortcutHandler.svelte` — first More placement and navigation.
- `Inbox.svelte` — cold-mount intent restoration, exact account/thread fetch,
  anchor validation, and safe off-page chronological rendering.

### Generated acceptance and documentation

- `scripts/qa/generated_provider_draft_server.mjs` and
  `generated_contact_profiles_self_test.mjs` — localhost-only `.example.test`
  users/accounts/correspondents, exclusion/content sentinels, failure/delay/
  held-session cases, exact already-read message handoffs, and read-only audit
  counters.
- `docs/api.md`, `docs/progress/CURRENT.md`, `JOURNAL.md`, and
  `DECISIONS.md` — API, current state, release evidence, and D-046.

## Review and acceptance evidence

- Backend and UX audits independently selected the migration-free bounded
  projection and exact-account list/detail design.
- Generated safety review proved user/account isolation, Bcc/self/status
  exclusions, opaque keys, content-free shapes, stale-session handling, and
  zero provider/network capability.
- Browser acceptance covered anchored More placement, desktop profile,
  390×844 profile/Back/focus, account switching during delayed responses,
  filter/search/empty/error/Retry, and exact chronological thread opening.
- Browser console warnings/errors: 0.
- Generated audit after the exact thread journey: 0 expected mail mutations,
  0 unexpected mutations, 0 provider sends, 0 unknown routes, and 0 external
  network calls.
- A final independent review found one P1: malformed or RFC2047-expanded
  sender metadata could poison a whole response. Strict mailbox limits and
  safe formatting fallback fixed it; the focused poison-row regression passed.
- The one consolidated post-freeze gate passed 770 backend tests with 75
  expected skips, all 509 frontend tests, and a 612-module production build.

Generated screenshots are retained outside the repository at:

- `/Users/austinmcchord/Development/Email-release-evidence/contact-profiles-2026-08-31/contacts-more-menu.png`
- `/Users/austinmcchord/Development/Email-release-evidence/contact-profiles-2026-08-31/contacts-desktop.png`
- `/Users/austinmcchord/Development/Email-release-evidence/contact-profiles-2026-08-31/contacts-mobile.png`

## Data and migration impact

- Alembic remains `f9a0b1c2d3e4`.
- No table, row, provider contact, OAuth scope, worker job, or mailbox mutation
  is introduced.
- The projection is rebuilt from synchronized metadata on each request. Opaque
  keys are not durable references and may change if the application secret is
  deliberately rotated.

## Deployment and rollback

- Deployment requires a frontend production build and replacement of the API
  process for router registration. Mail workers, cron, Caddy, PostgreSQL, and
  Redis require no change.
- No database backup or migration is required because the release is
  migration-free and read-only.
- Rollback is a Git fast-forward/revert to the prior Signatures closeout,
  rebuild of the prior frontend, and API replacement. No data rollback exists
  or is needed.
- Exact runtime, production postflight, and final docs-closeout SHAs are added
  after deployment.
