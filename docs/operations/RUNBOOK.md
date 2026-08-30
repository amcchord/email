# Operations Runbook

This runbook describes the environment observed on 2026-08-26. Commands that
change production are labeled. Reconfirm actual state before following them.

## Environment

| Item | Value |
| --- | --- |
| Public URL | `https://email.mcchord.net` |
| SSH | `root@email.mcchord.net` |
| Production checkout | `/opt/mail` |
| Application owner | `mailapp:mailapp` |
| API | `mailapp.service`, `127.0.0.1:8000` |
| Workers | `mailworker.service`, `mailworker-cron.service` |
| TUI | `mailtui.service`, ports 2222 and 8022 |
| Proxy/static files | `caddy.service`, `/etc/caddy/Caddyfile` |
| Database | PostgreSQL 17 on loopback port 5432 |
| Queue/cache | Redis on loopback port 6379 |

## Local Staging Setup

Requirements: Git, SSH, Python 3.13, Node.js, and npm.

```bash
make setup
make check
```

`make setup` creates `.venv/`, installs the pinned Python dependencies, and
runs `npm ci` for the frontend. It does not copy production configuration,
start PostgreSQL/Redis, install Playwright browsers, or create a local database.
`make test` supplies a deliberately unreachable placeholder PostgreSQL URL for
test collection; database integration tests need a separately provisioned
disposable database.

Optional components:

```bash
scripts/workspace/bootstrap.sh --desktop
scripts/workspace/bootstrap.sh --playwright
```

## Read-only Production Inspection

Preferred snapshot:

```bash
make remote-status
```

Manual inspection:

```bash
ssh root@email.mcchord.net
systemctl --no-pager --full status mailapp mailworker mailworker-cron mailtui caddy
journalctl --no-pager -n 100 -u mailapp
journalctl --no-pager -n 100 -u mailworker -u mailworker-cron
curl -fsS https://email.mcchord.net/api/health
git -c safe.directory=/opt/mail -C /opt/mail status --short --branch
```

Do not display `/opt/mail/.env` or query private mailbox data as a general
diagnostic step.

## Local Development

Frontend with API proxy:

```bash
npm --prefix frontend run dev
```

Unit tests and production frontend build:

```bash
make test
make frontend-build
```

The FastAPI configuration currently assumes production paths under `/opt/mail`.
Before doing full-stack local work, create a scoped task to make those paths
configurable and provision a disposable PostgreSQL/Redis environment. Do not
work around this by importing production secrets.

## Release Preflight

These steps are safe locally. They do not authorize a deployment.

1. Confirm the requested change and acceptance criteria in `CURRENT.md`.
2. Check `git status` and review the entire diff.
3. Rebase or merge the current `origin/main` without rewriting shared history.
4. Run change-specific checks and `make check` when practical.
5. Identify the exact release commit and ensure it is available on the remote.
6. Run `make remote-status` and confirm the live checkout has no unexpected
   changes.
7. Review dependency, Alembic, Caddy, and systemd changes separately. Define a
   recovery path and back up PostgreSQL before a risky migration.

## Production Deployment (Mutating)

Only perform this section when the user explicitly requests a deployment.
Deploy an exact reviewed commit; do not develop in `/opt/mail`.

Record the current live commit first:

```bash
ssh root@email.mcchord.net \
  'git -c safe.directory=/opt/mail -C /opt/mail rev-parse HEAD'
```

On the host, confirm a clean worktree and fast-forward to the reviewed commit
as the application owner. Replace `<reviewed-commit>` with the actual full Git
SHA; never leave it as a placeholder in an executed command.

```bash
ssh root@email.mcchord.net
git -c safe.directory=/opt/mail -C /opt/mail status --short --branch
sudo -u mailapp git -C /opt/mail fetch origin
sudo -u mailapp git -C /opt/mail merge --ff-only <reviewed-commit>
```

Then apply only the release steps required by the diff:

```bash
# Python dependency change
sudo -u mailapp /opt/mail/venv/bin/pip install -r /opt/mail/requirements.lock

# Frontend dependency or source change
sudo -u mailapp npm --prefix /opt/mail/frontend ci
sudo -u mailapp npm --prefix /opt/mail/frontend run build

# Alembic revision, only after backup and migration review
cd /opt/mail
sudo -u mailapp /opt/mail/venv/bin/alembic upgrade head

# Restart only affected processes
systemctl restart mailapp
systemctl restart mailworker mailworker-cron
systemctl restart mailtui
```

The repository also provides `bash scripts/restart.sh` for grouped rebuilds and
restarts, but selective commands make the blast radius clearer. If Caddy
changes, validate before reload:

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

## Post-deploy Verification

```bash
curl -fsS https://email.mcchord.net/api/health
systemctl --no-pager --full is-active mailapp mailworker mailworker-cron mailtui caddy
journalctl --no-pager --since '-5 minutes' -u mailapp -u mailworker -u mailworker-cron
```

Also verify the user-facing path changed by the release. Record the deployed
commit, commands, migration revision (if any), health result, and production
actions in `docs/progress/JOURNAL.md`.

## Incident and Recovery Principles

1. Stop making changes and capture the time, deployed commit, service state,
   relevant error summary, and last known healthy behavior.
2. Reduce impact with the narrowest reversible action (for example, restart one
   failed service after understanding why it failed).
3. Prefer a reviewed Git revert deployed through the normal path over editing
   live files or forcing the production branch backward.
4. Treat database rollback separately from code rollback. Do not downgrade or
   restore a production database until the data implications are understood.
5. Preserve useful evidence, but redact credentials, tokens, addresses, subject
   lines, message bodies, and attachments from repository documentation.
6. After recovery, reconcile production with Git and add the lesson to the
   journal or decisions file.
