# Ironkeep

**Tactical operations platform for Albion Online guilds and alliances.**

Ironkeep helps officers plan compositions, run signups, assign slots, track readiness, post to Discord, and lock rosters — in one server-rendered workspace. It is built for structured CTAs and alliance-scale coordination, not generic guild chat management.

This repository (`IronkeepV2`) is the current codebase. User-facing product name is **Ironkeep**.

---

## Status

| | |
|---|---|
| **Stage** | Pre-alliance trial — pilot / alliance-trial ready, not a final public release |
| **Milestone tag** | `pre-alliance-trial` (see git tags for the current baseline) |
| **Test suite** | 2,400+ tests (~93 test files) |
| **Production readiness** | Suitable for controlled pilot and alliance trial use; follow pre-live checklists before sharing signup links |

Ironkeep is actively developed. Capabilities below reflect what is implemented today, not a marketing roadmap.

---

## Capabilities

### Build & composition library

- **Build Library** — reusable Albion builds per workspace, with role-aware presentation
- **CSV / paste build import** — bulk import builds without manual re-entry
- **Composition Library** — named compositions with slot templates and party structure
- **Tactical party layout preview** — role tallies, party grouping, and gap signals on composition surfaces
- **Operation creation from composition** — start an operation from an existing comp
- **Slot generation** — generate operation slots from composition templates

### Signup & assignment

- **Open alliance signup links** — shareable URLs for operation signups
- **Non-member signup support** — authenticated users outside the workspace can sign up when links are open
- **Assignment planner** — party-grouped slot assignment with tactical density
- **Quick Assign / Quick Fill** — accelerated assignment workflows for officers under time pressure

### Operational command

- **Readiness tracking** — slot fill, role gaps, and readiness state in the planner
- **Roster locking** — freeze assignments when the operation is ready to go live
- **Discord announcements with signup links** — post operation announcements with embed signup buttons
- **Discord roster previews / posts** — formatted roster output for Discord channels

### Foundation & discipline

- **Attendance recording** — mark presence, late, absent, and related states for assigned participants
- **Player reliability scores** — attendance-derived reliability surfaced in planner context
- **Payout ledger foundation** — domain events and data model for regear / payout tracking (officer workflows documented in pilot onboarding; not a full automated payout product)
- **Design doctrine & operational UI system** — three visual registers (public, administrative, operational), token-based CSS, and testable UI contracts

---

## Architecture

Ironkeep is a **server-rendered tactical operations stack** — no SPA, no frontend framework, no build pipeline for UI.

| Layer | Technology |
|---|---|
| **Web app** | FastAPI + Jinja2 templates |
| **Database** | SQLite with WAL mode — single shared file, workspace-scoped data |
| **Discord** | Separate bot process (`bot/`) — thin adapter; business logic stays in `app/` |
| **Scheduler** | Independent process for retries, reminders, and metadata refresh |
| **Static UI** | Layered CSS (`app/static/css/`) — tokens, components, tactical register, landing |

**Process model:** web + scheduler (+ optional Discord bot) share one SQLite database. No Redis, no external queue, no container runtime required for development or typical self-hosted deployment.

**Maturity note:** The architecture is deliberate and stable for pilot use. Operational surfaces (planner, readiness, assignments) are the most exercised paths; administrative and public surfaces continue to evolve under the design doctrine.

---

## Quick Start (Development)

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open **http://localhost:8000**.

In dev mode (`IRONKEEP_ENV` unset or `dev`), Discord OAuth is bypassed — use the dev login form with any display name.

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Optional — scheduler (second terminal)

Background jobs (retries, reminders) require the scheduler process:

```powershell
# Windows
$env:SCHEDULER_ENABLED = "1"
python -m app.scheduler
```

```bash
# macOS / Linux
SCHEDULER_ENABLED=1 python -m app.scheduler
```

Discord posting additionally requires `DISCORD_BOT_TOKEN`, workspace Discord settings, and `WEB_BASE_URL` when signup links must resolve outside localhost. See [docs/deployment.md](docs/deployment.md) and [docs/pilot_onboarding.md](docs/pilot_onboarding.md).

---

## Running Tests

The suite contains **2,400+ tests** (2,413 collected as of the latest testing-strategy audit). Tests use isolated in-memory SQLite — no external services required.

```bash
pytest
```

**Do not run the full suite by default during routine development.** Validation effort should match change risk.

Follow **[docs/testing_strategy.md](docs/testing_strategy.md)** for the risk-scaled validation matrix:

- **Tier 0** — docs / pure CSS (no pytest)
- **Tier 4a / 4b** — targeted or full UI validation for template and presentation changes
- **Tier 5** — full regression suite (~22 minutes); reserved for end-of-session checkpoints, pre-release gates, and high-blast-radius changes

Example targeted run:

```bash
pytest tests/test_tactical_logic.py -q
```

---

## Documentation

| Document | Description |
|---|---|
| [docs/design_doctrine.md](docs/design_doctrine.md) | Visual and interaction constitution — public, administrative, and operational registers |
| [docs/testing_strategy.md](docs/testing_strategy.md) | Validation tiers, risk matrix, and when to run full regression |
| [docs/integrated_composition_builder_foundation.md](docs/integrated_composition_builder_foundation.md) | Composition builder, build library, and tactical workflow foundation |
| [docs/ui_architecture_system.md](docs/ui_architecture_system.md) | CSS architecture, component taxonomy, and naming |
| [docs/pre_live_final_checklist.md](docs/pre_live_final_checklist.md) | Final checks before sharing alliance signup links |
| [docs/pre_weekend_live_trial_checklist.md](docs/pre_weekend_live_trial_checklist.md) | Operational dry-run checklist for a live trial weekend |
| [docs/deployment.md](docs/deployment.md) | Production deployment — env vars, process supervision, WAL, backup, health checks |
| [docs/pilot_onboarding.md](docs/pilot_onboarding.md) | Guild officer onboarding — Discord setup, first workspace, operation workflow |
| [docs/security_notes.md](docs/security_notes.md) | Secrets handling, token rotation, SQLite sensitivity |
| [docs/launch_checklist.md](docs/launch_checklist.md) | Pre-launch readiness checklist |
| [docs/ironkeepv2_roadmap.md](docs/ironkeepv2_roadmap.md) | Roadmap, completed slices, architecture decisions |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
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

Store secrets in a local `.env` file (see Security below). Never commit `.env` to git.

---

## Health Check

```bash
curl http://localhost:8000/health
```

Returns JSON with scheduler status, DB reachability, and pending retry count. HTTP 503 indicates degraded state.

---

## Scripts

| Script | Description |
|---|---|
| `scripts/run_app.sh` | Start the web process (production) |
| `scripts/run_scheduler.sh` | Start the scheduler process (production) |
| `scripts/backup_db.py` | Create a WAL-aware SQLite backup |

```bash
python scripts/backup_db.py --backup-dir ./backups/ --verify
```

---

## Project Structure

```
app/
  main.py                     FastAPI entry point and lifespan
  routes.py                   HTTP routes (thin: parse → use case → render/redirect)
  routes_auth.py              Auth and workspace view helpers
  repositories.py             Database access — workspace-scoped
  database.py                 SQLite connection, schema init, transactions
  tactical.py                 Role family classification and tactical summaries
  application/
    use_cases.py              Business logic, RBAC, operational events
  domain/
    albion_builds.py          Build validation and domain rules
    albion_compositions.py    Composition validation
    guild_operations.py       Operation status machine
    readiness.py              Pure readiness calculation
    ...                       Additional domain modules
  discord/                    Formatters, dispatcher, adapter (no business logic)
  scheduler/                  Background jobs
  static/css/                 Token-based CSS layers (tokens, tactical, landing, …)
  templates/
    builds_*.html             Build library surfaces
    compositions_*.html       Composition library and builder
    operation_planner.html    Tactical assignment planner
    landing.html              Public landing page
    workspace_dashboard.html  Workspace entry dashboard
    ...                       Additional Jinja2 templates
bot/                          Discord bot process (separate requirements)
docs/                         Doctrine, testing strategy, checklists, deployment
tests/                        pytest suite (2,400+ tests)
scripts/                      Production helper scripts
```

---

## Security & Secrets

This is a **private repository**. Do not distribute without permission.

- **Never commit `.env`** or any file containing Discord tokens, session secrets, or production credentials
- **Never commit Discord bot tokens** — rotate immediately if one is exposed
- **Keep deployment secrets outside the repo** — use environment variables or a secrets manager on the host
- **`.gitignore` protects common local files** — `.env`, `*.db`, virtual environments, pytest caches, and local backup directories

See [docs/security_notes.md](docs/security_notes.md) for token rotation, SQLite file sensitivity, and production hardening guidance.

---

## License

Private repository. Do not distribute without permission.
