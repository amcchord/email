# Read-Only Public API (`/api/v1`)

A small, stable JSON API for building external tools on top of your mail and
calendar data. The canonical use cases are a "day ahead" display, a
"newspaper front page" of your week, or a script that asks Claude
free-form questions about your inbox without touching the web UI.

## Contents

- [Authentication](#authentication)
- [Base URL](#base-url)
- [Rate limits](#rate-limits)
- [Endpoints](#endpoints)
  - Identity
    - [`GET /me`](#get-apiv1me)
  - Calendar
    - [`GET /calendar/today`](#get-apiv1calendartoday)
    - [`GET /calendar/upcoming`](#get-apiv1calendarupcoming)
    - [`GET /calendar/week`](#get-apiv1calendarweek)
  - Email
    - [`GET /emails/recent`](#get-apiv1emailsrecent)
    - [`GET /emails/important`](#get-apiv1emailsimportant)
    - [`GET /emails/digests`](#get-apiv1emailsdigests)
    - [`GET /emails/unread-count`](#get-apiv1emailsunread-count)
    - [`GET /emails/volume`](#get-apiv1emailsvolume)
  - Newspaper / briefing
    - [`GET /briefing`](#get-apiv1briefing)
    - [`GET /briefing/summary`](#get-apiv1briefingsummary)
  - Claude-powered Q&A
    - [`POST /ask`](#post-apiv1ask)
- [Error responses](#error-responses)
- [Recipes](#recipes)
  - [Day-ahead display](#day-ahead-display)
  - [Newspaper / week-ahead polling cadence](#newspaper--week-ahead-polling-cadence)
  - [Ask Claude from a script](#ask-claude-from-a-script)
- [Security notes](#security-notes)

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

## Base URL

If your install lives at `https://email.example.com`, the API is at
`https://email.example.com/api/v1/...`.

## Rate limits

Limits are per token. Heavier tiers protect Claude spend.

| Tier | Endpoints | Limit |
|------|-----------|-------|
| Cheap (DB only) | `/me`, `/calendar/today`, `/calendar/upcoming`, `/calendar/week`, `/emails/recent`, `/emails/important`, `/emails/digests`, `/emails/volume` | 60 / minute |
| Cheap (high-frequency) | `/emails/unread-count` | 120 / minute |
| Composite | `/briefing` | 30 / minute |
| AI prose | `/briefing/summary`, `/briefing?summary=true` (shares `/briefing` quota) | 10 / minute |
| Agent Q&A | `/ask` | 20 / minute |

Hitting a limit returns `429` with `{"detail": "Rate limit exceeded: ..."}`.

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

| param | type   | default | notes                                  |
|-------|--------|---------|----------------------------------------|
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

### `GET /api/v1/calendar/week`

Events grouped by local day for the next `days` days, with cheap importance
heuristics applied per event.

| param  | type   | default | notes                                  |
|--------|--------|---------|----------------------------------------|
| `tz`   | string | `UTC`   | IANA timezone for day bucketing        |
| `days` | int    | 7       | 1–21                                   |

An event is flagged `is_important: true` when any of:

- It has an attendee whose email isn't one of your connected accounts ("external attendee").
- The organizer is you (you scheduled the meeting).
- The summary contains a flagged keyword (`interview`, `review`, `board`,
  `1:1`, `kickoff`, `all hands`, `demo`, `presentation`, `exec`, `leadership`,
  `investor`, `customer`, `client`, `offsite`, `launch`, `release`,
  `performance review`, …).

`importance_reasons` is a short human-readable list (e.g. `["with 3 external attendee(s)", "\"review\" in title"]`).

`busy_minutes` sums non-all-day event durations clipped to the local day —
useful as a "how booked is each day" badge.

```json
{
  "timezone": "America/New_York",
  "days": [
    {
      "date": "2026-05-02",
      "label": "Today",
      "weekday": "Saturday",
      "busy_minutes": 145,
      "important_count": 1,
      "events": [
        {
          "id": 42,
          "summary": "1:1 with Boss",
          "start_time": "2026-05-02T13:00:00+00:00",
          "end_time":   "2026-05-02T13:30:00+00:00",
          "is_all_day": false,
          "is_important": true,
          "importance_reasons": ["with 1 external attendee(s)", "\"1:1\" in title"],
          "...": "(all the standard PublicCalendarEvent fields)"
        }
      ]
    }
  ]
}
```

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

### `GET /api/v1/emails/important`

Emails the AI has flagged as important: priority of `high` or `urgent`, or
flagged as `needs_reply` (and not ignored). Same per-email shape as
`/emails/recent`, plus four AI signal fields.

| param         | type   | default | notes                          |
|---------------|--------|---------|--------------------------------|
| `limit`       | int    | 20      | 1–200                          |
| `unread_only` | bool   | true    |                                |
| `days`        | int    | 7       | 1–90; only emails newer than this many days |
| `mailbox`     | string | `INBOX` | same values as `/emails/recent` |

Extra per-email fields:

| field         | type                          | meaning                       |
|---------------|-------------------------------|-------------------------------|
| `priority`    | int (`0`-`3`)                 | `0`=low, `1`=normal, `2`=high, `3`=urgent |
| `needs_reply` | bool                          | Recipient should write back   |
| `ai_summary`  | string \| null                | 1-2 sentence AI summary       |
| `ai_category` | `can_ignore`/`fyi`/`urgent`/`awaiting_reply` | AI category |

Ordered by `priority desc, needs_reply desc, date desc`.

```json
{
  "emails": [
    {
      "id": 9001,
      "subject": "Contract redlines for Friday",
      "from_name": "Alex",
      "from_address": "alex@client.com",
      "date": "2026-05-02T09:14:00+00:00",
      "snippet": "Attaching the latest redlines...",
      "is_read": false,
      "priority": 3,
      "needs_reply": true,
      "ai_summary": "Client sent contract redlines and needs sign-off by Friday.",
      "ai_category": "urgent",
      "...": "(plus all standard PublicEmail fields)"
    }
  ],
  "total": 1
}
```

### `GET /api/v1/emails/digests`

Recent AI-generated thread digests. Multi-message threads are collapsed into
one summary per thread, with conversation type and (for scheduling threads)
a resolved outcome.

| param             | type | default | notes                                  |
|-------------------|------|---------|----------------------------------------|
| `limit`           | int  | 20      | 1–100                                  |
| `unresolved_only` | bool | false   | If true, only threads with `is_resolved=false` |

```json
{
  "digests": [
    {
      "id": 12,
      "account_email": "you@gmail.com",
      "thread_id": "1860a...",
      "subject": "Coffee next week",
      "conversation_type": "scheduling",
      "summary": "Sam suggested Tue or Wed at 10am. You replied Wed works.",
      "resolved_outcome": "Wed at 10am, Blue Bottle Hayes Valley",
      "is_resolved": true,
      "key_topics": ["coffee", "scheduling"],
      "message_count": 4,
      "participants": [{"name": "Sam", "address": "sam@example.com"}],
      "latest_date": "2026-05-01T22:14:00+00:00",
      "updated_at":  "2026-05-01T22:15:00+00:00"
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
    { "account_id": 3, "account_email": "you@gmail.com",      "unread": 9 },
    { "account_id": 7, "account_email": "work@example.com",   "unread": 3 }
  ]
}
```

### `GET /api/v1/emails/volume`

Daily inbound (received + unread) and outbound (sent) email counts, plus a
per-account rollup. Days are bucketed in the requested local timezone.

| param  | type   | default | notes                                  |
|--------|--------|---------|----------------------------------------|
| `days` | int    | 14      | 1–90                                   |
| `tz`   | string | `UTC`   | IANA timezone for day bucketing        |

```json
{
  "timezone": "America/New_York",
  "received_total": 184,
  "sent_total": 21,
  "average_per_day": 13.14,
  "days": [
    { "date": "2026-04-19", "received": 18, "unread": 6, "sent": 1 },
    { "date": "2026-04-20", "received": 22, "unread": 9, "sent": 4 }
  ],
  "by_account": [
    { "account_id": 3, "account_email": "you@gmail.com",    "received": 120, "sent": 12 },
    { "account_id": 7, "account_email": "work@example.com", "received":  64, "sent":  9 }
  ]
}
```

### `GET /api/v1/briefing`

The "newspaper front page". One call returns today, tomorrow, the week
ahead, important emails, recent thread digests, recent volume, and unread
counts. Ideal for an e-ink display or a morning dashboard.

| param             | type   | default | notes                                                                      |
|-------------------|--------|---------|----------------------------------------------------------------------------|
| `tz`              | string | `UTC`   | IANA timezone for day bucketing                                            |
| `days`            | int    | 7       | 1–14; how many days in `week_ahead`                                        |
| `summary`         | bool   | false   | If true, also generates a Claude-written prose briefing (counts against the 10/min AI tier) |
| `summary_chars`   | int    | 600     | 100–4000. Soft target for the AI prose length, in characters. Ignored when `summary=false`. The model is told to aim for this length and the response is soft-trimmed at sentence boundaries if it overshoots by more than ~40%. |
| `important_limit` | int    | 20      | 1–100. Number of `important_emails` to include.                            |
| `digests_limit`   | int    | 10      | 1–50. Number of `recent_digests` to include.                               |

Without `summary=true` the endpoint runs purely against the database and
parallelises its sub-queries; expect ~50–150 ms typical latency. With
`summary=true` it then makes one Claude call (a few seconds; token budget
scales with `summary_chars`).

The `important_limit` value also bounds how many emails feed into the AI
prose, so trimming it makes the prose call faster and cheaper as well.

```json
{
  "meta": {
    "generated_at": "2026-05-02T13:46:00+00:00",
    "timezone": "America/New_York",
    "days": 7,
    "summary_included": true,
    "summary_model": "claude-sonnet-4-6",
    "summary_tokens_used": 920
  },
  "today":      [ /* PublicWeekEvent objects */ ],
  "tomorrow":   [ /* PublicWeekEvent objects */ ],
  "week_ahead": [ /* PublicWeekDay objects, see /calendar/week */ ],
  "important_emails": [ /* PublicImportantEmail objects, see /emails/important */ ],
  "recent_digests":   [ /* PublicThreadDigest objects, see /emails/digests */ ],
  "volume":           { /* PublicVolumeResponse, see /emails/volume */ },
  "unread":           { /* PublicUnreadCountResponse, see /emails/unread-count */ },
  "summary": "Your morning is light - just a 1:1 with your manager at 9. The bigger story is the contract redlines from Alex that landed last night and need eyes before Friday's call. Inbox volume is up roughly 30% over last week, mostly customer threads about the launch. Looking out: Wednesday's all-hands plus an investor update Thursday afternoon are the two anchors of the week."
}
```

### `GET /api/v1/briefing/summary`

Just the Claude-written prose. Useful when you poll `/briefing` (the data
part) on a fast cadence and refresh the prose less frequently.

| param             | type   | default | notes                                                       |
|-------------------|--------|---------|-------------------------------------------------------------|
| `tz`              | string | `UTC`   | IANA timezone for day bucketing                             |
| `days`            | int    | 7       | 1–14                                                        |
| `chars`           | int    | 600     | 100–4000. Soft target for prose length in characters.       |
| `important_limit` | int    | 20      | 1–100. How many important emails to feed Claude as context. |
| `digests_limit`   | int    | 10      | 1–50. How many recent digests to feed Claude as context.    |

Length guidance the model gets, by `chars` value:

| `chars` | Style                                                                  |
|---------|------------------------------------------------------------------------|
| ≤ 200   | One tight sentence; single most important thing only                   |
| ≤ 400   | 1–2 sentences; today's headline plus at most one other beat            |
| ≤ 800   | 2–3 short paragraphs                                                   |
| ≤ 1500  | 3–4 paragraphs covering today, anchor events, and 2–3 specific threads |
| > 1500  | A full column with multiple specific events/threads and a real outlook |

```json
{
  "summary": "Your morning is light...",
  "model": "claude-sonnet-4-6",
  "tokens_used": 920,
  "char_target": 600,
  "generated_at": "2026-05-02T13:46:00+00:00",
  "timezone": "America/New_York"
}
```

### `POST /api/v1/ask`

Free-form Q&A about your emails and calendar. Internally runs the same
plan → execute → verify Claude agent that powers the in-app chat, but
returns one JSON response instead of an SSE stream and **does not**
persist a `ChatConversation` (so calls don't clutter your web chat history).

Request body:

| field             | type   | default | notes                                  |
|-------------------|--------|---------|----------------------------------------|
| `prompt`          | string | —       | Required. Free-form question.          |
| `tz`              | string | null    | Reserved for future use; currently the agent infers times from event metadata. |
| `fast`            | bool   | false   | If true, swap to Haiku for plan/execute/verify (cheaper, faster, less smart). |
| `timeout_seconds` | int    | 60      | Server-side ceiling: 120s. On timeout returns 504. |

Response:

```json
{
  "answer": "You have three meetings tomorrow: a 1:1 with Boss at 9, the launch sync at 11, and an investor update at 3. The 11am one has the most prep -- Alex sent contract redlines that you should review first.",
  "clarification": null,
  "plan": [
    { "id": 1, "description": "Look up tomorrow's calendar events", "search_strategy": "calendar_search by date", "depends_on": [] },
    { "id": 2, "description": "Find emails related to those meetings", "search_strategy": "search_emails by attendees + topics", "depends_on": [1] }
  ],
  "task_results": {
    "1": "Found 3 meetings on 2026-05-03",
    "2": "Found 2 relevant threads, including contract redlines from Alex"
  },
  "model": "claude-sonnet-4-6",
  "tokens_used": 4231,
  "duration_seconds": 6.42
}
```

If the agent isn't confident and asks back, `answer` is null and
`clarification` holds the question to relay to your user:

```json
{
  "answer": null,
  "clarification": "Which week did you mean -- this week or next week?",
  "plan": [],
  "task_results": {},
  "model": "claude-sonnet-4-6",
  "tokens_used": 412,
  "duration_seconds": 1.18
}
```

Errors specific to this endpoint:

| status | when |
|--------|------|
| 400    | empty `prompt`, or no Google accounts connected |
| 502    | upstream Anthropic error |
| 504    | did not finish within `timeout_seconds` (capped at 120s) |

## Error responses

Standard FastAPI shape:

```json
{ "detail": "Invalid API token" }
```

| status | meaning                                                |
|--------|--------------------------------------------------------|
| 400    | bad request (unknown timezone, no accounts, empty prompt) |
| 401    | missing / invalid / revoked token, or inactive user    |
| 429    | rate limit exceeded                                    |
| 502    | upstream Anthropic error (AI endpoints only)           |
| 503    | Claude API key not configured (AI endpoints only)      |
| 504    | `/ask` timed out                                       |

## Recipes

### Day-ahead display

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

### Newspaper / week-ahead polling cadence

For a "morning newspaper" device, the cheapest pattern is to poll
`/briefing` for the data and `/briefing/summary` for the prose on a slower
cadence so the AI quota isn't wasted refreshing the same paragraph.

```bash
TOKEN="mk_yourtoken..."
HOST="https://email.example.com"
TZ="America/New_York"

# Every 5 minutes -- cheap composite payload (no Claude call)
# Trim what you don't need with important_limit / digests_limit
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/briefing?tz=$TZ&days=7&important_limit=10&digests_limit=5"

# Every 30 minutes -- refresh the AI-written prose, sized to a small e-ink screen
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/briefing/summary?tz=$TZ&days=7&chars=400"

# A single one-shot call that includes everything (counts against the 10/min AI tier)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/briefing?tz=$TZ&days=7&summary=true&summary_chars=800&important_limit=15"
```

For a richer "feel for the week ahead" view, combine `/calendar/week`
(`busy_minutes` and `important_count` per day) with `/emails/important`
(things waiting on you) and `/emails/volume` (whether your week is loud or
quiet relative to the trend).

### Ask Claude from a script

```bash
TOKEN="mk_yourtoken..."
HOST="https://email.example.com"

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What does my Wednesday look like, and is there anything I should prep for?",
    "timeout_seconds": 60
  }' \
  "$HOST/api/v1/ask"

# Cheaper / faster (Haiku for all phases)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "prompt": "Any unread emails I should reply to today?", "fast": true }' \
  "$HOST/api/v1/ask"
```

## Security notes

- Treat tokens like passwords. They grant full read access to your
  emails and calendar, plus AI Q&A which can cost you Claude tokens.
- Tokens are stored only as `sha256(token)`; if you lose the plaintext,
  revoke the token and create a new one.
- The API never accepts JWT/cookie auth, and the web UI never accepts
  API tokens — there is no way for a stolen token to escalate into a
  web session, and no way for a stolen browser cookie to call `/api/v1`.
- `/ask` uses the same agent as the web chat but doesn't persist a
  `ChatConversation`; revoking a token therefore wipes out an attacker's
  ability to ask further questions but doesn't leave traces in your
  in-app chat history.

## Revoking a token

Click **Revoke** next to the token in **Settings → Profile & Accounts →
API Tokens**. Revocation is immediate; the next request from any client
using that token returns 401.
