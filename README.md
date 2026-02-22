# Mail Client

A self-hosted, AI-augmented email client built on Svelte 5, FastAPI, and PostgreSQL. It connects to Gmail via the Google API and provides intelligent email management powered by Anthropic Claude.

**Key features:**

- Full Gmail integration -- sync all mail, labels, and categories with real-time actions (read/unread, star, archive, trash, spam, label)
- AI-powered email categorization, summarization, and action item extraction via Claude
- Rich HTML composition with Tiptap editor, inline images, links, and reply/forward threading
- Multi-account support -- connect multiple Gmail accounts under one user
- Subscription management -- AI-powered unsubscribe with browser automation, bulk unsubscribe, sender blocking, and post-unsubscribe tracking
- "Talk to your Emails" AI chat -- conversational assistant that can search emails, read attachments, access calendar, and browse the web; exportable as Markdown or PDF
- Todo management -- manual and AI-extracted action items with AI-drafted replies you can approve and send directly
- Flow daily dashboard -- day summary with upcoming events, pending todos, needs-reply queue, awaiting-response tracking, active thread digests, and inline AI reply generation
- AI Insights -- thread digests, topic-based email bundles, conversation type detection, trending topics, and a "needs attention" queue with snooze/ignore
- AI reply generation -- suggested replies (accept, decline, defer) and custom-prompt replies
- Google Calendar integration -- month, week, and day views with multi-account support
- Statistics dashboard -- email volume charts, top senders, read/unread ratios, AI category breakdowns
- 6 color themes (Amber, Blue, Rose, Emerald, Purple, Monochrome) with light/dark/system mode
- Customizable keyboard shortcuts with visual overlay (hold Alt/Option to see shortcuts)
- Pop-out email viewer for side-by-side work
- Real-time updates via Server-Sent Events (SSE) -- new emails and AI analysis results push to the browser instantly via Redis Pub/Sub, no polling required
- Cross-thread reply detection -- replies that Gmail places in a different thread (e.g. after a subject change) are still recognized via In-Reply-To / References headers
- Background sync via Redis + ARQ workers
- Self-hosted and private -- all data stored locally, no third-party analytics

### Security

- HMAC-signed OAuth state tokens with expiry to prevent forgery and replay attacks
- CSRF protection on Google login OAuth flow via random state cookie verification
- Rate limiting on login endpoint (5 attempts/minute) to block brute-force attacks
- HTML sanitization with DOMPurify on email body rendering and AI markdown output
- Allowlisted sort parameters to prevent model attribute probing

## Screenshots

### Classic Inbox
The traditional inbox view with sidebar navigation, smart views (Needs Reply, Urgent, Waiting On, FYI), and AI-powered category badges on each email.

![Classic Inbox](screenshots/ClassicInbox.png)

### Flow — Daily Dashboard
Flow is a daily productivity dashboard that surfaces upcoming calendar events, pending todos, emails needing a reply, sent messages awaiting a response, and active thread digests -- all in one view with inline AI reply generation and a collapsible chat sidebar.

![Flow Dashboard](screenshots/Flow.png)

### Calendar
A full weekly calendar view with color-coded events pulled from Google Calendar, supporting multiple calendar categories and day/week/month views.

![Calendar View](screenshots/Calendar.png)

### Subscription Management & AI Unsubscribe
The Subscriptions page lists every mailing list and marketing sender detected by AI, grouped by domain with email counts and last-received dates. One-click unsubscribe triggers a fully automated Playwright browser session guided by Claude's vision model -- the AI loads the unsubscribe page, analyzes the layout, fills in forms or clicks buttons, and verifies the result. A live progress modal streams each step in real time: browser launch, page analysis, LLM reasoning, screenshots of the actual unsubscribe page, and a final success/failure confirmation. Bulk unsubscribe lets you select multiple senders and process them sequentially, and senders are optionally marked as spam in Gmail after unsubscribing.

![Subscription Management & AI Unsubscribe](screenshots/Unsubscribe.png)

## Architecture

```
Browser (Svelte 5 SPA)
  |  EventSource (SSE)
  |
  +-- Caddy (automatic TLS, static files, /api reverse proxy)
  |
  +-- FastAPI (REST API, JWT auth, email CRUD, SSE event stream)
        |
        +-- PostgreSQL (emails, users, accounts, AI analyses, settings)
        +-- Redis + ARQ (background sync jobs, batch AI analysis)
        +-- Redis Pub/Sub (real-time event delivery to SSE clients)
        +-- Gmail API (message sync, send, label management)
        +-- Google Calendar API (event sync, multi-account)
        +-- Claude API (categorization, summarization, trend analysis, reply generation)
        +-- Playwright (headless browser for AI-powered unsubscribe automation)
        +-- Brave Search API (optional, web search for AI chat)
```

Caddy terminates TLS and serves the built frontend static files. All `/api/*` requests are reverse-proxied to the FastAPI backend running on `localhost:8000`. Background work (email sync, AI batch analysis) is handled by an ARQ worker process connected to Redis. Real-time notifications (new emails, AI analysis completion) flow from workers through Redis Pub/Sub to a per-user SSE endpoint, which pushes events to all connected browser tabs. The Playwright headless browser is used on-demand for AI-powered URL-based unsubscribe automation.

## Tech Stack

| Layer          | Technology                                                                    |
| -------------- | ----------------------------------------------------------------------------- |
| Frontend       | Svelte 5, Vite, Tailwind CSS 4, Tiptap (rich text), DOMPurify, Feather Icons |
| Backend        | Python 3.13, FastAPI, SQLAlchemy (async + asyncpg), Alembic, slowapi          |
| Background     | ARQ workers, Redis                                                            |
| Database       | PostgreSQL 17                                                                 |
| Reverse Proxy  | Caddy 2 (automatic HTTPS)                                                    |
| AI / APIs      | Anthropic Claude, Google Gmail API, Google Calendar API                       |
| Automation     | Playwright (headless Chromium for AI-powered unsubscribe)                     |
| Search         | Brave Search API (optional, for AI chat web search)                           |

## Quick Start (One-Liner)

Install everything on a fresh Linux server with a single command:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/amcchord/email/main/scripts/install.sh)
```

This downloads the repo, then launches an interactive setup wizard that walks you through every step -- system dependencies, Google Cloud OAuth, database, domain/TLS, and service configuration.

To install to a custom directory:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/amcchord/email/main/scripts/install.sh) --install-dir=/srv/mail
```

### What the wizard does

The setup wizard is a 9-step interactive TUI powered by [Rich](https://github.com/Textualize/rich) and [InquirerPy](https://github.com/kazhala/InquirerPy):

| Step | What it does |
| ---- | ------------ |
| 1. Pre-flight checks | Detects OS/distro, checks installed software, verifies port availability |
| 2. System dependencies | Installs PostgreSQL, Redis, Caddy, Node.js, and build tools via your package manager |
| 3. Google Cloud & OAuth | Automates GCP project creation and API enabling via `gcloud` CLI; guides you through OAuth consent screen and credential setup with direct links to the right Google Console pages |
| 4. Domain & SSL | Configures your domain, checks DNS, generates the Caddyfile |
| 5. Database setup | Creates the PostgreSQL user and database, generates a secure password |
| 6. Configuration | Generates `.env` with auto-generated secrets, prompts for admin credentials and API keys |
| 7. Application build | Creates Python venv, installs dependencies, installs Playwright browsers, builds the Svelte frontend, runs migrations |
| 8. Service installation | Generates and installs systemd unit files, enables and starts all services |
| 9. Verification | Runs 18 health checks covering infrastructure, services, TLS, DNS, and API connectivity |

The wizard is **idempotent** (safe to re-run), **resumable** (saves progress if interrupted), and **non-destructive** (asks before overwriting any existing configuration).

### Health checks

Run the health check suite at any time to verify your installation:

```bash
bash scripts/install.sh --verify
```

This produces a pass/fail table covering PostgreSQL, Redis, the API, frontend build, systemd services, DNS, HTTPS, SSL certificates, file permissions, and configuration completeness.

## Prerequisites

- **OS:** Linux server (Debian/Ubuntu recommended; Fedora/RHEL and Arch also supported)
- **Python:** 3.11+ (the wizard checks for this and guides installation)
- **Git:** required for cloning the repository
- **Domain name** pointed at your server (Caddy uses this for automatic TLS)
- **Google Cloud project** with Gmail API enabled and OAuth 2.0 credentials
- **Anthropic API key** (optional, for AI features -- can be added later)

All other dependencies (Node.js, PostgreSQL, Redis, Caddy) are installed automatically by the setup wizard.

## Manual Installation

If you prefer to install manually instead of using the wizard:

### 1. Clone the repository

```bash
git clone https://github.com/amcchord/email.git /opt/mail
cd /opt/mail
```

### 2. Create a system user

The application runs as a dedicated `mailapp` user:

```bash
sudo useradd --system --home /opt/mail --shell /bin/bash mailapp
sudo chown -R mailapp:mailapp /opt/mail
```

### 3. Install system dependencies

On Debian/Ubuntu:

```bash
# PostgreSQL
sudo apt install -y postgresql postgresql-client

# Redis
sudo apt install -y redis-server

# Python
sudo apt install -y python3 python3-venv python3-pip

# Node.js (via NodeSource or nvm)
# See https://nodejs.org/ for current install instructions

# Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

### 4. Create the PostgreSQL database

```bash
sudo -u postgres psql <<SQL
CREATE USER mailapp WITH PASSWORD 'your-secure-password';
CREATE DATABASE maildb OWNER mailapp;
GRANT ALL PRIVILEGES ON DATABASE maildb TO mailapp;
SQL
```

Replace the password with your own secure value and update `DATABASE_URL` in `.env` to match.

### 5. Configure environment variables

Create a `.env` file in the project root:

```bash
cp /dev/null .env
chmod 600 .env
```

Then populate it (see the [Configuration](#configuration) section below for all variables).

### 6. Run the setup script

```bash
sudo -u mailapp bash scripts/setup.sh
```

This script will:
- Start PostgreSQL and Redis if not already running
- Create a Python virtual environment and install dependencies
- Install Playwright Chromium browser for AI-powered unsubscribe
- Run Alembic database migrations
- Generate an encryption key if one is not set
- Install frontend npm packages and build the Svelte app

## Configuration

All configuration is done through the `.env` file in the project root. The backend reads these values via Pydantic Settings (see `backend/config.py`).

| Variable               | Description                                                   | Example / Default                                              |
| ---------------------- | ------------------------------------------------------------- | -------------------------------------------------------------- |
| `DATABASE_URL`         | PostgreSQL connection string (async)                          | `postgresql+asyncpg://mailapp:PASSWORD@localhost:5432/maildb`  |
| `REDIS_URL`            | Redis connection string                                       | `redis://localhost:6379/0`                                     |
| `SECRET_KEY`           | Secret for signing JWT tokens -- use a long random string     | (generate with `openssl rand -hex 32`)                         |
| `ENCRYPTION_KEY`       | Fernet key for encrypting stored credentials                  | (auto-generated by `setup.sh` if left blank)                   |
| `ADMIN_USERNAME`       | Username for the admin login                                  | `admin`                                                        |
| `ADMIN_PASSWORD`       | Password for the admin login                                  | (choose a strong password)                                     |
| `CLAUDE_API_KEY`       | Anthropic API key for AI features                             | `sk-ant-api03-...`                                             |
| `GOOGLE_CLIENT_ID`     | OAuth 2.0 client ID from Google Cloud Console                 | (from Google Cloud)                                            |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret from Google Cloud Console             | (from Google Cloud)                                            |
| `GOOGLE_REDIRECT_URI`  | OAuth callback URL -- must match Google Console config        | `https://yourdomain.com/api/auth/google/callback`              |
| `ALLOWED_ORIGINS`      | Comma-separated list of allowed CORS origins                  | `https://yourdomain.com`                                       |
| `BRAVE_SEARCH_API_KEY` | Brave Search API key (optional, enables web search in AI chat)| (from [Brave Search](https://brave.com/search/api/))           |
| `SYNC_INTERVAL_SECONDS`| Email sync interval in seconds                                | `60`                                                           |

## Google OAuth Setup

The app requires a Google Cloud project with OAuth 2.0 credentials to access Gmail and Google Calendar. You will need to:

1. Create a Google Cloud project and enable the **Gmail API** and **Google Calendar API**.
2. Configure the **OAuth consent screen** with the required scopes.
3. Create **OAuth 2.0 credentials** (Web application type) with two redirect URIs -- one for login and one for connecting accounts.
4. Copy the Client ID and Client Secret into your `.env` file.

The full list of required scopes:

| Scope | Purpose |
| --- | --- |
| `openid` | OpenID Connect authentication |
| `userinfo.email` | Identify users by email |
| `userinfo.profile` | Display name and profile picture |
| `gmail.readonly` | Read email messages and metadata |
| `gmail.send` | Send and reply to emails |
| `gmail.modify` | Mark read/unread, star, archive, trash, spam, labels |
| `gmail.labels` | List and manage Gmail labels |
| `calendar.readonly` | Read calendar events (for calendar view and AI context) |

**For a detailed, step-by-step walkthrough** -- including screenshots guidance, troubleshooting, and how to handle Google's verification process -- see the **[Google Cloud Setup Guide](docs/google-setup.md)**.

## Running the Application

### Systemd services

The application uses two systemd services plus Caddy. Install the service files:

**`/etc/systemd/system/mailapp.service`** -- API server:

```ini
[Unit]
Description=Mail Client API
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=mailapp
Group=mailapp
WorkingDirectory=/opt/mail
ExecStart=/opt/mail/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3
Environment=PATH=/opt/mail/venv/bin:/usr/local/bin:/usr/bin
Environment=OAUTHLIB_RELAX_TOKEN_SCOPE=1

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/mailworker.service`** -- background worker:

```ini
[Unit]
Description=Mail Client Background Worker
After=network.target postgresql.service redis-server.service mailapp.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=mailapp
Group=mailapp
WorkingDirectory=/opt/mail
ExecStart=/opt/mail/venv/bin/arq backend.workers.tasks.WorkerSettings
Restart=always
RestartSec=5
Environment=PATH=/opt/mail/venv/bin:/usr/local/bin:/usr/bin
Environment=OAUTHLIB_RELAX_TOKEN_SCOPE=1

[Install]
WantedBy=multi-user.target
```

### Caddy configuration

Edit the `Caddyfile` in the project root and replace `email.mcchord.net` with your domain:

```
yourdomain.com {
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        X-XSS-Protection "1; mode=block"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "camera=(), microphone=(), geolocation=()"
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        -Server
    }

    handle /api/* {
        reverse_proxy localhost:8000
    }

    handle {
        root * /opt/mail/frontend/dist
        try_files {path} /index.html
        file_server
    }

    log {
        output file /var/log/caddy/mail.log
        format console
    }
}
```

Copy or symlink this file to `/etc/caddy/Caddyfile` (or configure Caddy to use it directly).

### Start everything

Enable and start all services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now postgresql redis-server caddy mailapp mailworker
```

Or use the convenience script:

```bash
bash scripts/start.sh
```

The application will be available at `https://yourdomain.com`. Log in with the admin credentials from your `.env` file, then connect a Gmail account through the Settings page.

### Restarting after changes

Use the restart script to selectively restart services:

```bash
bash scripts/restart.sh                # restart everything (frontend build + backend + worker)
bash scripts/restart.sh --frontend     # rebuild frontend only
bash scripts/restart.sh --backend      # restart API server only
bash scripts/restart.sh --worker       # restart background worker only
bash scripts/restart.sh --backend --worker  # restart both backend services
```

The restart script writes a build version file that triggers auto-reload in open browser tabs.

## Development

### Frontend

The frontend is a Svelte 5 SPA using Vite as the build tool. During development, Vite proxies `/api` requests to the backend:

```bash
cd frontend
npm install
npm run dev
```

This starts a dev server (typically on `http://localhost:5173`) with hot module replacement.

### Backend

Run the FastAPI server with auto-reload:

```bash
source venv/bin/activate
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Make sure PostgreSQL and Redis are running before starting the backend.

### Background worker

Run the ARQ worker for background tasks (email sync, AI analysis):

```bash
source venv/bin/activate
arq backend.workers.tasks.WorkerSettings
```

### Database migrations

Migrations are managed with Alembic:

```bash
source venv/bin/activate

# Apply all pending migrations
alembic upgrade head

# Create a new migration after changing models
alembic revision --autogenerate -m "describe your change"

# Downgrade one revision
alembic downgrade -1
```

## Project Structure

```
/opt/mail/
├── backend/
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Pydantic Settings (reads .env)
│   ├── database.py          # SQLAlchemy async engine and session
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── user.py          #   User accounts and preferences
│   │   ├── email.py         #   Email messages, attachments, labels
│   │   ├── account.py       #   Connected Gmail accounts, sync status
│   │   ├── ai.py            #   AI analyses, thread digests, bundles, unsubscribe tracking
│   │   ├── todo.py          #   Todo items with AI draft support
│   │   ├── chat.py          #   AI chat conversations and messages
│   │   ├── calendar.py      #   Calendar events and sync status
│   │   └── settings.py      #   App settings (key-value store)
│   ├── routers/             # API route handlers
│   │   ├── auth.py          #   Authentication (login, OAuth, JWT, device auth)
│   │   ├── admin.py         #   Admin operations, feature flags, settings
│   │   ├── emails.py        #   Email CRUD, search, bulk actions
│   │   ├── compose.py       #   Email composition and sending
│   │   ├── accounts.py      #   Gmail account management, allowed accounts
│   │   ├── ai.py            #   AI analysis, subscriptions, unsubscribe, reply generation
│   │   ├── todos.py         #   Todo CRUD, create from email action items
│   │   ├── chat.py          #   AI chat (streaming, conversations)
│   │   ├── calendar.py      #   Calendar events and sync
│   │   └── events.py        #   SSE event stream (real-time push to browser)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # Business logic
│   │   ├── gmail.py         #   Gmail API integration
│   │   ├── sync.py          #   Email sync orchestration
│   │   ├── ai.py            #   Claude AI (categorization, replies, digests, bundles)
│   │   ├── chat.py          #   AI chat agent (plan/execute/verify, tool use)
│   │   ├── search.py        #   Full-text search (PostgreSQL vectors)
│   │   ├── credentials.py   #   Encrypted credential storage
│   │   ├── calendar_sync.py #   Calendar sync orchestration
│   │   ├── google_calendar.py # Google Calendar API client
│   │   ├── unsubscribe.py   #   AI-powered unsubscribe (email + Playwright browser)
│   │   ├── bundler.py       #   Topic-based email clustering
│   │   ├── notifications.py #   Redis Pub/Sub event publishing
│   │   └── rate_limiter.py  #   API rate limiting
│   ├── utils/               # Shared utilities
│   └── workers/
│       └── tasks.py         # ARQ background task definitions
├── frontend/
│   ├── src/
│   │   ├── main.js          # App entry point
│   │   ├── App.svelte       # Root component and routing
│   │   ├── app.css          # Global styles and theme variables
│   │   ├── pages/           # Top-level page components
│   │   │   ├── Flow.svelte              # Daily dashboard (events, todos, replies, threads)
│   │   │   ├── Inbox.svelte             # Traditional inbox (column + table views)
│   │   │   ├── Compose.svelte           # Email composer (rich text, multi-account)
│   │   │   ├── Subscriptions.svelte     # Subscription management and unsubscribe
│   │   │   ├── Admin.svelte             # Settings, accounts, AI models, preferences
│   │   │   ├── Stats.svelte             # Email statistics dashboard
│   │   │   ├── AIInsights.svelte        # AI insights (digests, bundles, topics)
│   │   │   ├── Todos.svelte             # Todo list with AI draft replies
│   │   │   ├── Chat.svelte              # "Talk to your Emails" AI chat
│   │   │   ├── Calendar.svelte          # Calendar (month/week/day views)
│   │   │   ├── DeviceAuth.svelte        # Device authorization for CLI/TUI
│   │   │   ├── EmailViewStandalone.svelte # Pop-out email viewer
│   │   │   └── Login.svelte             # Login page (OAuth + admin password)
│   │   ├── components/      # Reusable UI components
│   │   │   ├── layout/      #   App shell, sidebar, header
│   │   │   ├── email/       #   Email list, viewer, thread, unsubscribe viewer
│   │   │   ├── ai/          #   AI insight cards, category badges
│   │   │   ├── calendar/    #   Calendar month/week/day views, event details
│   │   │   └── common/      #   Buttons, modals, toast, keyboard shortcuts, etc.
│   │   └── lib/             # Shared frontend utilities
│   │       ├── api.js              # API client (fetch wrapper)
│   │       ├── stores.js           # Svelte stores (user, page, sync)
│   │       ├── theme.js            # Dark/light/system mode management
│   │       ├── themes.js           # 6 color theme definitions
│   │       ├── realtime.js         # SSE client for real-time event updates
│   │       ├── autoReload.js       # Build version polling
│   │       ├── calendarLayout.js   # Calendar layout utilities
│   │       ├── sanitize.js         # DOMPurify wrappers for HTML/markdown sanitization
│   │       ├── shortcutDefaults.js # Default keyboard shortcut bindings
│   │       └── shortcutStore.js    # Keyboard shortcut state management
│   ├── vite.config.js       # Vite build configuration
│   └── package.json         # Frontend dependencies
├── alembic/                 # Database migration scripts
│   ├── env.py
│   └── versions/            # Individual migration files
├── scripts/
│   ├── install.sh           # One-liner bootstrap: clones repo, launches setup wizard
│   ├── setup/               # Interactive TUI setup wizard (Python)
│   │   ├── __main__.py      #   CLI entry point (full wizard or --verify)
│   │   ├── wizard.py        #   Step sequencing, progress tracking, resume
│   │   ├── ui.py            #   Rich console helpers, prompts, status tables
│   │   └── steps/           #   Individual setup steps
│   │       ├── preflight.py     # OS detection, version checks
│   │       ├── system_deps.py   # Package installation (apt/dnf/pacman)
│   │       ├── google_cloud.py  # GCP project, APIs, OAuth automation
│   │       ├── database.py      # PostgreSQL user/database creation
│   │       ├── config.py        # .env generation, Caddyfile, domain setup
│   │       ├── application.py   # venv, pip, npm, Playwright, migrations, build
│   │       ├── services.py      # systemd unit generation and management
│   │       └── verify.py        # Health check suite
│   ├── setup.sh             # Legacy setup (venv, deps, migrations, build)
│   ├── start.sh             # Start all services via systemd
│   └── restart.sh           # Restart services after code changes
├── Caddyfile                # Caddy reverse proxy configuration
├── alembic.ini              # Alembic configuration
├── requirements.txt         # Python dependencies
├── goals.md                 # Project goals and vision
├── LICENSE                  # MIT License
└── .env                     # Environment variables (not committed)
```

## License

This project is licensed under the [MIT License](LICENSE).
