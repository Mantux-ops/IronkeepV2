# IronkeepV2 — Production Deployment Runbook

This document covers everything needed to run IronkeepV2 in a stable production
environment on a Linux server (VPS, bare-metal, or similar). No cloud provider,
container runtime, or orchestrator is assumed or required.

---

## Architecture Overview

IronkeepV2 runs as **two independent OS processes**:

| Process | Command | Responsibility |
|---------|---------|----------------|
| **Web** | `uvicorn app.main:app` | Serves the HTTP application (FastAPI + Jinja2) |
| **Scheduler** | `python -m app.scheduler` | Background jobs: dispatch retries, metadata refresh, operation reminders |

Both processes share the same SQLite database file. SQLite WAL mode is enabled
automatically on first start, allowing concurrent reads from both processes
without lock contention.

---

## Requirements

- Python 3.11+ (3.12 recommended)
- pip or a venv with `requirements.txt` installed
- A Linux user account for the service (e.g. `ironkeep`)
- A writable directory for the database file
- Outbound HTTPS access for Discord API calls

---

## Environment Variables

Set these in a `.env` file (do **not** commit it) or in your systemd unit's
`EnvironmentFile=` directive.

### Required in production

| Variable | Description | Example |
|----------|-------------|---------|
| `IRONKEEP_ENV` | Must be `production` to enable strict checks and secure cookies | `production` |
| `IRONKEEP_SESSION_SECRET` | Random 64-hex-char string for session signing. **Must not be the dev default.** | *(see below)* |
| `IRONKEEP_DB_PATH` | Absolute path to the SQLite database file | `/var/lib/ironkeep/ironkeep_v2.db` |

Generate the session secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Required for Discord features

| Variable | Description |
|----------|-------------|
| `DISCORD_BOT_TOKEN` | Discord bot token — required for posting announcements, rosters, and dispatch retries |
| `DISCORD_CLIENT_ID` | Discord application client ID — required for OAuth login |
| `DISCORD_CLIENT_SECRET` | Discord application client secret — required for OAuth login |
| `DISCORD_OAUTH_REDIRECT_URI` | Must match the redirect URI registered in the Discord Developer Portal |
| `WEB_BASE_URL` | Public URL of the web app (e.g. `https://ironkeep.example.com`) — used for embed signup links |

### Optional / scheduler

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEDULER_ENABLED` | *(unset)* | Set to `1` to allow the scheduler process to start |
| `SCHEDULER_POLL_SECONDS` | `300` | How often the scheduler runs its jobs (seconds) |
| `DISCORD_DISPATCH_ENABLED` | *(unset)* | Set to `1` for the scheduler to execute live Discord dispatch retries |

### Safety rule

> **Never put secrets in `scripts/`, `app/`, or source control.**
> Use a `.env` file outside the project directory, systemd `EnvironmentFile=`,
> or your host's secrets manager.

---

## First-Time Setup

```bash
# 1. Clone and install dependencies
git clone <repo> /opt/ironkeep
cd /opt/ironkeep
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Create the database directory
mkdir -p /var/lib/ironkeep
chown ironkeep:ironkeep /var/lib/ironkeep

# 3. Create the environment file (outside the repo)
cat > /etc/ironkeep/ironkeep.env << 'EOF'
IRONKEEP_ENV=production
IRONKEEP_SESSION_SECRET=<generated-secret>
IRONKEEP_DB_PATH=/var/lib/ironkeep/ironkeep_v2.db
DISCORD_BOT_TOKEN=<your-token>
DISCORD_CLIENT_ID=<your-client-id>
DISCORD_CLIENT_SECRET=<your-client-secret>
DISCORD_OAUTH_REDIRECT_URI=https://ironkeep.example.com/auth/discord/callback
WEB_BASE_URL=https://ironkeep.example.com
EOF
chmod 600 /etc/ironkeep/ironkeep.env
```

---

## Starting the Application

### Web process

```bash
source /opt/ironkeep/.venv/bin/activate
source /etc/ironkeep/ironkeep.env  # or export vars individually

uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --log-level info
```

> **Workers must be 1.** SQLite does not support multi-process write concurrency
> through connection pooling. The WAL mode allows concurrent *reads* but all
> *writes* are serialised through the single connection model. Increasing workers
> without a proper write queue will cause locking errors.

See also: `scripts/run_app.sh`

### Scheduler process

```bash
source /opt/ironkeep/.venv/bin/activate
source /etc/ironkeep/ironkeep.env

SCHEDULER_ENABLED=1 \
DISCORD_DISPATCH_ENABLED=1 \
python -m app.scheduler
```

The scheduler runs in an infinite loop with a configurable sleep between
iterations (`SCHEDULER_POLL_SECONDS`, default 5 minutes). It is safe to restart
at any time — all jobs use claim/finalize patterns to avoid duplicate work.

See also: `scripts/run_scheduler.sh`

---

## SQLite / WAL Notes

IronkeepV2 uses SQLite with Write-Ahead Logging (WAL) mode enabled on first
startup. This affects how you handle the database files.

**There are always up to three files:**

| File | Purpose |
|------|---------|
| `ironkeep_v2.db` | Main database file |
| `ironkeep_v2.db-wal` | WAL log (pending writes not yet checkpointed) |
| `ironkeep_v2.db-shm` | Shared memory index for the WAL |

**Rules:**
- Never copy `ironkeep_v2.db` alone at the OS level while the app is running —
  the WAL file may contain uncommitted data not yet merged.
- Use `scripts/backup_db.py` which calls Python's `sqlite3.Connection.backup()`
  API for a consistent, WAL-aware snapshot. This is safe to run while the app
  is live.
- WAL files are automatically checkpointed by SQLite. A large WAL file (visible
  on the diagnostics page) is not an error, but a very large WAL (> 100 MB)
  may indicate the checkpoint is blocked.

---

## Backup Procedure

### Creating a backup (live, WAL-aware)

```bash
# Writes a timestamped backup to /var/lib/ironkeep/backups/
python scripts/backup_db.py \
  --dest /var/lib/ironkeep/backups/ironkeep_backup_$(date +%Y%m%d_%H%M%S).db

# Or let the script generate the filename automatically
python scripts/backup_db.py --backup-dir /var/lib/ironkeep/backups/
```

The script uses `sqlite3.Connection.backup()` — no CLI, no file copy, always
WAL-consistent.

### Verifying a backup

```python
import sqlite3
from app import startup

conn = sqlite3.connect("/var/lib/ironkeep/backups/ironkeep_backup_YYYYMMDD.db")
startup.check_core_tables(conn)  # raises if required tables missing
startup.check_integrity(conn)    # raises if PRAGMA integrity_check fails
conn.close()
print("Backup OK")
```

### Recommended backup schedule

IronkeepV2 has no built-in scheduled backup. Add a cron job or systemd timer:

```cron
# Daily backup at 03:00, keep 7 days
0 3 * * * ironkeep /opt/ironkeep/.venv/bin/python \
    /opt/ironkeep/scripts/backup_db.py \
    --backup-dir /var/lib/ironkeep/backups/ \
  && find /var/lib/ironkeep/backups/ -name "ironkeep_backup_*.db" \
     -mtime +7 -delete
```

---

## Restore Procedure

> **Restore is a manual operator step.** There is no automated or UI-driven
> restore. Follow this procedure carefully to avoid data loss.

```bash
# 1. Stop both processes
systemctl stop ironkeep-app ironkeep-scheduler

# 2. Verify the backup file is intact
python - << 'EOF'
import sqlite3
from app import startup
conn = sqlite3.connect("/var/lib/ironkeep/backups/ironkeep_backup_YYYYMMDD.db")
startup.check_core_tables(conn)
startup.check_integrity(conn)
conn.close()
print("Backup integrity OK — safe to restore")
EOF

# 3. Take a safety copy of the current database
cp /var/lib/ironkeep/ironkeep_v2.db \
   /var/lib/ironkeep/ironkeep_v2.db.pre-restore

# 4. Replace the database files
cp /var/lib/ironkeep/backups/ironkeep_backup_YYYYMMDD.db \
   /var/lib/ironkeep/ironkeep_v2.db
# Remove stale WAL/SHM so the restored DB starts clean
rm -f /var/lib/ironkeep/ironkeep_v2.db-wal \
      /var/lib/ironkeep/ironkeep_v2.db-shm

# 5. Restart
systemctl start ironkeep-app ironkeep-scheduler

# 6. Check /workspaces/<slug>/settings/diagnostics
```

> **Data loss warning:** Any operations, events, or ledger entries created
> after the backup was taken will be permanently lost.

---

## Health Check Usage

### JSON health endpoint (unauthenticated)

```bash
curl -s https://ironkeep.example.com/health | python -m json.tool
```

Expected healthy response:
```json
{
  "status": "ok",
  "db_reachable": true,
  "wal_mode": true,
  "scheduler": "ok",
  "scheduler_last_seen_at": "2026-05-16T20:05:00+00:00",
  "pending_retries": 0,
  "recent_error_runs_24h": 0
}
```

Returns HTTP 503 if the database is unreachable or a scheduler job is stuck.

Use this endpoint for:
- Uptime monitoring (e.g. UptimeRobot, Checkly, Prometheus blackbox exporter)
- Load-balancer health checks
- Post-deploy smoke tests

### Diagnostics page (authenticated, officer/owner)

Navigate to `/workspaces/<slug>/settings/diagnostics` to see:
- Database reachability, WAL mode, file size, last modified
- Scheduler health banner (ok / stale / stuck / never_run)
- Pending retry backlog (global and workspace-scoped)
- Backup & recovery guidance
- Links to the JSON health endpoint and full scheduler status

---

## Rollback Procedure

If a code deployment causes failures:

```bash
# 1. Stop the web process
systemctl stop ironkeep-app

# 2. Roll back the code
cd /opt/ironkeep
git checkout <previous-tag-or-commit>

# 3. Re-install dependencies in case they changed
source .venv/bin/activate
pip install -r requirements.txt

# 4. Restart
systemctl start ironkeep-app
```

Schema migrations in IronkeepV2 are additive only (`ALTER TABLE ... ADD COLUMN`).
Rolling back code does not require rolling back the database — new columns will
simply be ignored by the older code. If a rollback requires removing a table or
column, that must be planned separately.

---

## Log Locations

When running under systemd, logs are captured by journald:

```bash
# Web process logs
journalctl -u ironkeep-app -f

# Scheduler logs
journalctl -u ironkeep-scheduler -f

# Last 100 lines from both
journalctl -u ironkeep-app -u ironkeep-scheduler -n 100
```

---

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---------|-------------|------------|
| App refuses to start with "IRONKEEP_SESSION_SECRET must be set" | `IRONKEEP_ENV=production` but no secret | Generate and set `IRONKEEP_SESSION_SECRET` |
| App refuses to start with "Database directory does not exist" | `IRONKEEP_DB_PATH` parent dir missing | `mkdir -p` the directory |
| Login page shows "Discord OAuth not configured" | OAuth env vars missing | Set `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_OAUTH_REDIRECT_URI` |
| Discord posts fail at runtime | `DISCORD_BOT_TOKEN` not set | Set the token and restart the web process |
| Scheduler stuck banner on diagnostics page | Scheduler process crashed or not started | Check `journalctl -u ironkeep-scheduler` and restart |
| Large WAL file (> 50 MB) | WAL checkpoint blocked by a long-running read | Restart the web process; checkpoint runs on connection open |
| `database or disk is full` SQLite error | Disk space exhausted | Free disk space; consider moving DB to a larger volume |
