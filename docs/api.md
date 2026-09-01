# Read-Only Public API (`/api/v1`)

A small, stable JSON API for building external tools on top of your mail and
calendar data. The canonical use cases are a "day ahead" display, a
"newspaper front page" of your week, or a script that asks the configured AI
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
  - AI-powered Q&A
    - [`POST /ask`](#post-apiv1ask)
- [Error responses](#error-responses)
- [Recipes](#recipes)
  - [Day-ahead display](#day-ahead-display)
  - [Newspaper / week-ahead polling cadence](#newspaper--week-ahead-polling-cadence)
  - [Ask the mail assistant from a script](#ask-the-mail-assistant-from-a-script)
- [Security notes](#security-notes)
- [Web session-only calendar reads](#web-session-only-calendar-reads)
- [Web session-only structured email search](#web-session-only-structured-email-search)
- [Web session-only Saved Views](#web-session-only-saved-views)
- [Web session-only attachment workspace](#web-session-only-attachment-workspace)
- [Web session-only attachment preview and download](#web-session-only-attachment-preview-and-download)
- [Web session-only Inbox triage preferences](#web-session-only-inbox-triage-preferences)
- [Web session-only durable mail actions](#web-session-only-durable-mail-actions)
- [Web session-only durable Snooze reminders](#web-session-only-durable-snooze-reminders)
- [Web session-only automatic follow-up reminders](#web-session-only-automatic-follow-up-reminders)
- [Web session-only per-account signatures](#web-session-only-per-account-signatures)
- [Web session-only durable outbound delivery](#web-session-only-durable-outbound-delivery)
- [Web session-only durable draft sessions](#web-session-only-durable-draft-sessions)
- [Web session-only Todo ownership](#web-session-only-todo-ownership)
- [At a Glance displays and terminal management](#at-a-glance-displays-and-terminal-management)

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

Limits are per token. Heavier tiers protect AI-provider spend.

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
| `summary`         | bool   | false   | If true, also generates an AI-written prose briefing (counts against the 10/min AI tier) |
| `summary_chars`   | int    | 600     | 100–4000. Soft target for the AI prose length, in characters. Ignored when `summary=false`. The model is told to aim for this length and the response is soft-trimmed at sentence boundaries if it overshoots by more than ~40%. |
| `important_limit` | int    | 20      | 1–100. Number of `important_emails` to include.                            |
| `digests_limit`   | int    | 10      | 1–50. Number of `recent_digests` to include.                               |

Without `summary=true` the endpoint runs purely against the database and
parallelises its sub-queries; expect ~50–150 ms typical latency. With
`summary=true` it then makes one model call (a few seconds; token budget
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
    "summary_model": "gpt-5.6-terra",
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

Just the AI-written prose. Useful when you poll `/briefing` (the data
part) on a fast cadence and refresh the prose less frequently.

| param             | type   | default | notes                                                       |
|-------------------|--------|---------|-------------------------------------------------------------|
| `tz`              | string | `UTC`   | IANA timezone for day bucketing                             |
| `days`            | int    | 7       | 1–14                                                        |
| `chars`           | int    | 600     | 100–4000. Soft target for prose length in characters.       |
| `important_limit` | int    | 20      | 1–100. How many important emails to feed the model as context. |
| `digests_limit`   | int    | 10      | 1–50. How many recent digests to feed the model as context.    |

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
  "model": "gpt-5.6-terra",
  "tokens_used": 920,
  "char_target": 600,
  "generated_at": "2026-05-02T13:46:00+00:00",
  "timezone": "America/New_York"
}
```

### `POST /api/v1/ask`

Free-form Q&A about your emails and calendar. Internally runs the same
plan → execute → verify agent that powers the in-app chat, but
returns one JSON response instead of an SSE stream and **does not**
persist a `ChatConversation` (so calls don't clutter your web chat history).

Request body:

| field             | type   | default | notes                                  |
|-------------------|--------|---------|----------------------------------------|
| `prompt`          | string | —       | Required. Free-form question.          |
| `tz`              | string | null    | Reserved for future use; currently the agent infers times from event metadata. |
| `fast`            | bool   | false   | If true, use the efficient GPT-5.6 Luna profile for all phases. |
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
  "model": "gpt-5.6-sol",
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
  "model": "gpt-5.6-sol",
  "tokens_used": 412,
  "duration_seconds": 1.18
}
```

Errors specific to this endpoint:

| status | when |
|--------|------|
| 400    | empty `prompt`, or no Google accounts connected |
| 502    | upstream AI provider error |
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
| 502    | upstream AI provider error (AI endpoints only)         |
| 503    | selected provider API key not configured (AI endpoints only) |
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

# Every 5 minutes -- cheap composite payload (no AI call)
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

### Ask the mail assistant from a script

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

# Cheaper / faster (GPT-5.6 Luna at low effort for all phases)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "prompt": "Any unread emails I should reply to today?", "fast": true }' \
  "$HOST/api/v1/ask"
```

## Security notes

- Treat tokens like passwords. They grant full read access to your
  emails and calendar, plus AI Q&A which can consume provider tokens.
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

## Web session-only calendar reads

The authenticated Calendar screen reads the local Google Calendar cache through:

```text
GET /api/calendar/events?start=YYYY-MM-DD&end=YYYY-MM-DD&tz=America/New_York&account_id={optional_owned_id}
GET /api/calendar/sync-status
```

`start` and `end` are inclusive local calendar dates interpreted in the IANA
`tz`. Timed-event selection uses the equivalent half-open instant range
`[start at local midnight, day after end at local midnight)`, so DST transition
days retain their real 23- or 25-hour duration. An event overlaps when it starts
before the exclusive range end and ends after the range start. Google all-day
events use their native exclusive `end_date`, with the same half-open overlap
rule. Events ending exactly at the requested start are excluded.

An optional positive `account_id` must belong to the session user; otherwise
the route returns 404. Invalid dates, a reversed range, or an unknown timezone
return 400. The response remains `{ "events": [...], "total": n }` and contains
cached data only; `/sync-status` is the separate freshness and connection-health
authority used by the UI. Public API tokens cannot call these routes.

### Private Share Availability snapshots

Compose, reader reply, and Flow can calculate proposed meeting times from the
same synchronized primary-calendar cache:

```text
POST /api/calendar/availability
```

This route is available only to the authenticated web session and every
response is `Cache-Control: private, no-store`. A request names the exact
active owned `account_ids`, inclusive local `start_date` and `end_date` within
the next 21 days, an IANA `timezone`, a supported `duration_minutes` and
`step_minutes`, local `day_start`/`day_end`, `include_weekends`, and bounded
`minimum_notice_minutes`. Unknown, foreign, inactive, duplicated, or malformed
account scope fails closed; there is no fallback to all accounts.

The response contains only `ready`, `generated_at`, timezone and duration,
per-account `{ account_id, account_email, state, last_success_at }` coverage,
and bounded `{ start, end }` slots. It never returns event subjects, attendees,
locations, descriptions, provider identifiers, or calendar identifiers. The
calculation reads PostgreSQL only and performs no Google call, event hold,
event creation, cache write, or mail action.

Every selected account must retain the recorded Calendar read scope, have a
successful full synchronization, have no reauthorization or sync error, and
have a full/incremental success within 30 minutes. Active synchronization also
makes the snapshot non-ready. Availability rechecks that status after reading
events and discards every slot if the sync generation changed, preventing a
partially applied incremental sync from being presented as free time.
Cancelled, transparent, and self-declined events do not block; tentative,
needs-action, opaque timed events and all-day events do. DST gaps are skipped,
folds resolve deterministically, and emitted slots must have the exact requested
elapsed duration. The client shows source/freshness truth inside the picker but
does not insert connected account addresses or sync timestamps into recipient
copy. This is a synchronized availability snapshot, not live availability, a
hold, a booking link, or an invitation.

## Web session-only structured email search

The authenticated web application, not the `/api/v1` token surface, exposes
composable search through the normal email-list route:

```text
GET /api/emails/?search={query}&mailbox=ALL&tz=America/New_York
```

The route always constrains results to accounts owned by the browser-session
user. An explicit unknown or foreign `account_id` returns 404 rather than
falling back to all owned accounts. `account:` and `label:` operators can only
narrow that ownership boundary.

Search terms separated by whitespace compose with AND. A standalone `OR`
starts another group, `-` excludes one term, and double quotes request an exact
phrase. Parenthesized groups are intentionally rejected until their precedence
can be represented consistently in both the API and UI.

Supported operators are:

| syntax | meaning |
|--------|---------|
| `from:`, `to:`, `cc:`, `bcc:` | sender or recipient name/address contains the literal value |
| `subject:`, `body:` | subject, snippet, or plain-text body contains the literal value |
| `after:YYYY-MM-DD` | at or after local midnight on the date |
| `before:YYYY-MM-DD` | before local midnight on the date |
| `is:read\|unread\|starred\|unstarred\|draft\|sent` | message state |
| `has:attachment` | message has at least one attachment |
| `in:inbox\|sent\|drafts\|archive\|starred\|spam\|trash\|all\|anywhere` | mailbox scope |
| `account:` | owned account ID, email, name, description, or short label |
| `label:` | exact Gmail label ID or case-insensitive label name within owned accounts |

Unknown operator-shaped text such as `ticket:1234` remains an ordinary search
term for compatibility. Operator names and enumerated values are
case-insensitive. Quoted values support `\"` and `\\` escapes. Queries are
limited to 512 characters, 32 clauses, and 256 characters per value.

`tz` is an IANA timezone used only for date boundaries and defaults to UTC.
`after:` is inclusive; `before:` is exclusive. Invalid dates, timezones,
recognized operator values, quotes, escapes, OR placement, and limits return a
stable string `detail` with status 422.

The outer `mailbox` remains backward compatible when the query has no positive
`in:` clause. A positive `in:` supplies mailbox scope for its OR branch; other
OR branches remain in regular mail rather than silently expanding into Spam
or Trash. The web UI submits non-empty search with `mailbox=ALL`, suspends
Focused/smart filters while searching, preserves an explicit account filter,
and restores the prior mailbox/filter context when search is cleared.

The authenticated Inbox, mailbox, and search surfaces can request an
authoritative conversation projection through:

```text
GET /api/emails/conversations?mailbox=INBOX&page=1&page_size=50&search={optional_query}
```

It accepts the same owned-account, mailbox, label, search, timezone, read,
star, AI-category, and needs-reply filters as the message list. PostgreSQL
groups and counts before pagination by the exact `(account_id,
gmail_thread_id)` identity. A missing or whitespace-only thread ID is isolated
as its own typed message identity instead of being merged with unrelated mail.
The newest matching message is the row anchor; aggregate fields describe all
currently synchronized members of that owned conversation:

- `conversation_key`, `account_id`, `account_email`, and `anchor_email_id`;
- `member_count`, `matched_count`, and `unread_count`;
- `star_state` (`none`, `some`, or `all`) and attachment-any state; and
- the label union plus per-label `some`/`all` coverage.

The literal, otherwise-unfiltered Inbox exposes one coherent Split projection:

```text
GET /api/emails/conversations/split?page=1&page_size=25&account_id={optional_owned_account}
```

Placement is derived once from the authoritative newest Inbox anchor after
conversation identity is established and before count/pagination. One
PostgreSQL statement ranks and pages both sections and returns
`{ "focused": ConversationListResponse, "other": ConversationListResponse,
"total": n }`, so a concurrent classifier update cannot create a cross-request
gap or duplicate. Each row carries `inbox_placement` and the stable
`inbox_placement_reason` enum. The two result sets are disjoint and their exact
totals sum to `total`. Missing analysis fails visibly into Focused rather than
hiding new mail while background classification catches up. The projection
uses only persisted priority, reply, trusted-contact, delegation, subscription,
and low-priority signals; it never calls an AI provider or moves Gmail mail.
Owned `account_id` narrowing remains supported.

Authenticated users can add an explicit local correction without changing
Gmail labels, provider state, AI analysis, or any mail action. Every endpoint
below is session-authenticated and returns `Cache-Control: private, no-store`:

```text
GET    /api/inbox-placement-rules?account_id={optional_owned_account}
GET    /api/inbox-placement-rules/candidate?account_id={owned_account}&anchor_email_id={current_inbox_anchor}
POST   /api/inbox-placement-rules
PUT    /api/inbox-placement-rules/{rule_uuid}
DELETE /api/inbox-placement-rules/{rule_uuid}?revision={current_revision}
```

The candidate route accepts only the exact active owned account and current
authoritative synchronized Inbox anchor. It returns safe account, conversation,
sender, and exact-domain display values plus any matching rules; raw provider
thread/message selectors never leave the server. `POST` accepts a client UUID
`create_id`, that account and anchor, one `conversation|sender|domain` scope,
one `focused|other` placement, `enabled`, and `expected_revision`. Revision
zero means no rule currently exists. The server derives the selector, locks the
owned account, enforces a 500-rule account limit, and treats an exact lost-response
replay as success. `PUT` can change only placement/enabled with the exact
current revision; selector/scope remain immutable. `DELETE` is also revision
guarded. Foreign, missing, inactive, or stale candidates fail closed without
widening account ownership; conflicting revisions return 409.

Enabled rules resolve before the system reason in strict order: exact
conversation, exact sender, then exact domain. Exact domains never imply their
subdomains. The winning rule participates inside the same authoritative SQL
projection before section totals, ranking, windowing, and paging. Rule-backed
conversation rows carry `inbox_placement_source="rule"`, the safe public rule
UUID/scope/revision, and `user_rule_focused|user_rule_other`; system rows keep
their prior reason and `inbox_placement_source="system"`. Disabled rules remain
visible in the private ledger but do not affect placement. Immediate UI Undo
uses the returned revision to delete a newly created rule or restore the exact
captured prior state, then reloads both sections authoritatively.

The section-specific compatibility form remains available to API clients:

```text
GET /api/emails/conversations?mailbox=INBOX&inbox_placement=focused|other
```

Combining that compatibility parameter with search, labels, non-Inbox
mailboxes, state/category/needs-reply filters, or the legacy ignored-category
exclusion returns 422 rather than presenting a partial split as authoritative.

The response envelope is `{ "conversations": [...], "total": n, "page": n,
"page_size": n, "total_pages": n }`, where totals and page boundaries count
conversations rather than messages. The ordinary Inbox projection excludes
active durable Snoozes in the same server query so a page-local client filter
cannot make totals false. Search and other mailboxes retain those rows and may
annotate their active reminder state separately.

Email list, detail, and thread payloads include `is_sent`, `is_trash`, and
`is_spam` alongside the existing read/starred/draft state. These additive
fields let mixed-folder search results render recipients and expose safe
Restore/Not Spam actions per message instead of inferring state from the outer
mailbox parameter.

Email detail and thread-member payloads also include the authoritative
`account_id`, `account_email`, and optional `references_header`. Reply clients
must use that identity instead of selecting the first configured account, and
can extend the existing RFC References chain instead of replacing it.

Thread reads accept an additive account scope:

```text
GET /api/emails/thread/{thread_id}?account_id={owned_account_id}&order=asc|desc
```

When `account_id` is supplied, the response contains only messages from that
owned account. An unknown or foreign account returns the same 404 as a missing
thread. Omitting the parameter preserves a legacy read only when the thread ID
is unique across the user's owned accounts; an ambiguous cross-account thread
returns 409 rather than combining mail. First-party conversation and reply
surfaces always send the exact account scope.

## Web session-only Saved Views

Saved Views are private named definitions over the structured-search contract
above. They are available only to the authenticated browser session, never to
`/api/v1` tokens. Every response, including validation, authentication, not-
found, and conflict responses, carries `Cache-Control: private, no-store`.

```text
GET    /api/saved-views
POST   /api/saved-views
PUT    /api/saved-views/{view_id}
DELETE /api/saved-views/{view_id}?revision={positive_integer}
POST   /api/saved-views/reorder
```

The collection response is:

```json
{
  "items": [
    {
      "id": "0c10bd58-ec55-4718-8418-c2d7c48f1f12",
      "create_id": "8400dc83-f5cb-4128-950f-e76fded3b4b0",
      "name": "Leadership follow-ups",
      "account_id": 7,
      "query": "from:leader@example.test is:unread in:inbox",
      "position": 0,
      "revision": 1,
      "created_at": "2026-08-31T15:00:00Z",
      "updated_at": "2026-08-31T15:00:00Z"
    }
  ],
  "max_views": 12
}
```

`POST` accepts exactly `{ create_id, name, account_id, query }`. The client UUID
is an idempotency identity: an exact replay returns the existing view with 200;
reusing it for different content returns 409. A new view returns 201. `PUT`
accepts exactly `{ revision, name, account_id, query }`; an exact retry of the
immediately successful replacement is idempotent, while any stale or divergent
revision returns 409. Names are normalized, limited to 80 characters, and
case-insensitively unique per user. Queries are limited to 512 characters and
must pass the same parser used by Inbox search.

`account_id` may be `null` for all owned accounts or one positive account owned
by the session user. Missing and foreign accounts both return 404; the server
never coerces an invalid account to `null`, which would broaden the view. If an
account is removed, its account-scoped views are deleted rather than widened.

Reorder accepts one authoritative snapshot:

```json
{
  "expected_order": [
    "0c10bd58-ec55-4718-8418-c2d7c48f1f12",
    "5503a580-cad9-4cbe-9ec2-21b9cdbf3373"
  ],
  "view_ids": [
    "5503a580-cad9-4cbe-9ec2-21b9cdbf3373",
    "0c10bd58-ec55-4718-8418-c2d7c48f1f12"
  ]
}
```

Both arrays must contain the exact current collection once each. A concurrent
change returns 409; success returns the normalized collection with updated
positions and revisions. Deletion also compacts following positions, so clients
must refresh the authoritative collection after a successful 204.

Saved Views store only the bounded definition and ownership metadata. They do
not cache message IDs or results, call Gmail or AI, move mail, or write any
mail/calendar state. The first-party UI keeps queries in authenticated session
memory and request bodies; opening a view applies its account and query without
placing private terms in navigation URLs or browser storage.

## Web session-only attachment workspace

The authenticated browser application exposes a read-only file-discovery
projection over already synchronized local metadata:

```text
POST /api/attachments/query
```

The request is always bound to one exact active account owned by the session
user:

```json
{
  "account_id": 7,
  "query": "quarterly",
  "kind": "document",
  "direction": "received",
  "cursor": null,
  "page_size": 30
}
```

`query` is a literal case-insensitive filename, subject, sender-name, or
sender-address search limited to 256 characters. `kind` is one of `all`,
`document`, `image`, `archive`, or `other`; `direction` is `all`, `received`,
or `sent`; and `page_size` is 1–50. A supplied cursor is signed and bound to
the exact user, account, query, kind, and direction, so it cannot be replayed
under a broader or different query. Missing, inactive, and foreign accounts
all return 404 instead of falling back to another account.

The response contains only explicitly allowlisted display metadata:

```json
{
  "account_id": 7,
  "items": [
    {
      "account_id": 7,
      "attachment_id": 44,
      "email_id": 1201,
      "filename": "quarterly-report.pdf",
      "content_type": "application/pdf",
      "size_bytes": 84721,
      "message_date": "2026-08-30T18:00:00Z",
      "sender_name": "Example Sender",
      "sender_address": "sender@example.test",
      "subject": "Quarterly review",
      "is_sent": false
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

Results use stable keyset order by message date, email ID, and attachment ID.
Draft, Spam, Trash, and inline parts are excluded. Invalid sender metadata is
reduced to `null`; filenames and content types use sanitized fallbacks. The
projection never returns provider IDs, cache/storage paths, content IDs,
recipient fields, Bcc, snippets, bodies, or AI output.

Listing, search, filtering, pagination, keyboard selection, and parent-message
navigation are PostgreSQL-only and never fetch attachment bytes, call Gmail,
or populate the attachment cache. Bytes remain available only through the
existing explicit Preview and Download routes below. Every response, including
authentication, validation, and not-found responses, is `private, no-store`.
Public `/api/v1` tokens cannot call this route.

## Web session-only attachment preview and download

The authenticated web application, not the `/api/v1` token surface, exposes:

```text
GET /api/emails/{email_id}/attachments/{attachment_id}/download
GET /api/emails/{email_id}/attachments/{attachment_id}/preview
```

Both routes require the normal browser session cookie and verify the user,
owning account, email, and attachment with the same membership lookup. Missing,
foreign, and wrong-message attachment IDs all return the same 404 response.

Downloads always use attachment disposition, sanitized sender metadata,
private no-store caching, `nosniff`, and same-origin resource policy headers.
The browser treats active formats, archives, and filename/type mismatches as
confirmation-required downloads.

Previews do not trust sender-declared MIME data for rendering. The server
classifies the bytes into one of three bounded contracts: strict UTF-8 plain
text, metadata-stripped and dimension-bounded JPEG/PNG raster data, or a PDF
with a valid outer signature whose obvious active-feature markers are rejected. The response
uses inline disposition plus `X-Attachment-Preview-Kind` and
`X-Attachment-Preview-Truncated`; the client rejects any kind/content-type
mismatch. Text is rendered only as text, images use a revocable object URL, and
PDFs remain untrusted and open only in a separate browser-native viewer; the
marker check is not a malware scan or structural proof. Unsupported,
active, malformed, or corrupt content fails closed instead of falling back to
sender metadata.

Stable error responses are:

| status | meaning |
|--------|---------|
| 404 | attachment is missing or not owned by the current user |
| 409 | metadata exists but no retrievable content is available |
| 413 | attachment exceeds the interactive download size limit |
| 415 | attachment bytes are not supported by the safe preview contract |
| 502 | cached or upstream attachment data is invalid |
| 503 | Gmail retrieval failed or exceeded the interactive wait bound |

Public API tokens cannot call these routes. Attachment bytes are cached only at
private, canonical ID-derived paths; filenames and Gmail/cache identifiers are
not accepted as lookup keys.

## Web session-only Inbox triage preferences

These endpoints use the authenticated web session. They are not part of the
token-authenticated `/api/v1` surface.

### `GET /api/auth/ui-preferences`

Returns the current user's cross-device UI preferences with server defaults
filled in:

```json
{
  "thread_order": "newest_first",
  "theme": "amber",
  "color_scheme": "light",
  "swipe_left_action": "archive",
  "swipe_right_action": "snooze"
}
```

### `PUT /api/auth/ui-preferences`

Partially updates the same user-owned preference object. Swipe actions accept
only `archive`, `snooze`, `toggle_read`, `toggle_star`, or `none`; invalid
values fail with `422` without modifying the stored preferences. Omitted fields
retain their current values.

The web Inbox applies swipe preferences only to authoritative ordinary Inbox
conversation rows on a primary touch/coarse pointer. Trash, Spam, Move, and
other destructive/provider-routing actions are intentionally not valid swipe
choices. A snooze gesture opens the existing picker and performs no write until
the user explicitly chooses a return time. The client disables gestures when
the preference read or current Inbox dataset is not authoritative.

## Web session-only durable mail actions

Mailbox mutations use the authenticated browser session and a PostgreSQL
outbox. Acceptance means the local optimistic state and durable Gmail work were
committed together; it does not falsely claim that Gmail has already confirmed
every item.

```text
POST /api/emails/actions
GET  /api/emails/actions/recent?limit=20
GET  /api/emails/actions/by-idempotency/{idempotency_key}
GET  /api/emails/actions/{request_id}
POST /api/emails/actions/{request_id}/undo
POST /api/emails/actions/{request_id}/retry
```

Create accepts 1–200 unique, positive, fully owned email IDs. Mixed owned,
foreign, or missing targets return a uniform 404 and mutate nothing.

The current synchronized label catalog is available to authenticated browser
sessions at:

```text
GET /api/emails/labels/all?account_id=3
```

`account_id` is optional and, when present, is constrained to the current
user's connected accounts. Each result includes the local positive `id`,
`account_id`, `gmail_label_id`, display `name`, `label_type`, optional Gmail
colors, and synchronized total/unread counts. Interactive mutation surfaces
offer only `label_type=user`; Gmail system labels are never accepted as custom
label targets. A successful full label synchronization is authoritative for
that account, so local catalog rows that Gmail no longer returns are pruned.
Malformed or failed provider responses never trigger that pruning.

```json
{
  "email_ids": [9001, 9002],
  "action": "archive",
  "scope": "conversations",
  "idempotency_key": "e4544fb2-dddf-4323-8e28-fecede02cb72"
}
```

`scope` is additive and defaults to `messages`, preserving the original
payload and idempotency hash for existing clients. With
`scope=conversations`, every explicit owned anchor expands under PostgreSQL
locks to all current synchronized members of its exact account/thread; blank
thread IDs remain one-message conversations. The existing 200-message bound
applies after expansion. The original anchor IDs and scope are part of the
immutable idempotency identity, while `accepted_count`, optimistic state,
Undo, retry, and worker replay describe the expanded durable operation.

Supported actions are `mark_read`, `mark_unread`, `star`, `unstar`, `archive`,
`unarchive`, `trash`, `untrash`, `spam`, `unspam`, `add_label`, `remove_label`,
and `move_to_label`. `unarchive` is the internal ordered Inbox-return primitive
used by Snooze and is rejected for Trash or Spam. The three label actions
require a positive local `label_id`; every other action rejects `label_id`.
The chosen label and every explicit email anchor must belong to one owned Gmail
account, and the label must be a current user label with a non-empty provider
ID.

Label actions expand each explicit anchor to all locally synchronized messages
in the same owned Gmail conversation, with the same 200-message operation
bound. `accepted_count` can therefore exceed the number of submitted IDs.
`add_label` and `remove_label` apply the exact custom-label delta to those
existing messages. `move_to_label` is the Inbox-only "label and archive"
primitive: each explicit anchor must currently be in Inbox; every existing
conversation message gains the destination label and loses `INBOX` when it has
it. Sent or previously archived siblings do not invalidate an otherwise valid
Inbox move. The web client exposes Move only in the literal Inbox view; other
mailboxes retain the independent Label action.

The idempotency key is optional for legacy callers, but
retry-capable clients should generate one UUID per logical operation and reuse
it until a response is known. Reusing a key with the same payload returns the
original operation; reuse with a different payload returns 409. After a lost or
timed-out create response, the authenticated
`by-idempotency` route returns that exact owned operation or a uniform 404.
Because a lost POST can still be waiting on a database lock, that 404 is not a
definitive rejection: clients keep the projection visibly pending and replay
the same POST with the same key until POST itself returns a definitive result.
For label actions, the immutable payload identity includes the original sorted
email IDs and local `label_id`. Exact accepted replay is resolved before the
mutable label catalog or current mailbox state, so a lost-response recovery
still returns the original operation after Gmail synchronization or the
accepted Move itself changes that state.

Create returns HTTP 202:

```json
{
  "request_id": "7e05a7d6-0718-43c3-b220-d8168f85fe87",
  "idempotency_key": "e4544fb2-dddf-4323-8e28-fecede02cb72",
  "action": "archive",
  "state": "staged",
  "accepted_count": 2,
  "undo_until": "2026-08-30T12:00:10Z",
  "created_at": "2026-08-30T12:00:00Z",
  "items": [
    {
      "id": 41,
      "email_id": 9001,
      "account_id": 3,
      "gmail_message_id": "generated-example-id",
      "sequence": 1,
      "action": "archive",
      "state": "staged",
      "attempt_count": 0,
      "next_attempt_at": "2026-08-30T12:00:10Z",
      "error_code": null,
      "error_message": null,
      "applied_at": null,
      "failed_at": null,
      "cancelled_at": null
    }
  ]
}
```

Item states are `staged`, `processing`, `retry_wait`, `applied`, `failed`, and
`cancelled`. An operation containing different item states reports `partial` at
the top level. Error text is sanitized; callers should use `error_code` for
behavior and present the supplied generic message.

Undo is all-or-none and restores the exact saved labels and flags only while
every item remains staged and within its ten-second deadline. Once any item has
started, Undo returns 409 rather than pretending to reverse an uncertain Gmail
result. Retry requeues only terminally failed items and returns 409 when a newer
action exists for one of them.

The database sweeper reclaims expired worker leases and processes the oldest
active sequence for each email. Redis only accelerates pickup; periodic cron
draining guarantees recovery if enqueueing or a process fails. Redis enqueue
and status publication have a short hard deadline, so a stalled Redis service
cannot hold an API response or the account-locked Gmail worker after the
durable database commit. One-attempt Gmail mutations use a finite HTTP
transport timeout and then enter the durable retry policy.
Each cron job and account-lock tenure processes at most eight actions, keeping
the worst-case Gmail transport slice well below the worker timeout; later work
is picked up by the next durable cron pass.

`GET /actions/recent` remains bounded by `limit` (1–100) but prioritizes
operations with unresolved failed items before newer completed operations, so
a failure does not silently disappear behind routine successes. Public API
tokens cannot call these mutation routes.

## Web session-only durable Snooze reminders

Universal Snooze uses the authenticated browser session and is scoped to one
exact owned Google account and Gmail conversation. Public API tokens cannot
call these routes.

```text
POST  /api/snoozes
GET   /api/snoozes?state=active&limit=50&offset=0
GET   /api/snoozes/by-idempotency/{idempotency_key}
GET   /api/snoozes/{snooze_id}
PATCH /api/snoozes/{snooze_id}/reschedule
POST  /api/snoozes/{snooze_id}/cancel
POST  /api/snoozes/{snooze_id}/return-now
```

Create requires one owned positive email ID, a future offset-aware instant,
the originating IANA time zone, one condition, and a client UUID:

```json
{
  "email_id": 9001,
  "wake_at": "2026-08-31T13:00:00Z",
  "time_zone": "America/New_York",
  "condition": "if_no_reply",
  "idempotency_key": "42a7cd5b-d5de-4d42-8a2c-1a80116b1607"
}
```

`condition` is `always` or `if_no_reply`. Replaying the same idempotency key and
canonical payload returns the original reminder even after its wake time;
reusing the key for a different payload returns 409. The owned-key lookup is
the recovery path after a lost create response.

The lifecycle is conversation-scoped by `(user, account, gmail_thread_id)`.
Only one active reminder may exist for that tuple. Current eligible Inbox
members archive together through the durable mail-action outbox, and the
response identifies both the representative row and conversation scope:

```json
{
  "id": "2e7f88e3-d532-48c0-91e6-7ec16174f79e",
  "email_id": 9001,
  "account_id": 3,
  "account_email": "you@example.test",
  "gmail_thread_id": "generated-thread-id",
  "wake_at": "2026-08-31T13:00:00Z",
  "time_zone": "America/New_York",
  "condition": "if_no_reply",
  "state": "pending_archive",
  "status_detail": "archiving",
  "archive_required": true,
  "originally_in_inbox": true,
  "conversation_message_count": 2,
  "archive_action_request_id": "d4cda482-261b-42e4-98ea-983f99b36768",
  "archive_undo_until": "2026-08-30T12:00:10Z",
  "error_code": null,
  "error_message": null,
  "email": { "id": 9001, "subject": "Generated example" }
}
```

Active states are `pending_archive`, `scheduled`, and `pending_return`;
terminal states are `returned`, `cancelled`, `dismissed`, and `failed`. Lists
are bounded to 200 items and may request `active`, `scheduled`, `returned`,
`cancelled`, `failed`, or `all`.

Cancel is idempotent and restores the conversation's original Inbox placement.
Return now and the scheduled wake add Inbox, including for a reminder created
from Sent or All Mail. Trash, Spam, and messages with a newer manual placement
are never overridden. Reschedule accepts a future offset-aware `wake_at` and an
IANA `time_zone` for an active reminder.

For `if_no_reply`, the worker first requires a successful account sync
checkpoint at or after wake, then suppresses return if a later non-sent inbound
message exists in the exact account/thread. PostgreSQL is authoritative;
Redis is wake-up acceleration and the minutely cron drain recovers lost wakes
and expired leases. Snooze return actions enter the same ordered mail-action
sequence as direct user actions, so later manual placement wins.

Automatic follow-up Snoozes additionally return
`origin="automatic_follow_up"` and their safe originating outbound identifier.
They never archive or otherwise remove a synchronized Inbox conversation. A
manual Snooze or newer manual placement always wins.

## Web session-only automatic follow-up reminders

Automatic follow-ups are an authenticated, per-account writing preference and
delivery-confirmed reminder workflow. Public API tokens cannot read or mutate
these routes.

```text
GET /api/follow-up/policies
PUT /api/follow-up/policies/{account_id}
```

`GET` returns every active connected account. An account with no saved row is
represented by a safe default-off revision-zero policy. `PUT` is a complete,
revision-checked replacement:

```json
{
  "expected_revision": 0,
  "enabled": true,
  "delay_days": 5,
  "wake_local_time": "09:00",
  "time_zone": "America/New_York",
  "weekdays_only": true
}
```

Delay is 1–30 days, local time is strict 24-hour `HH:MM`, and `time_zone` must
be an IANA zone. A stale revision returns 409
`follow_up_policy_conflict`; missing, inactive, and foreign accounts share the
same non-disclosing 404. Exact replacement replay is safe.

Compose, reader reply, and Flow include these fields in both durable draft and
send payloads:

```json
{
  "follow_up_reminder": "default",
  "follow_up_time_zone": "America/New_York"
}
```

`follow_up_reminder` is `default`, `enabled`, or `disabled`. `default` resolves
the selected account policy once at immutable send admission; changing the
policy later cannot rewrite an accepted message. Explicit enable requires at
least one external To or Cc recipient. Self-only and Bcc-only sends fail
admission instead of silently discarding the user's request.

The server creates a content-free companion intent in the same PostgreSQL
transaction as the outbound message. It does not schedule a reminder from an
HTTP 202, undo window, scheduled time, worker attempt, or unconfirmed provider
response. After provider-confirmed delivery, it reconciles the exact
synchronized Sent row by provider message ID and unique RFC Message-ID, uses
the synchronized delivery timestamp, applies the saved local time/business-day
rule with explicit DST handling, then creates one `if_no_reply` automatic
Snooze. Identifier disagreement fails closed.

Undo, scheduled cancellation, terminal delivery failure, retry authorization,
retry expiry, and send-now update the same intent transactionally. Redis only
accelerates work; the periodic database drainer recovers expired leases and
lost enqueueing. Reply detection requires a successful sync checkpoint at or
after wake. No tracking pixel, read receipt, remote image, or message-content
copy is used.

## Web session-only per-account signatures

Signatures are authenticated, owner-scoped writing preferences. Public API
tokens cannot read or mutate these routes.

```text
GET /api/compose/signatures
PUT /api/compose/signatures/{account_id}
```

`GET` returns every active connected account. An account without a saved row is
represented by a disabled revision-zero default. `PUT` is a complete,
revision-checked replacement:

```json
{
  "expected_revision": 0,
  "enabled": true,
  "include_on_new": true,
  "include_on_replies": true,
  "include_on_forwards": true,
  "body_html": "<p><strong>Generated Sender</strong><br>Example team</p>",
  "body_text": "Generated Sender\nExample team"
}
```

Missing, inactive, and foreign accounts share the same non-disclosing 404.
Exact replacement replay is safe; a stale revision returns 409
`signature_policy_conflict`. Rich content is bounded, sanitized through the
pinned server sanitizer, and returned with a `sanitizer_version`. Active
content, event handlers, inline styles, remote images, and unsafe protocols are
removed. An enabled policy requires coherent rich and plain content and at
least one selected message type.

Compose, reader reply, and Flow include these fields in durable draft and send
payloads:

```json
{
  "composition_kind": "reply",
  "signature_mode": "default",
  "quoted_html": "<blockquote>Earlier generated message</blockquote>",
  "quoted_text": "Earlier generated message"
}
```

`composition_kind` is `new`, `reply`, or `forward`; it cannot change after a
draft is created. `signature_mode` is `default`, `enabled`, or `disabled`.
Quoted forward history is a separate bounded field, not editable authored
body content.

The server freezes one sanitized `signature_snapshot` when a new durable draft
or unlinked send first establishes its writing intent. The snapshot records the
exact account, policy revision, sanitizer version, content hash, content, and
whether it is applied. Linked sends copy their draft snapshot exactly. A later
settings edit cannot rewrite a draft, retry, scheduled send, or accepted
outbound message. Legacy drafts with no snapshot remain unsigned instead of
acquiring a new policy on reopen.

The provider renderer assembles the transient send body exactly once in this
order: authored body, frozen signature when applied, then structured quoted
history. Persisted authored body is never rewritten with signature markup.
Remove and Restore only change the applied state of the frozen sidecar; they do
not re-read live settings or duplicate content. Rendered output is size-checked
before any Gmail call. Signature policy load failure visibly blocks Send until
Retry succeeds or the user explicitly continues unsigned.

Full draft-detail and draft-save responses may return the frozen snapshot so a
mounted writer can reconcile its authoritative state. Recent-draft lists omit
signature content. Logs, generated QA audit records, and companion lifecycle
state retain only safe identifiers, revisions, counts, and hashes.

## Web session-only recipient suggestions

Compose recipient suggestions are private projections of already-synchronized
message metadata. Public API tokens cannot access them.

```text
GET /api/compose/recipients?account_id=3&q=ada&limit=8
```

The account must be active and owned by the current user; missing, inactive,
and foreign account identifiers share the same non-disclosing 404 response.
`q` is optional and limited to 254 characters. `limit` defaults to 8 and is
bounded from 1 through 20.

```json
{
  "suggestions": [
    {
      "name": "Lovelace, Ada",
      "address": "ada.correspondent@example.test",
      "formatted": "\"Lovelace, Ada\" <ada.correspondent@example.test>"
    }
  ]
}
```

The service reads one recent, date-ordered corpus capped at 4,000 rows for the
selected account. It excludes drafts, Spam, Trash, every address owned by the
signed-in user, and correspondents visible only in another account. Results are
normalized and deduplicated case-insensitively, then rank exact/prefix matches,
prior outgoing correspondence, recency, and frequency. The response contains
only display-name and mailbox metadata; it never returns subject or body
content and does not call Google Contacts or another provider.

The browser commits only canonical recipient chips to durable drafts and send
requests. Unfinished input remains local, is not autosaved, and blocks sender
changes, draft save, navigation, and every Send path until the user commits or
removes it.

## Web session-only Contact profiles

Contact profiles are private, read-only projections of already-synchronized
message metadata. They do not request Google Contacts access, call a provider,
or create an address-book record. Public API tokens cannot access them.

```text
POST /api/contacts/query
POST /api/contacts/profile
```

Both endpoints require an active account owned by the authenticated user.
Missing, inactive, and foreign accounts share the same non-disclosing 404
response. Requests are POST-only so search text and opaque contact keys do not
enter browser history, proxy query logs, or referrer URLs. Responses use
`Cache-Control: private, no-store`.

Query accepts an exact `account_id`, optional name/address `query`, one of
`all`, `bidirectional`, `inbound_only`, or `outbound_only`, and bounded page
controls. The projection scans at most the newest 4,000 eligible metadata rows
from that account, excluding Draft, Spam, Trash, Bcc-only correspondents, and
every mailbox owned by the signed-in user. It returns normalized name/address,
an opaque HMAC-derived `contact_key`, relationship direction, observed message
and conversation counts, observed first/last timestamps, and explicit corpus
coverage. Subject, snippet, body, Bcc, labels, attachments, AI output, and raw
headers are never returned.

Profile accepts the same exact account plus one opaque `contact_key` and a
`recent_limit` from 1 through 20. It returns the same metadata summary and
content-free recent conversation pointers:

```json
{
  "account_id": 3,
  "contact": {
    "account_id": 3,
    "contact_key": "<opaque 64-character key>",
    "name": "Lovelace, Ada",
    "address": "ada.correspondent@example.test",
    "formatted": "\"Lovelace, Ada\" <ada.correspondent@example.test>",
    "relationship": "bidirectional",
    "observed_message_count": 4,
    "observed_received_count": 2,
    "observed_sent_count": 2,
    "observed_conversation_count": 1,
    "observed_first_at": "2026-08-28T15:57:00Z",
    "observed_last_at": "2026-08-30T15:59:00Z",
    "observed_last_received_at": "2026-08-30T15:59:00Z",
    "observed_last_sent_at": "2026-08-30T15:57:00Z"
  },
  "recent_conversations": [
    {
      "account_id": 3,
      "anchor_email_id": 1401,
      "thread_id": "provider-thread-id",
      "observed_last_at": "2026-08-30T15:59:00Z",
      "observed_message_count": 4,
      "direction": "bidirectional"
    }
  ]
}
```

The browser treats both response types as untrusted: it rejects mixed-account,
malformed, duplicate, or mismatched identities. Email starts one new Compose
intent with the exact account and one canonical To recipient. Opening a recent
conversation carries only the exact account, anchor, and thread pointer in
session memory, then loads that account-owned thread after Inbox authority is
ready. The handoff is cleared on every authenticated-session transition.

## Web session-only Personal Snippets

Personal Snippets are private reusable writing blocks owned by the authenticated
user. Public API tokens cannot list or mutate them.

```text
GET    /api/compose/snippets
POST   /api/compose/snippets
PUT    /api/compose/snippets/{snippet_id}
DELETE /api/compose/snippets/{snippet_id}?expected_revision=3
```

Create uses a client-generated UUID as the stable identity for one logical
request:

```json
{
  "snippet_id": "71ea1d53-9fbc-4683-83ba-c0b5b876d755",
  "name": "Generated follow-up",
  "shortcut": "follow_up",
  "body_html": "<p>Generated fixture content</p>",
  "body_text": "Generated fixture content"
}
```

Names are normalized to 1–120 characters. Shortcuts are case-folded, may omit
or include a leading semicolon at admission, and persist as 1–32 lowercase
letters, numbers, hyphens, or underscores. They are unique per user. Plain text
is limited to 20,000 characters, HTML to 50,000 characters, the complete
request to 128 KiB, and each user to 250 snippets.

An exact create replay with the same UUID and canonical content returns the
existing record with 200; the first create returns 201. Reusing the UUID for
different content, reusing a shortcut, or replacing a stale revision returns
409 `snippet_conflict`. Replace is a full revisioned update:

```json
{
  "expected_revision": 3,
  "name": "Generated follow-up",
  "shortcut": "follow_up",
  "body_html": "<p>Updated generated content</p>",
  "body_text": "Updated generated content"
}
```

An exact lost-response update replay is safe. Delete requires the current
positive revision and is idempotent after success; missing and foreign UUIDs
share the same non-disclosing behavior. List results are bounded, sorted by
name, and contain only the current user's records. Snippet HTML is sanitized at
every insertion boundary; plain-text surfaces insert the stored plain fallback.
Insertion materializes a copy into the draft, so later snippet edits or deletion
never rewrite an existing draft.

Compose, reader reply, and Flow also provide client-side inline expansion.
Typing a leading or whitespace-delimited `;shortcut` opens a fresh
authenticated list for the current editor activation; the client never
auto-replaces from an asynchronous response. Enter, Tab, or explicit pointer
selection revalidates the current session and exact live trigger range before
materializing the sanitized rich snapshot or stored plain-text fallback in one
Undo transaction. Escape, movement, loading, empty, error, and stale-session
states preserve the literal text. Browsers that cannot provide an undoable
compatibility transaction retain the existing `Cmd/Ctrl+;` picker instead.

## Web session-only durable outbound delivery

Interactive email sends use the authenticated browser session and a
PostgreSQL outbox. HTTP 202 means the server durably owns the logical send; it
does not mean Gmail has confirmed delivery.

```text
POST /api/compose/send
GET  /api/compose/sends/scheduled?limit=60
GET  /api/compose/sends/recent?limit=20
GET  /api/compose/sends/by-idempotency/{idempotency_key}
GET  /api/compose/sends/{send_id}
POST /api/compose/sends/{send_id}/cancel
POST /api/compose/sends/{send_id}/send-now
POST /api/compose/sends/{send_id}/undo
POST /api/compose/sends/{send_id}/retry
```

Create requires one client-generated UUID for one immutable logical payload:

```json
{
  "idempotency_key": "a48e819f-1bd6-4bf6-b2bc-b81e7300f226",
  "account_id": 3,
  "to": ["recipient@example.test"],
  "cc": [],
  "bcc": [],
  "subject": "Generated example",
  "body_text": "Generated fixture content",
  "body_html": "<p>Generated fixture content</p>",
  "client_draft_id": "ca309a94-c45d-430c-a707-af10376124b1",
  "draft_revision": 7,
  "scheduled_for": "2026-08-31T13:00:00Z",
  "schedule_timezone": "America/New_York",
  "archive_source_after_send": false,
  "follow_up_reminder": "default",
  "follow_up_time_zone": "America/New_York",
  "source_email_id": null,
  "in_reply_to": null,
  "references": null,
  "thread_id": null,
  "attachments": []
}
```

Omit `scheduled_for` for an immediate send. A scheduled send must be at least
60 seconds and at most 365 days in the future, must include a valid IANA
`schedule_timezone`, and must link the exact current durable draft revision.
The server stores the instant in UTC; the timezone is presentation context for
the browser and does not alter the delivery instant. Ambiguous fall-back local
times are shown as two explicit offset choices, while nonexistent spring-forward
times are rejected before admission.

The account must be active and owned by the current user. A message requires a
To recipient; the server accepts at most 100 unique RFC mailboxes, ten
attachments, 18 MiB of decoded attachment bytes, and bounded headers/bodies.
Header newlines, invalid base64, duplicates across To/Cc/Bcc, foreign accounts,
and inactive accounts fail before persistence. A pure-ASGI guard rejects a
declared or streamed request body above 50 MiB with 413 before FastAPI parses
the message JSON.

Flow, full Compose replies, and inline reader replies may set
`archive_source_after_send=true` only with an exact validated
`source_email_id`. New messages and ordinary Send omit the flag. The outbound
worker durably stages one deterministic, conversation-scoped archive action
after provider delivery is confirmed and before publishing terminal `sent`
truth. Reconciliation repeats that same idempotent action if a process stops
between those commits. Undo, scheduled cancellation, and delivery failure leave
the conversation in place; if sync removed the exact source before delivery,
the confirmed send completes and the archive becomes a safe no-op.

Outbound responses expose `archive_source_after_send` as a safe boolean only
while the retained intent still has an exact positive source identity. This
allows scheduled-send management to describe the pending follow-up without
returning the outbound payload or message content.

Outbound responses also expose `follow_up_requested` as a safe boolean. It
reports the immutable admission result, not the current account preference.

Admission is serialized transactionally per user. At most 30 active sends may
consume one account's capacity and 60 may consume one user's capacity; the
rolling 60-second acceptance limits are 20 per account and 40 per user.
Same-key/same-payload idempotent lookups do not consume another quota slot.
Quota rejection returns 429 `outbound_rate_limited` with `Retry-After`.

A reply with `thread_id`, `in_reply_to`, or `references` must include a
positive `source_email_id`. The source must belong to the same owned account,
and its Gmail thread, Message-ID, and complete References chain must exactly
match the request. Missing and foreign reply sources share a non-disclosing
404.

Reusing an idempotency key with the same canonical payload returns the original
operation with 202. Reusing it for different content returns 409. After a lost
create response, the browser looks up the owned key and may replay only the
same payload with the same key; it never creates a replacement key for that
logical send.

```json
{
  "send_id": "f9801543-45a0-4304-8373-410e6db85438",
  "idempotency_key": "a48e819f-1bd6-4bf6-b2bc-b81e7300f226",
  "account_id": 3,
  "source_email_id": null,
  "client_draft_id": "ca309a94-c45d-430c-a707-af10376124b1",
  "state": "staged",
  "execute_after": "2026-08-31T13:00:00Z",
  "undo_until": "2026-08-30T12:00:10Z",
  "next_attempt_at": "2026-08-31T13:00:00Z",
  "scheduled_for": "2026-08-31T13:00:00Z",
  "schedule_timezone": "America/New_York",
  "attempt_count": 0,
  "max_attempts": 8,
  "can_undo": false,
  "can_cancel": true,
  "can_send_now": true,
  "can_retry": false,
  "provider_message_id": null,
  "error_code": null,
  "error_message": null,
  "created_at": "2026-08-30T12:00:00Z",
  "updated_at": "2026-08-30T12:00:00Z",
  "sent_at": null,
  "failed_at": null,
  "cancelled_at": null
}
```

States are `staged`, `processing`, `retry_wait`, `reconciling`, `sent`,
`failed`, and `cancelled`. Undo succeeds only while the operation remains
staged and the server's ten-second deadline is open; otherwise it returns 409.
For a scheduled operation, the same ten-second Undo window protects admission,
then `cancel` remains authoritative until a worker owns the due send. Cancel is
idempotent, scrubs the outbox payload, and restores the linked durable draft.
`send-now` advances a cancellable scheduled operation to the durable delivery
queue; it never bypasses the normal provider preflight, Message-ID lookup, or
ambiguity policy. The bounded `scheduled` list returns only active future
operations, ordered by delivery time, so browsers can restore the manager after
reload or on another device.
`can_retry` is authoritative. A failure after any possible Gmail attempt is
never retryable. A rare pre-provider failure may expose `can_retry=true` for an
internal one-hour recovery window; the deadline itself is deliberately not
included in the response. After it expires, `can_retry=false` and admission or
the minute cron sweep removes the retained payload. A persistence failure while
accepting work returns safe 503 `outbound_unavailable` with `Retry-After: 5`;
database parameters and raw exception text are not exposed.

Before Gmail delivery, the worker searches Sent by one stable RFC Message-ID.
It then durably records the provider-attempt boundary before executing exactly
one Gmail send request. A response, timeout, worker interruption, or lease loss
after that boundary which cannot prove the Gmail result enters `reconciling`.
Reconciliation performs only Sent lookups; it never replays the message.
Expired pre-attempt work may follow bounded retry policy. Redis only wakes the
drainer; PostgreSQL and the periodic cron sweep provide recovery. Future work
uses an exact deferred wake time rather than frequent status polling; the
browser uses sparse list recovery and delays per-operation reads while a
schedule is far away.

`client_draft_id` and `draft_revision` are optional only as a pair. When
present, they must identify the current user's exact durable draft revision;
admission links that immutable revision to this send. The browser keeps its
auth-scoped IndexedDB snapshot until terminal truth: `sent` deletes it, while
`failed` or `cancelled` converts it to a new Compose identity before removing
the send-owned copy. This recovery authority does not weaken server-side
payload scrubbing.

Status responses contain lifecycle metadata only—never recipients, subject,
body, or attachments. Provider errors are reduced to safe codes and copy.
Payload content is removed after `sent`, `cancelled`, every non-retryable
failure, or expiration of the bounded pre-provider retry window. Public API
tokens cannot call these mutation routes.

## Web session-only durable draft sessions

Full Compose uses a user- and account-owned PostgreSQL draft session rather
than treating a successful Gmail request as the first durable save. HTTP 202
means the exact revision and attachment bytes are committed locally and owned
by the server; only `state: "synced"` means Gmail has confirmed the provider
draft.

```text
POST /api/compose/draft
GET  /api/compose/drafts/recent?limit=20
GET  /api/compose/drafts/by-client-id/{client_draft_id}
GET  /api/compose/drafts/by-source-email/{source_email_id}?account_id=3
GET  /api/compose/drafts/by-email/{email_id}
POST /api/compose/drafts/{client_draft_id}/discard
POST /api/compose/drafts/{client_draft_id}/undo-discard
```

Each writing intent receives one client UUID. Every changed snapshot advances
its positive revision and receives a new mutation UUID:

```json
{
  "client_draft_id": "ca309a94-c45d-430c-a707-af10376124b1",
  "revision": 7,
  "mutation_id": "7461b86c-2f33-41dc-9a30-d183d94cfa87",
  "account_id": 3,
  "to": ["recipient@example.test"],
  "cc": [],
  "bcc": [],
  "subject": "Generated example",
  "body_text": "Generated fixture content",
  "body_html": "<p>Generated fixture content</p>",
  "source_email_id": null,
  "in_reply_to": null,
  "references": null,
  "thread_id": null,
  "attachments": []
}
```

The account must be active and owned by the current user. Recipient, header,
body, attachment-count, decoded-byte, and streamed-body limits match Compose
send. Reply metadata additionally requires an exact owned source message,
account, Gmail thread, Message-ID, and References chain. Foreign, missing, or
mismatched sources use the same non-disclosing 404.

The same mutation and canonical payload is an idempotent lookup. A reused
mutation for different content, a changed payload at an existing revision, or
a stale revision returns 409 `draft_conflict`. PostgreSQL serializes admission
per user and enforces active-draft, recent-mutation, and retained-byte quotas;
quota failures return 429 `draft_rate_limited` with `Retry-After`. Persistence
failure returns safe 503 `draft_unavailable` with `Retry-After: 5`.

```json
{
  "client_draft_id": "ca309a94-c45d-430c-a707-af10376124b1",
  "account_id": 3,
  "source_email_id": null,
  "revision": 7,
  "synced_revision": 7,
  "state": "synced",
  "next_attempt_at": null,
  "attempt_count": 1,
  "can_undo_discard": false,
  "discard_at": null,
  "discard_undo_until": null,
  "linked_send_id": null,
  "error_code": null,
  "error_message": null,
  "attachment_count": 0,
  "attachment_bytes": 0,
  "created_at": "2026-08-30T12:00:00Z",
  "updated_at": "2026-08-30T12:00:02Z",
  "synced_at": "2026-08-30T12:00:02Z",
  "discarded_at": null
}
```

States are `pending`, `syncing`, `reconciling`, `synced`, `failed`,
`discard_pending`, `discarded`, and `sending`. The detail lookups also return
the owned content and attachment bytes needed to reopen a draft. Recent list
responses remain metadata-only and are loaded without recipient, subject, body,
provider identifier, reply-header, or attachment-byte columns. The
`by-source-email` lookup requires the exact owned account and source message;
it returns the one active reply session for that source or a non-disclosing
404. A legacy duplicate returns 409 rather than choosing content silently.
Concurrent first saves with different client UUIDs converge on the source
winner: the losing create returns 409 `draft_source_exists`, and the browser
then resolves the exact owned-source session instead of creating a second Gmail
draft. `by-email` resolves only a provider draft that this application manages
for the current user; a foreign or externally created Gmail draft remains
read-only and returns the same safe 404.

Reader, Flow, and full Compose replies share the stable intent
`reply:{account_id}:{source_email_id}`. The authenticated browser first checks
its owner-scoped IndexedDB record, then uses `by-source-email` for cross-device
discovery. Every editor update is written locally before remote debounce. A
session or account transition invalidates an in-flight open before either
browser storage or UI can accept its result. Navigation is blocked while local
storage has failed, discard is pending, or send reconciliation owns the reply.
Reply-to-Reply-All changes rebase only the verified recipient envelope while
preserving the saved body and attachment state. Sending, discard-pending,
discarded, or conflicted source winners never replace an unrelated local UUID.

The worker assigns one stable RFC Message-ID before provider work. It attempts
the initial Gmail draft create at most once. If that result is ambiguous, the
session enters `reconciling` and performs lookup-only recovery; it never issues
a blind second create. Confirmed drafts use Gmail update semantics for later
revisions. Redis only wakes the drainer; PostgreSQL leases and the minutely cron
sweep are the recovery authority.

Discard is server-authoritative and starts a ten-second Undo window. Undo uses
a distinct mutation UUID and succeeds only while the server still reports
`can_undo_discard`. As soon as that authoritative window expires, the database
scrubs recipients, bodies, and attachment bytes before any provider delete or
reconciliation work. A content-free tombstone retains only the identities and
state needed to finish safe provider reconciliation without claiming success.
A send may link only the exact owned draft UUID and revision; the worker cleans
up the matching provider draft after the authoritative Undo deadline, even
while outbound delivery is still retrying or reconciling. The browser-owned
recovery snapshot remains available until terminal delivery truth. Public API
tokens cannot call any draft mutation or detail route.

## Web session-only Todo ownership

Todos use the authenticated browser session and are always scoped to its user.
Public API tokens cannot call these routes.

```text
GET    /api/todos/?status=pending&page=1&page_size=50
POST   /api/todos/
POST   /api/todos/from-email/{email_id}
PATCH  /api/todos/{todo_id}
DELETE /api/todos/{todo_id}
```

The generic create route creates only manual Todos. `title` is trimmed and
must contain 1–500 characters; `email_id`, when supplied, must be a positive
ID for an email owned through one of the current user's Google accounts.
`source` may only be `manual`, and unknown request fields are rejected.

```json
{
  "title": "Follow up next week",
  "email_id": 9001,
  "source": "manual"
}
```

AI-derived Todos can be created only through `POST /from-email/{email_id}`.
That route resolves the analysis through the owned Email and Google Account,
then accepts only non-empty string action items, bounds titles to 500
characters, and avoids duplicates for that email. A foreign email, a missing
email, and an owned email without an analysis all return the same 404
`{"detail":"Email not found"}` response, avoiding an ownership or analysis
existence oracle.

List, update, and delete routes filter by the current user. Updates accept only
`title` and the statuses `pending`, `done`, or `dismissed`. PostgreSQL also
enforces the Todo-to-email ownership relationship on inserts and relevant
updates, so a future caller cannot bypass the router invariant.

Migration `c0d1e2f3a4b5` removes historical AI-derived rows linked across user
boundaries because their titles may contain source-email content. It preserves
user-authored manual titles by detaching the invalid email and clearing any
derived reply-draft fields. Downgrade removes the trigger but intentionally
does not recreate unsafe links or purged content; restoring those rows requires
the validated pre-migration backup.

## At a Glance displays and terminal management

At a Glance has two delivery adapters backed by the same view/design catalog:
pre-quantized BMP files for e-ink firmware and fullscreen browser pages for
ordinary landscape or portrait displays. These routes do not use `/api/v1`
tokens. Firmware retains its opaque per-user terminal `code`. Each browser
display instead has a separate high-entropy credential bound server-side to
one view/design/profile, so a leaked Clock URL cannot be changed into a Day
Ahead URL. All of these URLs should still be handled like private unlisted
links.

```text
GET /terminal/{code}/schedule.json
GET /terminal/{code}/image.bmp
GET /terminal/display/{token}.html
GET /terminal/display/{token}/frame.png
```

The firmware endpoints retain the version-1 schedule and BMP contracts in
[`docs/terminal/server-protocol.md`](terminal/server-protocol.md). Both the BMP
and PNG frame endpoints return stable `ETag` values and honor
`If-None-Match`; clients should revalidate rather than append cache-busting
query values.

`display.html` is a no-store fullscreen shell. It refreshes the canonical PNG
frame on a bounded cadence. View, design, and profile are bound to the token;
the public URL cannot override them. It accepts only:

| param | values | default |
|-------|--------|---------|
| `refresh` | 30–3600 seconds (values are clamped) | 300 |

Current layout contracts keep the Home Dashboard on 16:9, provide Day Ahead
as exact registered 16:9 and 9:16 compositions, and support both profiles for
the Clock. The 16:9 Day Ahead adapter is the native 800×480 E1002 layout; it is
not a resized portrait frame. PNG responses are marked private and must be
revalidated by clients.

The authenticated Settings UI uses the normal browser-session API:

```text
GET    /api/terminal/experience
GET    /api/terminal/experience/preview.png?view={view}&design={design}&profile={profile}
GET    /api/terminal/settings
GET    /api/terminal/devices
PATCH  /api/terminal/devices/{device_id}
DELETE /api/terminal/devices/{device_id}
POST   /api/terminal/displays/{display_id}/regenerate
POST   /api/terminal/devices/{device_id}/ota/attempts
GET    /api/terminal/devices/{device_id}/ota/attempts
GET    /api/terminal/ota/attempts/{attempt_id}
POST   /api/terminal/ota/attempts/{attempt_id}/cancel
```

`GET /api/terminal/experience` is the read-only contract for the first-class
At a Glance page. It returns `{views, designs, display_profiles, combinations,
devices}`. `combinations` contains only catalog metadata (`key`, `label`,
`view`, `design`, `profile`, `orientation`, and `aspect_ratio`); the response
contains no shared terminal code, browser display token or URL, Home Assistant
value, or credential-minting side effect. `devices` uses the same owner-scoped
summaries and battery-health shape as `GET /api/terminal/devices`.

The authenticated preview endpoint accepts only a catalog-compatible
view/design/profile combination and returns the canonical 16:9 or 9:16 web
frame as a private, no-store PNG. Unknown views or profiles and incompatible
combinations return `400`. It does not expose or create a public display URL;
scoped display-link management remains in Settings.

`GET /api/terminal/settings` now includes the shared `views`, `designs`,
`display_profiles`, and ready-to-open `web_displays` catalogs in addition to
the existing firmware variants. Regenerating the terminal code immediately
invalidates old firmware URLs without disrupting browser displays. Regenerating
one browser display rotates only that credential and immediately invalidates
its old URL.

`PATCH /api/terminal/devices/{device_id}` accepts an additive
`hardware_revision` field. Supplying or clearing that field is an explicit
owner confirmation: it requires the normal browser-session cookie plus the
same-origin mutation boundary and is rejected while the device has an active
OTA attempt. The value is never inferred from USB descriptors, model names, or
firmware self-reporting.

Each device response includes additive `battery_health` data. The server stores
sparse samples on meaningful percentage/voltage changes plus a six-hour
heartbeat, with a five-minute ingestion floor and 90-day retention. It
estimates discharge only after at least three percentage samples spanning 12
hours with a measurable, directionally consistent drop. Six-hour medians and a
bounded robust slope reduce ADC spikes and oscillation; inconsistent or
greater-than-one-year projections remain `null`. Percentage freshness follows
the latest percentage-bearing sample, so a newer voltage-only check-in cannot
make stale percentage data look current. Prediction fields include rate,
estimated days remaining, expected charge-threshold time, confidence, status,
and a human-readable notice. Because firmware does not report an
external-power signal, a corroborated rise resets the discharge segment but is
described only as `possible_charging`; the API never claims active charging
from inferred voltage rise. Low-charge notices always take precedence.

Firmware candidate.5 adds a bounded seven-sample battery burst and sends its
median, spread, sample count, and explicit quality result. When
`X-Battery-Valid: 0` is present, the server ignores that percentage and voltage
instead of adding misleading data to the predictor. Older firmware without the
quality header retains the existing range-bounded ingestion behavior.

Candidate.5 also emits exact RET1 status version 2 with read-only partition,
boot-state, and source-build identity. The enrollment API continues accepting
the exact candidate.4 status-v1 shape; the authenticated RET1 handshake remains
version 1. A status-v1 terminal has no runtime identity evidence and must not be
treated as a verified recovery boot.

### Authenticated firmware catalog and artifacts

Firmware release inspection uses the normal authenticated browser session.
Public API tokens and anonymous callers cannot use these routes:

```text
GET /api/terminal/firmware/catalog
GET /api/terminal/firmware/ota/capabilities
GET /api/terminal/firmware/releases/{release_id}/manifest.json
GET /api/terminal/firmware/releases/{release_id}/manifest.sig
GET /api/terminal/firmware/releases/{release_id}/models/{model}/artifacts/{role}
```

The catalog endpoint returns at most one approved release. Each response is
rebuilt from a detached-signature-verified catalog and a fully verified,
content-addressed bundle on local storage. The service checks the exact release
manifest schema, signing key, every listed hash and byte length, partition CSV
and binary table, factory image composition, hardware-revision allowlist,
model/panel/layout identity, and the NVS/LittleFS ranges that a normal install
must preserve. E1004 remains ineligible.

Catalog responses contain `schema_version`, `installer_state`,
`browser_flash_enabled`, `trusted_key_ids`, `blockers`, and `releases`. A model
record may include artifact download URLs only when the server enablement flag,
positive minimum signed-catalog generation, signed release evidence, explicit
hardware qualification, and model policy all agree. The browser applies a
second exact-schema and flash-range audit before presenting metadata.

The browser now fetches the exact manifest and detached signature bytes for a
second, independent SHA-256/Ed25519 verification against a source-pinned public
key map, strict duplicate-free JSON, the authenticated catalog, the pinned
toolchain, and exact model/partition contracts. The production browser key map
is intentionally empty, so this preflight remains locked until a reviewed key
is shipped in application source. It fetches no firmware artifact bytes.

`GET /api/terminal/firmware/ota/capabilities` is an authenticated, read-only
status surface. It reports the independent server enablement, exact HIL
allowlist, positive catalog-generation, signed parent/model eligibility, and
durable idempotent event-store blockers. The event store is now installed, but
production still defaults to disabled with an empty HIL map and zero-percent
rollout. No release is considered offerable merely because persistence exists;
the exact descriptor, parent bundle, signing key, model, printed hardware
revision, HIL evidence, catalog generation, power reserve, deterministic
cohort, and enablement gates must all agree.

Creating an owner OTA attempt is idempotent by `client_request_id` and exact
request fingerprint. It snapshots the verified release and current device
identity, active credential generation, running build/slot/boot count, fresh
power evidence, rollout percentage, and cohort bucket. Only an unstarted offer
may be cancelled. Reads are owner-scoped and never return the raw device
credential or credential-bearing artifact URLs.

An active enrolled terminal credential extends the secure schedule contract
with an optional `firmware` object and content-addressed device routes:

```text
GET  /terminal/device/{public_id}/{credential}/schedule.json
GET  /terminal/device/{public_id}/{credential}/firmware/{release_id}/manifest.json
GET  /terminal/device/{public_id}/{credential}/firmware/{release_id}/manifest.sig
GET  /terminal/device/{public_id}/{credential}/firmware/{release_id}/application.bin
POST /terminal/device/{public_id}/{credential}/firmware/events
```

OTA attempt admission requires one recently stored coherent header snapshot:
`X-FW-Version`,
`X-Firmware-Build-ID`, `X-Running-Partition`, `X-Boot-Count`,
`X-Battery-Valid: 1`, `X-Battery-MV`, and `X-Battery-Pct`.
`X-External-Power` is optional and accepts only `0` or `1`; absence means
unknown. Current firmware does not claim direct power, so offer admission uses
fresh measured reserve of at least 4000 mV and 80%. Forecasts and
`possible_charging` never authorize an update. Malformed telemetry clears the
stored snapshot; firmware independently re-samples measured power before
descriptor verification and again at the flash-write boundary.

Artifacts are available only for the exact active attempt, release, device,
and active credential that received the offer. Event bodies are bounded and
strict duplicate-free OTA1 JSON. The append-only ledger enforces one global
event identity and one sequence per attempt, returns `201` for first acceptance
and `200` for an exact replay, and rejects binding, transition, runtime-slot,
build, boot-count, or payload conflicts. Sequence gaps are retained explicitly
and cannot later count as clean rollout-promotion evidence.

The browser installer remains physically write-locked by dynamic server,
catalog, release/model, printed-revision, enrollment, and HIL gates. Production
has no trusted catalog key, positive generation, online enrollment identity, or
qualified release/model tuple, so it renders no Wi-Fi inputs and disables the
Connect action before any `navigator.serial.requestPort` or artifact request can
begin. When all independent gates are deliberately satisfied, one explicit user
gesture selects one port and holds one origin-wide Web Lock through exact
four-segment preserve-config flash/readback, reset, RET1 configuration/result,
and activation polling. Whole-chip erase remains unavailable.

Browser firmware responses use `Cache-Control: private, no-store`, `nosniff`,
and same-origin resource policy. Browser artifact responses also include an
exact `Content-Length`, a strong SHA-256 `ETag`, and a sanitized attachment
filename. Unknown resources return 404, a recognized but ineligible model
returns 409, and missing, untrusted, stale-generation, or corrupt approved
state returns a non-disclosing 503. Catalog/metadata reads are limited to six
per minute per client; browser artifact reads are limited to twelve. Scoped
device OTA artifacts use the same private/no-store, `nosniff`, length, and ETag
boundaries without `Content-Disposition`; device artifacts and events are each
limited to 120 requests per minute per client.

### Secure terminal enrollment foundation

RET1 enrollment uses the authenticated browser session for owner intent and a
separate per-device credential for later terminal check-ins. Public API tokens
cannot call the enrollment APIs. The deployed browser surface imports its RET1
transport only through the independently gated workflow. Production remains
locked: it can inspect capabilities and revoke an existing secure credential,
but it exposes no Wi-Fi fields, leaves Connect disabled, and cannot request a
port, download an artifact, flash, configure, or erase a device.

```text
GET  /api/terminal/enrollment/capabilities
POST /api/terminal/enrollment/intents
POST /api/terminal/enrollment/intents/{attempt_id}/ticket
POST /api/terminal/enrollment/intents/{attempt_id}/complete
POST /api/terminal/enrollment/intents/{attempt_id}/cancel
GET  /api/terminal/enrollment/intents/{attempt_id}
POST /api/terminal/enrollment/devices/{public_id}/revoke

GET /terminal/device/{public_id}/{credential}/schedule.json
GET /terminal/device/{public_id}/{credential}/image.bmp
```

The capabilities read is session-authenticated and private. Intent, ticket,
completion, cancellation, and revocation writes additionally require a browser
session cookie, an approved same-origin `Origin`, and a same-origin Fetch
Metadata claim when the browser sends one. Intent and ticket UUIDs are
idempotency keys; reusing one with different exact input returns 409. The server
accepts only an exact RET1 status/hello/hello-ack transcript for a
catalog-qualified E1001 or E1002 release and refuses E1004. Cancellation binds
the exact `client_intent_id` and operation `cancel`, is owner-scoped and
same-origin, and supersedes only that attempt and candidate before encrypted
device provisioning may have begun.

Issuance remains fail-closed unless all of these agree:

- the explicit server enablement flag and exact HTTPS origin;
- a protected, process-owned P-256 online signing key and configured key ID;
- a detached-signature-verified schema-2 firmware release whose RET1 public
  key hash and key ID match that online identity;
- a positive pinned catalog generation; and
- an explicit release/model physical-HIL allowlist.

The online ES256 enrollment key is independent of the offline Ed25519 firmware
release key. Tickets last at most ten minutes (the configured default is five),
use low-S raw `R || S` signatures, and bind the exact transcript hash, model,
reported MAC, firmware version, opaque terminal UUID, next configuration
generation, configuration SHA-256, operation, and one-time ticket ID. Physical
cable observation is not hardware attestation: the MAC, model, chip revision,
and firmware version remain self-reported inventory data.

The browser creates a 32-byte URL credential and sends only its SHA-256 plus
the configuration SHA-256 to the server. PostgreSQL stores only those hashes;
the raw credential exists in the device configuration and subsequent scoped
HTTPS path. The exact compact JWS is retained only so an identical ticket retry
can receive the same signed result. Wi-Fi SSID/password and configuration JSON
never enter an application request, database row, log, browser persistence, or
artifact. The server authorizes the browser-supplied configuration hash; it
cannot independently inspect the encrypted configuration or prove that its
schedule URL matches the issued URL without a future RET1 protocol extension.
The first-party browser builder therefore remains part of this trust boundary.
The browser validates the compact JWS structure and exact transition bindings;
firmware performs the authoritative ES256 signature verification before it
decrypts and stages configuration.

A cancelled pre-write attempt may be reused only after a new physical handshake
proves that the device still reports the old generation; the server then issues
fresh hashes and a fresh ticket for that same generation. If the encrypted
result was lost, the browser never automatically replays it. A fresh observed
target generation may reconcile one unique recent lineage and advance safely,
but physical cable evidence never substitutes for scoped HTTPS activation.

Browser completion is advisory. A candidate credential becomes active only on
the first matching scoped HTTPS check-in with the expected normalized MAC and
model-specific query (`variant=bw` for E1001; no query for E1002). A pending
first enrollment keeps only the same owner's legacy shared URL usable, so an
interrupted serial write does not strand the terminal. Once active, the device
cannot fall back to any shared URL. Re-enrollment keeps the existing active
credential until the new candidate checks in; the immediately previous
generation then remains a bounded rollback credential for 24 hours. Older
generations are revoked. Owner revocation is row-locked and idempotently
revokes candidate, active, and rollback credentials; a revoked terminal stays
isolated from shared routing and requires a new qualified physical enrollment.

The terminal UUID and credential are both required, unknown or mismatched
devices return the same 404, and schedule/image responses are private and
revalidated. Treat the scoped URL as a secret and do not paste it into support
records. Caddy skips `/terminal/device/*` access logs, while an outer-scope ASGI
redactor protects Uvicorn success and exception logs. Enrollment state changes
use one PostgreSQL device-to-attempt-to-credential lock order; a transaction
advisory lock and partial unique secure-MAC index serialize absent-row ownership
claims. Migration `f3a4b5c6d7e8` adds this state without changing legacy
terminal credentials; downgrade intentionally destroys enrollment audit and
credential-hash state.

The complete trust and recovery contract is in
[`docs/terminal/secure-enrollment.md`](terminal/secure-enrollment.md).
