# AGENTS.md

## Purpose

This repository is the staging home base for the Mail Client deployed at
`https://email.mcchord.net`.

- Develop, review, and validate changes in this checkout.
- Treat `origin/main` as the code source of truth.
- Treat `root@email.mcchord.net:/opt/mail` as a production deployment target,
  not as a development workspace.
- Keep the living project state in [WORKBOOK.md](WORKBOOK.md) and
  `docs/progress/`.

These instructions apply to the entire repository unless a more specific
`AGENTS.md` exists deeper in the tree.

## Start Every Session Here

1. Read `WORKBOOK.md` and `docs/progress/CURRENT.md`.
2. Read the newest entry in `docs/progress/JOURNAL.md` and any relevant entry
   in `docs/progress/DECISIONS.md`.
3. Run `git status --short --branch` and inspect existing changes before
   editing. Never overwrite unrelated user work.
4. Run `make remote-status` when the task depends on live state. This command
   is read-only.
5. State the intended scope. Keep the smallest useful change set.

## System Map

| Area | Location / service | Notes |
| --- | --- | --- |
| Frontend | `frontend/` | Svelte 5, Vite, Tailwind; production build in ignored `frontend/dist/` |
| API | `backend/main.py`, `backend/routers/` | FastAPI on production `127.0.0.1:8000` |
| Domain logic | `backend/services/` | Gmail, calendar, AI, queues, e-ink, notifications |
| Jobs | `backend/workers/` | ARQ workers backed by Redis |
| Data model | `backend/models/`, `alembic/versions/` | PostgreSQL 17 and Alembic |
| Reverse proxy | `Caddyfile` | TLS, static frontend, `/api/*`, TUI and downloads |
| Desktop | `electron/` | Optional Electron shell and release builds |
| Production app | `/opt/mail` | Owned by `mailapp:mailapp` |
| Production services | `mailapp`, `mailworker`, `mailworker-cron`, `mailtui`, `caddy` | Managed by systemd |

The README is the primary architecture and installation reference. `goals.md`
is historical product context and contains some stale non-goals; prefer the
current code and README when they disagree.

## Local Workflow

Bootstrap once:

```bash
make setup
```

Common checks:

```bash
make test             # Python test suite
make frontend-build   # production frontend build
make check            # both of the above
make remote-status    # read-only production snapshot
```

The bootstrap uses Python 3.13 when available because `requirements.lock` was
generated with Python 3.13. It creates `.venv/` and installs frontend packages
with `npm ci`. Desktop dependencies are opt-in with
`scripts/workspace/bootstrap.sh --desktop`.

The application currently assumes production paths such as `/opt/mail/.env`
and `/opt/mail/frontend/dist`. Do not solve local configuration by copying the
production `.env`. Tests that exercise external services must use fakes,
fixtures, or explicitly documented non-production credentials. The `make test`
target supplies a deliberately unreachable placeholder database URL so modules
can import without connecting to production; tests that need a database must
provision and select a disposable one explicitly.

## Change Rules

- Never commit `.env` files, tokens, OAuth credentials, mailbox data, database
  dumps, logs, downloaded attachments, or production configuration values.
- Prefer focused branches and reviewable commits. Do not rewrite shared branch
  history.
- Preserve API compatibility unless the task explicitly changes the contract.
  Update `docs/api.md` when an endpoint or payload changes.
- Add an Alembic revision for schema changes. Review generated migrations by
  hand and describe forward and backward data implications.
- Keep network calls out of unit tests. Mock Gmail, Google Calendar, Anthropic,
  Home Assistant, weather, and search clients.
- For UI changes, test loading, empty, error, and narrow-screen states. Preserve
  keyboard navigation and sanitization of email HTML.
- For worker changes, consider retries, idempotency, rate limits, duplicate
  delivery, and what happens if a process restarts mid-job.
- Do not casually modify generated or ignored artifacts (`frontend/dist/`,
  `node_modules/`, `data/`, `downloads/`, `bin/`).

## Validation by Change Type

| Change | Minimum validation |
| --- | --- |
| Python service, router, model, or worker | Relevant tests, then `make test` |
| Svelte, CSS, or frontend API client | `make frontend-build`; inspect the affected flow in a browser when practical |
| Database schema | Tests, migration review, and `alembic upgrade head` against a disposable database |
| Caddy or systemd | Validate syntax/configuration without reloading production first |
| E-ink renderer | Relevant renderer tests plus image/layout audit when visual output changes |
| Documentation or operations only | Check commands, paths, links, and `git diff --check` |

## Validation Economy

Keep release confidence high without turning small follow-ups into recursive
full-suite loops.

1. During implementation, run only tests affected by the current edit.
2. Once the candidate is coherent, freeze its scope and request one bounded
   P0/P1 review. Record P2 polish for a later batch unless it blocks the primary
   workflow, accessibility, ownership, integrity, or security.
3. Fix review blockers with focused checks, then run the required migration,
   generated-fixture, and browser evidence once each when applicable.
4. Run one final `git diff --check && make check` after code freeze. If that
   gate finds a release blocker, fix it, rerun its focused test, then rerun the
   consolidated gate once.
5. After the final code gate, permit documentation-only closeout without
   restarting broad tests. Do not repeat disposable-database, browser, or full
   suite evidence unless the related code changes again.

This protocol does not weaken production preflight, backup, migration, health,
or rollback requirements.

If a full check cannot run, record exactly what ran, what did not, and why in
the journal and final handoff.

## Production Safety

SSH access is `root@email.mcchord.net`, but root access does not make a
production change routine.

- Inspection is allowed when relevant. Prefer `make remote-status`,
  `systemctl status`, `journalctl`, `curl`, and read-only Git commands.
- Do not deploy, restart services, run migrations, change Caddy/systemd,
  modify `.env`, write production data, or push Git changes unless the user has
  explicitly asked for that state change in the current task.
- Do not print or copy `/opt/mail/.env`, database contents, OAuth tokens,
  attachments, or private mail into this workspace or chat.
- Never edit tracked files directly in `/opt/mail` during normal work. If an
  emergency live edit is explicitly authorized, capture the prior state and
  immediately reconcile the change back into Git.
- Run application Git and build commands as `mailapp` where practical so the
  checkout remains correctly owned. Root is for service and host operations.
- Before an authorized deployment: confirm local and live Git state, identify
  the exact commit, run relevant checks, review dependency and migration diffs,
  define the rollback path, and take a database backup before risky migrations.
- After deployment: verify `/api/health`, service state, recent logs, and the
  user-facing path that changed.

See `docs/operations/RUNBOOK.md` for the observed production topology and
operational commands.

## Progress Protocol

Documentation is part of the work, not a cleanup step.

- Update `docs/progress/CURRENT.md` whenever the active objective, live
  baseline, blockers, or next action changes.
- Append one concise dated entry to `docs/progress/JOURNAL.md` for each material
  work session. Include scope, files/commits, verification, production actions,
  and the next action.
- Add durable choices to `docs/progress/DECISIONS.md`; do not bury architectural
  decisions in the journal.
- Keep secrets, personal email content, and raw production logs out of all
  progress documents.
- When a work item is complete, move it out of `CURRENT.md`; Git history and the
  journal retain the record.

## Definition of Done

A task is complete when the requested behavior or documentation exists, the
smallest relevant validation has passed, no secret or generated artifact was
added, the diff has been reviewed, and the workbook records the result and the
next safe action. Production is only “done” after an explicitly requested
deployment has also passed post-deploy health checks.
