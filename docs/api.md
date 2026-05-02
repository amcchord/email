# Read-Only Public API (`/api/v1`)

A small, stable JSON API for building external tools on top of your mail and
calendar data — the canonical use case is something like an e-ink "day ahead"
display.

## Authentication

The API uses per-user shared-secret tokens. Mint and revoke tokens from
**Settings → Profile & Accounts → API Tokens** in the web UI.

Tokens look like `mk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` and are shown
**exactly once** at creation. Only a SHA-256 hash is stored on the server.

Send the token in either header:

```
Authorization: Bearer mk_xxxxxxxx...
X-API-Key: mk_xxxxxxxx...
```

A token grants access to **the data of the user who minted it** (their
connected Google accounts, their calendar events, their mailboxes). Tokens
do not work in cookies and the cookie-based session does not work on
`/api/v1`.

Each token endpoint is independently rate-limited per token (60–120 req/min).

## Base URL

If your install lives at `https://email.example.com`, the API is at
`https://email.example.com/api/v1/...`.

## Endpoints

### `GET /api/v1/me`

Returns identity and connected account list — handy for verifying a token
and discovering account IDs.

```json
{
  "id": 1,
  "email": "you@example.com",
  "display_name": "You",
  "accounts": [
    { "id": 3, "email": "you@gmail.com" },
    { "id": 7, "email": "work@example.com" }
  ]
}
```

### `GET /api/v1/calendar/today`

Events that overlap "today" in the requested timezone (defaults to UTC).
Includes both timed and all-day events.

Query params:

| param | type   | default | notes                              |
|-------|--------|---------|------------------------------------|
| `tz`  | string | `UTC`   | IANA timezone, e.g. `America/New_York` |

```json
{
  "events": [
    {
      "id": 42,
      "account_email": "you@gmail.com",
      "google_event_id": "abc123",
      "calendar_id": "primary",
      "summary": "Standup",
      "location": "Zoom",
      "start_time": "2026-05-02T13:00:00+00:00",
      "end_time":   "2026-05-02T13:30:00+00:00",
      "is_all_day": false,
      "status": "confirmed",
      "html_link": "https://www.google.com/calendar/event?eid=...",
      "hangout_link": "https://meet.google.com/...",
      "organizer_email": "boss@example.com",
      "organizer_name": "Boss",
      "attendees": [...]
    }
  ],
  "total": 1
}
```

### `GET /api/v1/calendar/upcoming`

Next-N-days view, ordered by start time.

| param   | type | default | range  |
|---------|------|---------|--------|
| `days`  | int  | 7       | 1–90   |
| `limit` | int  | 50      | 1–500  |

Same event shape as `/calendar/today`.

### `GET /api/v1/emails/recent`

Most recent emails matching a mailbox. **Snippets only** — no full body
text/HTML, to keep payloads small for low-bandwidth clients.

| param         | type   | default | notes                                                 |
|---------------|--------|---------|-------------------------------------------------------|
| `limit`       | int    | 20      | 1–200                                                 |
| `unread_only` | bool   | false   |                                                       |
| `mailbox`     | string | `INBOX` | `INBOX`, `STARRED`, `SENT`, `DRAFTS`, `TRASH`, `SPAM`, `ALL`, or any Gmail label name |

```json
{
  "emails": [
    {
      "id": 9001,
      "gmail_message_id": "...",
      "gmail_thread_id": "...",
      "account_email": "you@gmail.com",
      "subject": "Lunch tomorrow?",
      "from_name": "Alex",
      "from_address": "alex@example.com",
      "date": "2026-05-02T11:14:00+00:00",
      "snippet": "Hey, want to grab lunch...",
      "is_read": false,
      "is_starred": false,
      "has_attachments": false,
      "labels": ["INBOX", "UNREAD"]
    }
  ],
  "total": 1
}
```

### `GET /api/v1/emails/unread-count`

Total unread INBOX count and a per-account breakdown. Useful as a
lightweight badge poll.

```json
{
  "unread": 12,
  "by_account": [
    { "account_id": 3, "account_email": "you@gmail.com", "unread": 9 },
    { "account_id": 7, "account_email": "work@example.com", "unread": 3 }
  ]
}
```

## Error responses

Standard FastAPI shape:

```json
{ "detail": "Invalid API token" }
```

| status | meaning                                       |
|--------|-----------------------------------------------|
| 401    | missing / invalid / revoked token, or inactive user |
| 400    | bad query param (e.g. unknown timezone)       |
| 429    | rate limit exceeded                            |

## Example: day-ahead display

```bash
TOKEN="mk_yourtoken..."
HOST="https://email.example.com"

# Identity check
curl -s -H "Authorization: Bearer $TOKEN" "$HOST/api/v1/me"

# Today's events in your local timezone
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/calendar/today?tz=America/New_York"

# Next 3 days, capped at 20 events
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/calendar/upcoming?days=3&limit=20"

# 5 most recent unread inbox emails
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/emails/recent?limit=5&unread_only=true"

# Just the unread count (cheap; safe to poll often)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/emails/unread-count"
```

## Revoking a token

Click **Revoke** next to the token in **Settings → Profile & Accounts →
API Tokens**. Revocation is immediate; the next request from any client
using that token returns 401.

## Security notes

- Treat tokens like passwords. They grant full read access to your
  emails and calendar.
- Tokens are stored only as `sha256(token)`; if you lose the plaintext,
  revoke the token and create a new one.
- The API never accepts JWT/cookie auth, and the web UI never accepts
  API tokens — there is no way for a stolen token to escalate into a
  web session, and no way for a stolen browser cookie to call `/api/v1`.
