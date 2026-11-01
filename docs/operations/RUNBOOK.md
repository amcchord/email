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

## API Restart Behaviour

An API restart should take a few seconds and should not fail a terminal check-in.
Four pieces work together:

| Piece | Value | Why |
| --- | --- | --- |
| `events.end_streams_on_sigterm` | Streams end within 1 second of SIGTERM | An open tab holds `/api/events/stream`. uvicorn waits for every open response and gives it no shutdown signal, so one tab used to hold a restart until systemd's 90-second SIGKILL (19:57 and 20:04 UTC on 2026-11-01). |
| `--timeout-graceful-shutdown` | 15 | Other requests get 15 seconds to finish, then uvicorn cancels them. In the Caddy log for 2026-10-16 to 2026-11-01, 161 of about 136,000 requests took longer than 15 seconds: 146 terminal image or schedule fetches and 15 others. |
| `TimeoutStopSec` | 25 | Backstop for the whole unit: 15 seconds of drain, up to 5 for lifespan shutdown, and 5 of margin. |
| Caddy `lb_try_duration` | 30s on `/api/*` and `/terminal/*` | Holds requests through the restart instead of returning 502. |

The Caddy hold matters because of how terminals fail. The firmware
(`reTerminalColor`, `src/main.cpp`) sleeps 300 seconds after any check-in that
is not a 200, and its read timeout is 20 seconds. One 502 therefore leaves a
terminal stale for about 5 minutes. Without the hold, new connections during a
restart wait in the supervisor's backlog, because it keeps the listening socket,
and then get a 502. The 19:57 restart produced 20 502s on API and terminal routes,
13 of them after waiting more than 30 seconds.

Expect these results:

- With a tab open and nothing slow in flight, a restart takes a few seconds and
  logs no error. The tab reconnects by itself.
- With a slow request in flight, the restart takes up to 15 seconds and logs
  `ERROR: Cancel N running task(s), timeout graceful shutdown exceeded`. Held
  requests then wait about 18 seconds, which is just inside the terminal read
  timeout. If lifespan shutdown also uses its full 5 seconds, a terminal can time
  out and sleep for 5 minutes.
- A request cancelled at 15 seconds logs `Exception in ASGI application` with a
  `CancelledError` traceback, and the client gets a 500 that is not retried. Check
  that the action was safe to repeat.

The hold has limits. Caddy retries a failed connection for any method, but once a
connection is accepted it retries only GET. A POST that lands in the backlog during
a drain still gets a 502, though this window is normally under a second. A GET can
run twice if the process dies while handling it. During a real outage, requests
wait 30 seconds before their 502.

### Apply on production (Mutating)

Only perform this when the user explicitly requests it. It needs three separate
steps because neither a deployment nor a Caddy reload changes the installed unit:
`scripts/setup/steps/services.py` and the README only apply to new installs.

1. Fast-forward `/opt/mail` to the reviewed commit, as in Production Deployment.
2. Validate and reload Caddy, which also closes open streams once:

   ```bash
   caddy validate --config /opt/mail/Caddyfile
   systemctl reload caddy
   ```

3. Add the unit drop-in. It takes effect at the next restart and leaves the
   installed unit file untouched:

```bash
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

4. Close signed-in tabs, then run `systemctl restart mailapp`. This restart stops
   the old code, so an open tab would hold it to the new 25-second limit, past the
   terminal read timeout. Only the next restart proves the change.

To roll back, remove the drop-in, then run `systemctl daemon-reload` and restart:

```bash
rm /etc/systemd/system/mailapp.service.d/graceful-shutdown.conf
```

Revert the Caddyfile through Git and reload Caddy.

### Verify with a connection open (Mutating: restarts the API)

Only an in-flight response holds a worker. An idle TCP connection is closed at
once and proves nothing, so use a real stream: open a signed-in tab at
`https://email.mcchord.net`. In a second shell, watch health through the proxy:

```bash
while sleep 0.5; do curl -s -o /dev/null -w '%{http_code} %{time_total}\n' https://email.mcchord.net/api/health; done
```

Then on the host:

```bash
journalctl --no-pager -u mailapp --since "$(systemctl show mailapp -p ActiveEnterTimestamp --value)" -o cat | grep -c 'GET /api/events/stream'
systemd-cgls --no-pager -u mailapp.service
since=$(date -u '+%F %T')
time systemctl restart mailapp
journalctl --no-pager -u mailapp --since "$since" -o cat | grep -E 'Cancel [0-9]+ running|stop-sigterm|Finished server process|Failed with result'
tail -n 2000 /var/log/caddy/mail.log | grep -cE '"status": ?502'
```

The first command must report at least 1. Run the last command once before the
restart as well, because it counts recent 502s and only an increase matters. The
change holds when all of these are true:

- `systemctl restart` returns within a few seconds.
- The health loop shows only 200s, with a slower response or two during the restart.
- The log shows `Finished server process`, and no `stop-sigterm` or `Failed with
  result`. A `Cancel N running` line only means a slow request was in flight.
- The 502 count did not increase.
- Terminals keep their normal request rate over the next 10 minutes.

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
