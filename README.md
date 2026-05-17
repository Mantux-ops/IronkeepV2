# IronkeepV2

Guild coordination platform for Albion Online. Manages the full lifecycle of
guild operations (CTAs): composition planning, player signup, slot assignment,
readiness tracking, attendance recording, and Discord communication.

---

## Architecture

- **Backend:** FastAPI + SQLite (WAL mode)
- **Frontend:** Jinja2 server-rendered templates — no JavaScript framework
- **Discord:** separate bot process (`bot/`), thin adapter only — no business logic
- **Scheduler:** independent process for background jobs (retries, reminders, metadata refresh)

Two processes, one shared SQLite database. No external queue, no Redis, no
container runtime required.

---

## Quick Start (Development)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start the web process
uvicorn app.main:app --reload

# Start the scheduler (separate terminal)
SCHEDULER_ENABLED=1 python -m app.scheduler
```

Open `http://localhost:8000`. In dev mode, Discord OAuth is bypassed — use the
dev login form with any display name.

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/deployment.md](docs/deployment.md) | Production deployment runbook — env vars, process supervision, WAL notes, backup/restore, health checks, rollback |
| [docs/launch_checklist.md](docs/launch_checklist.md) | Pre-launch readiness checklist — verify before onboarding a real guild |
| [docs/pilot_onboarding.md](docs/pilot_onboarding.md) | Guild officer onboarding guide — Discord setup, first workspace, operation workflow, payout ledger, known limitations |
| [docs/security_notes.md](docs/security_notes.md) | Security guidance — secrets handling, .env safety, Discord token rotation, SQLite sensitivity |
| [docs/ironkeepv2_roadmap.md](docs/ironkeepv2_roadmap.md) | Full project roadmap — completed slices, architecture decisions, invariants |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `IRONKEEP_ENV` | Production | `production` enables strict checks and secure cookies |
| `IRONKEEP_SESSION_SECRET` | Production | Strong random value for session signing |
| `IRONKEEP_DB_PATH` | Production | Absolute path to the SQLite database file |
| `DISCORD_BOT_TOKEN` | For Discord | Bot token for posting announcements and rosters |
| `DISCORD_CLIENT_ID` | For OAuth | Discord application client ID |
| `DISCORD_CLIENT_SECRET` | For OAuth | Discord application client secret |
| `DISCORD_OAUTH_REDIRECT_URI` | For OAuth | Callback URL registered in Discord Developer Portal |
| `WEB_BASE_URL` | For embeds | Public URL used in Discord embed signup links |
| `SCHEDULER_ENABLED` | Scheduler | Set to `1` to start the scheduler process |
| `DISCORD_DISPATCH_ENABLED` | Scheduler | Set to `1` for live Discord dispatch execution |

---

## Health Check

```bash
curl http://localhost:8000/health
```

Returns JSON with scheduler status, DB reachability, and pending retry count.
Returns HTTP 503 on degraded state. Use this for uptime monitoring.

---

## Running Tests

```bash
pytest
```

All tests use an isolated in-memory SQLite database. No external services
or environment variables are required to run the test suite.

---

## Scripts

| Script | Description |
|--------|-------------|
| `scripts/run_app.sh` | Start the web process (production) |
| `scripts/run_scheduler.sh` | Start the scheduler process (production) |
| `scripts/backup_db.py` | Create a WAL-aware SQLite backup |

```bash
# Create and verify a backup
python scripts/backup_db.py --backup-dir /var/lib/ironkeep/backups/ --verify
```

---

## Project Structure

```
app/
  main.py               FastAPI entry point and lifespan
  routes.py             HTTP routes (thin: parse → use case → redirect/render)
  repositories.py       Database access functions
  database.py           SQLite connection and schema init
  diagnostics.py        Health helpers (stale detection, UTC format, scheduler state)
  startup.py            Startup validation (DB writability, core tables, integrity)
  backup.py             WAL-aware backup utilities
  application/
    use_cases.py        Business logic (RBAC, domain rules, event emission)
  domain/               Pure domain validation (no DB, no HTTP)
  discord/              Formatters, dispatcher, adapter (no business logic)
  scheduler/            Background jobs (retry, metadata refresh, reminders)
  templates/            Jinja2 HTML templates
  auth/                 Session management, Discord OAuth, current user
bot/                    Discord bot process (separate requirements.txt)
scripts/                Production helper scripts
docs/                   Deployment, onboarding, security, roadmap
tests/                  pytest test suite (59 files, 1448 tests)
```

---

## License

Private repository. Do not distribute without permission.
See [docs/security_notes.md](docs/security_notes.md) for guidance on keeping
secrets out of version control.
