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
| Proxy/static files | `caddy.service`, tracked `/opt/mail/Caddyfile` |
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

Then apply only the release steps required by the diff.

When frontend code depends on a new schema or API response, do not use the
generic frontend-first order below. Keep the old built frontend live after the
Git fast-forward, take the backup, run Alembic while the old processes are
still serving, restart and verify the new API/workers, and only then build the
new frontend. This prevents a new browser bundle from calling an old mutation
contract and prevents new application startup from creating tables outside
Alembic.

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
restarts, but selective commands make the blast radius clearer. Production has
a systemd override whose `ExecStart` and `ExecReload` both use the tracked
`/opt/mail/Caddyfile`; the distro default under `/etc/caddy` is not the live
source. If Caddy changes, validate the tracked file before reload:

```bash
caddy validate --config /opt/mail/Caddyfile
systemctl reload caddy
```

Never downgrade a queue/outbox migration while actionable rows remain. Stop
every writer and drainer, audit the table using aggregate state counts, and
prefer rolling the application forward once production has accepted work. A
downgrade that drops an outbox destroys idempotency and recovery evidence.

## Post-deploy Verification

```bash
curl -fsS https://email.mcchord.net/api/health
systemctl --no-pager --full is-active mailapp mailworker mailworker-cron mailtui caddy
journalctl --no-pager --since '-5 minutes' -u mailapp -u mailworker -u mailworker-cron
```

Also verify the user-facing path changed by the release. Record the deployed
commit, commands, migration revision (if any), health result, and production
actions in `docs/progress/JOURNAL.md`.

## API Restart Bound

An open browser tab holds `/api/events/stream`, and uvicorn waits for every open
response before it exits. The stream never ends by itself: a shutdown does not
mark the client as disconnected, and the application's lifespan shutdown only
runs after that wait, so it cannot signal the stream. Without a bound,
`systemctl restart mailapp` with a tab open takes the full 90-second default
`TimeoutStopSec` and ends in SIGKILL (seen at 19:57 and 20:04 UTC on 2026-11-01).

While a worker drains, new connections are not refused. The supervisor still
holds the listening socket, so they wait in its backlog and Caddy returns 502
when the process exits. The 19:57 restart produced 20 502s on API and terminal
routes, 13 of them after waiting more than 30 seconds.

| Setting | Value | Why |
| --- | --- | --- |
| `--timeout-graceful-shutdown` | 15 | Requests get 15 seconds to finish, then uvicorn cancels what is left. In the Caddy log for 2026-10-16 to 2026-11-01, 161 of about 136,000 requests took longer than 15 seconds: 146 terminal image or schedule fetches and 15 others. |
| `TimeoutStopSec` | 25 | Backstop for the whole unit: 15 seconds of drain, up to 5 for lifespan shutdown, and 5 of margin. |

Expect these results:

- With a tab open, a restart takes about 15 seconds, and each affected worker logs
  `ERROR: Cancel N running task(s), timeout graceful shutdown exceeded`. This is
  expected, not a fault. The tab reconnects by itself.
- With no tab open, a restart takes a second or two and logs no such error.
- A request still running after 15 seconds is cancelled and logs
  `Exception in ASGI application` with a `CancelledError` traceback. Check that
  the client action was safe to retry.

Both settings live in `scripts/setup/steps/services.py` and the README, which only
apply to new installs. Production's unit file was installed once and is not updated
by a deployment, so it needs the change below.

### Apply on production (Mutating)

Only perform this when the user explicitly requests it. Applying has no effect
until the next restart. The drop-in leaves the installed unit file untouched.

```bash
ssh root@email.mcchord.net
install -d /etc/systemd/system/mailapp.service.d
cat > /etc/systemd/system/mailapp.service.d/graceful-shutdown.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/opt/mail/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 2 --timeout-graceful-shutdown 15
TimeoutStopSec=25
EOF
systemd-analyze verify mailapp.service
systemctl daemon-reload
systemctl show mailapp -p TimeoutStopUSec -p ExecStart
```

The first restart afterwards still stops a process started without the flag, so
with a tab open it runs to the new 25-second limit and logs `stop-sigterm timed
out`. Only the restart after that one proves the bound.

To roll back, remove the drop-in, then run `systemctl daemon-reload` and restart:

```bash
rm /etc/systemd/system/mailapp.service.d/graceful-shutdown.conf
```

### Verify with a connection open (Mutating: restarts the API)

Only an in-flight response holds a worker. An idle TCP connection is closed at
once and proves nothing, so use a real stream: keep a signed-in tab open at
`https://email.mcchord.net`, then on the host:

```bash
ss -Htn state established '( sport = :8000 )' | wc -l
journalctl --no-pager -u mailapp --since "$(systemctl show mailapp -p ActiveEnterTimestamp --value)" -o cat | grep -c 'GET /api/events/stream'
systemd-cgls --no-pager -u mailapp.service
since=$(date -u '+%F %T')
time systemctl restart mailapp
journalctl --no-pager -u mailapp --since "$since" -o cat | grep -E 'Cancel [0-9]+ running|stop-sigterm|Finished server process|Failed with result'
curl -fsS https://email.mcchord.net/api/health
```

The first two commands must each report at least 1. The bound holds when
`systemctl restart` returns in about 15 seconds, the log shows `Cancel N running`
and `Finished server process`, and it shows neither `stop-sigterm` nor `Failed with
result`.

If the restart takes 25 seconds and logs `stop-sigterm` although uvicorn finished,
a process other than uvicorn kept the unit open. Both forced stops on 2026-11-01
killed one extra `python3` beyond the workers and resource tracker, and its origin
is not yet known. The `systemd-cgls` output above lists it.

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
