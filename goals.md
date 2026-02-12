# Mail Client — Project Goals

A self-hosted, AI-augmented email client built on Svelte 5, FastAPI, and PostgreSQL that connects to Gmail via the Google API. The aim is a fast, private alternative to the Gmail web UI with intelligent email management powered by Claude.

## Core Goals

### Full Gmail Feature Parity
- Sync all mail, not just inbox — every folder, label, and category should be accessible.
- Support all standard mailbox actions: read/unread, star, archive, trash, spam, label — synced back to Gmail in real time.
- Rich HTML composition with formatting toolbar, inline images, links, and proper reply/forward threading.
- Full-text search across subject, sender, and body content.
- Pagination that handles large mailboxes (tens of thousands of emails) without choking.

### AI-Powered Email Intelligence
- Use Claude to automatically categorize emails: urgent, needs response, FYI, can ignore, awaiting reply.
- Generate per-email summaries and extract action items.
- Surface trends over time: what topics are hot, who sends the most actionable mail, what's been ignored.
- Provide a dedicated "Needs Attention" queue so nothing important falls through the cracks.
- Smart inbox summary: "You have 3 urgent emails and 5 needing a response."

### Modern, Flexible UI
- Column view (traditional email client sidebar + reading pane) and table view (spreadsheet-style row layout) with a toggle.
- Pop-out email viewer: open any email in its own browser window for side-by-side work.
- Dark and light themes with a warm accent palette.
- Responsive sidebar with collapsible sections for system mailboxes, Gmail categories, user labels, and connected accounts.
- Stats dashboard with volume charts, top senders, read/unread ratios, and AI category breakdowns.

### Reliable Authentication and Session Management
- Google OAuth for login and account connection.
- Admin password fallback for initial setup.
- Persistent sessions via automatic JWT token refresh — users should not get logged out every 15 minutes.
- Secure httpOnly cookie storage for tokens.

### Multi-Account Support
- Connect multiple Gmail accounts under a single user.
- Filter the inbox by account or view all accounts merged.
- Per-account sync status and controls.

### Self-Hosted and Private
- Runs on a single server behind Caddy with automatic TLS.
- All email data stored locally in PostgreSQL — no third-party analytics or tracking.
- API keys and OAuth credentials stored encrypted in the database.
- Background sync via Redis + ARQ workers.

## Non-Goals (for now)
- IMAP/SMTP support for non-Gmail providers.
- Mobile-native app (the web UI should be responsive enough).
- Calendar or contacts integration.
- End-to-end encryption (Gmail API handles transport security).

## Architecture

```
Browser (Svelte 5 SPA)
  |
  |-- Caddy (TLS, static files, /api proxy)
  |
  |-- FastAPI (REST API, JWT auth, email CRUD)
  |     |
  |     |-- PostgreSQL (emails, users, accounts, AI analyses, settings)
  |     |-- Redis + ARQ (background sync jobs, batch AI analysis)
  |     |-- Gmail API (message sync, send, label management)
  |     |-- Claude API (categorization, summarization, trend analysis)
```
