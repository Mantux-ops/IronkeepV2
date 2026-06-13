# IronkeepV2 — Progress Checkpoint

*Last updated: 2026-05-22*

---

## 1. Completed Slices

| # | Slice | Key deliverable |
|---|---|---|
| 1 | **Auth Foundation** | Users table, workspace membership, roles (owner/officer/member), dev login, server-side role enforcement, `AuthenticationRequired` / `PermissionDenied` errors, auth helpers that raise rather than redirect |
| 2 | **UI Foundation** | Consistent layout system (`base.html`), workspace nav, operation tabs, flash messages, page header partials, improved tables/forms/badges across all 14+ templates. Presentation-only — no domain changes |
| 3 | **Discord Integration Boundary Design** | `docs/discord_integration_boundary.md` — architectural principles, source-of-truth rules, adapter boundaries, OperationalEvent → Discord mapping, identity/linking strategy, explicit anti-patterns from old Ironkeep |
| 4 | **Discord Infrastructure Foundation** | Discord config columns on `guild_workspaces`, `signup_intents.source` column, `discord_messages` table, `discord_dispatch_failures` table, repository helpers, `app/discord/` module skeleton |
| 5 | **Post-commit Event Dispatch Foundation** | `TransactionContext` wrapper (sidesteps C-extension attribute limit on `sqlite3.Connection`), post-commit dispatch loop in `database.transaction()`, `app/events.py` with `DISPATCHABLE_EVENT_TYPES` allowlist, `_record_failure` in separate transaction, `insert_operational_event` appends to `pending_dispatch` |
| 6 | **Discord Workspace Configuration UI** | `GET/POST /workspaces/{slug}/settings/discord`, snowflake validation (digits-only, 15–20 chars), `discord_guild_id` uniqueness, `workspace.discord_config.updated` event, Settings nav link hidden from members |
| 7 | **Discord Formatter Foundation** | `app/discord/formatters.py` — four pure functions: `format_operation_announcement`, `format_readiness_summary`, `format_roster`, `format_signup_confirmation`. No SDK, no DB access, deterministic JSON-serialisable output |
| 8 | **Discord Identity Resolution Foundation** | `app/discord/identity.py` — `DiscordNotLinkedError`, `DiscordUserNotLinkedError`, `DiscordUserNotWorkspaceMemberError` (all `IronkeepError` subclasses), `resolve_workspace_from_discord_guild`, `resolve_user_from_discord_id`, `resolve_member_from_discord`, `get_discord_identity_context` |
| 9 | **Discord Command Adapter Foundation** | `app/discord/adapter.py` — `handle_signup_command`, `handle_readiness_command`, `handle_roster_command`, `handle_checkin_command`. Plain dict payloads in, plain dict interaction responses out. Signup uses `source='discord'`. All `IronkeepError` → ephemeral error response |
| 10 | **Discord Dispatcher Foundation** | `app/discord/dispatcher.py` — `resolve_action(event, db)` routing table, `dispatch(event)` post-commit hook. Events route to `post_message` / `edit_message` / `noop`. Checks `discord_messages` for edit vs post. Missing config → noop, never raises |

---

## 2. Current Architecture

```
app/
  main.py                     FastAPI app entry point
  database.py                 SQLite connection, TransactionContext, transaction()
  repositories.py             Raw SQL — all DB access, all workspace-scoped
  routes.py                   HTTP routes — thin: parse → use case → render/redirect
  routes_auth.py              Route-layer auth helpers (resolve_workspace_view, etc.)
  events.py                   Post-commit dispatch: DISPATCHABLE_EVENT_TYPES, dispatch_event
  errors.py                   Shared error hierarchy (IronkeepError subclasses)
  schema.sql                  Authoritative schema (16 tables, ~30 indexes)

  application/
    use_cases.py              Transactional commands — every command emits ≥1 OperationalEvent

  domain/
    guild_workspace.py        Workspace name/slug/snowflake validation
    guild_operations.py       Status machine, status-gated validation helpers
    operational_events.py     Event type constants, make_event factory
    operation_plans.py        Plan validation (role, willingness, availability)
    readiness.py              Pure readiness calculation (no DB)
    mass_planner.py           Candidate scoring / slot assignment sorting
    attendance.py             Attendance status validation
    scout_attendance.py       Scout/support role_type validation
    workspace_membership.py   Role constants and capability checks
    users.py                  Dev auth provider ID derivation
    albion_compositions.py    Composition validation

  auth/
    session.py                Cookie-based session read/write
    current_user.py           get_current_user / require_current_user helpers
    workspace_access.py       Membership resolution helpers

  discord/
    __init__.py               Package marker with design notes
    adapter.py                Command handlers (plain dict in → plain dict out)
    dispatcher.py             resolve_action() + dispatch() post-commit hook
    formatters.py             Pure formatting functions (no DB, no SDK)
    identity.py               Discord ↔ app identity resolution + typed errors
    message_store.py          Skeleton (Phase 2)
    rate_limiter.py           Skeleton (Phase 2)

  templates/                  Jinja2 server-rendered HTML (18 templates)
```

### Data flow (write path)

```
HTTP POST  ──►  route  ──►  use_case()
                               │
                  database.transaction()
                               │
                    repositories.insert_*(db, ...)
                    repositories.insert_operational_event(db, event)
                       → db.pending_dispatch.append(event)
                               │
                  conn.commit()  ← domain transaction ends here
                  conn.close()
                               │
                  post-commit dispatch loop
                    events.dispatch_event(event)
                      → dispatcher.dispatch(event)
                          → dispatcher.resolve_action(event, db_read)
                          → Phase 1: log action
                          → Phase 2: Discord REST call
```

### Key design decisions

- `sqlite3.Connection` is a C extension type that rejects arbitrary attributes. `TransactionContext` wraps it and owns `pending_dispatch: list[dict]`. All connection methods delegate via `__getattr__`.
- Repositories append to `pending_dispatch` only when `db` is a `TransactionContext` (checked via `getattr(db, "pending_dispatch", None)`). Bare connections (tests, `init_schema`) are unaffected.
- Dispatch is post-commit, synchronous, best-effort. A dispatcher failure writes to `discord_dispatch_failures` in a separate transaction and does not affect the committed domain data.
- Discord is a communication surface only. The adapter calls the same use cases the web UI calls. The dispatcher reads DB state to build message payloads. Neither owns business logic.

---

## 3. Core Invariants

| Invariant | Enforcement |
|---|---|
| Every state-changing command emits ≥1 OperationalEvent in the same transaction | Use case convention; `no event = no commit` rule documented |
| OperationalEvents are append-only and immutable | No UPDATE/DELETE on `operational_events` |
| All entity queries are workspace-scoped | Every repository function accepts and filters by `guild_workspace_id` |
| Operation slots are a frozen snapshot | Slots are copied from composition templates at generate time; template changes do not affect slots |
| At most one active assignment per participant per operation | Partial unique index on `assignments(workspace_id, operation_id, participant_id) WHERE status = 'assigned'` |
| A slot is "filled" iff an active assignment row exists | No status column on `operation_slots`; assignment state is always derived |
| Workspace membership misses do not leak workspace existence | Routes return 404 for both not-found and non-member cases |
| POST routes enforce role server-side | Hidden buttons are not security; `authz.authorize_workspace_action` checked before every mutation |
| Discord config uniqueness | `discord_guild_id` has a UNIQUE constraint; use case also checks before writing |
| Dispatch failures never roll back committed data | `_record_failure` uses a separate `database.transaction()`; `dispatch_event` wraps `dispatcher.dispatch` in try/except |

---

## 4. Current Discord Boundary Status

### What is wired end-to-end (no live bot required)

| Layer | Status |
|---|---|
| Schema (`discord_guild_id`, channels, `discord_messages`, `discord_dispatch_failures`) | ✅ Complete |
| Repository helpers (workspace by guild ID, upsert/get discord message, failure insert) | ✅ Complete |
| Workspace config UI (GET/POST `/settings/discord`, snowflake validation) | ✅ Complete |
| Post-commit event dispatch pipeline | ✅ Complete — wired, `dispatcher.dispatch` called after every commit |
| `DISPATCHABLE_EVENT_TYPES` allowlist | ✅ `workspace.created`, `guild_operation.published/locked/completed`, `readiness_snapshot.created`, `signup_intent.submitted`, `scout/support_attendance.recorded` |
| Formatters (announcement, readiness, roster, signup confirmation) | ✅ Pure, tested, JSON-serialisable |
| Identity resolution (`discord_guild_id → workspace`, Discord user snowflake → app user, membership check) | ✅ Complete — all three typed errors |
| Command adapter (signup, readiness, roster, checkin) | ✅ Complete — plain dict in/out, `IronkeepError` → ephemeral error response |
| Dispatcher action resolution (post/edit/noop routing table) | ✅ Complete — reads DB state, calls formatters, checks `discord_messages` for edit vs post |

### What is still a skeleton / no-op

| Component | State |
|---|---|
| `dispatcher.dispatch()` — executes action | Logs only. No Discord API call made. |
| `app/discord/message_store.py` | Skeleton |
| `app/discord/rate_limiter.py` | Skeleton |
| Discord OAuth / user account linking | Not implemented. Dev login only. |
| Bot gateway / slash command registration | Not implemented. |

### The one missing link to a live bot

The entire stack from event → formatter → message payload is fully wired. The only gap between Phase 1 and a working bot is replacing the `pass` / log in `dispatch()` with a real HTTP POST to `discord.com/api/channels/{id}/messages`. All supporting infrastructure — identity, formatters, action routing, failure recording — is in place.

---

## 5. What Is Intentionally Still Excluded

The following are explicitly out of scope for the current phase and must not be added without a new slice proposal:

- **Discord OAuth** — user identity linking is manual/future; dev login only
- **Discord gateway / bot process** — no `discord.py`, `nextcord`, or any SDK
- **Slash command registration** — commands are not registered with Discord
- **Discord API calls** — no outbound HTTP to Discord
- **Scheduler / background workers** — no Celery, Redis, APScheduler, asyncio queues
- **Outbox / event sourcing / CQRS** — dispatch is synchronous and best-effort
- **Recruitment flows** — no application/trial/probation tracking
- **Payouts / regear** — no silver or item compensation tracking
- **Watchlists** — no player watchlisting
- **Voice tracking** — no Discord voice channel activity
- **Role sync** — no Discord server role management
- **Web buttons / Discord components** — no interactive message components
- **Roster post as explicit officer action** — the "Post Roster to Discord" use case is designed but not implemented
- **Analytics / billing** — none
- **Frontend framework / Tailwind** — plain HTML/CSS only
- **WebSockets / drag-and-drop** — none

---

## 6. Test Count and Key Coverage Areas

**Total: 1945 tests, 0 failures** (as of 2026-05-22, Tier 5 full suite)

*Note: suite grew from 381 (2026-05-11) to 1945 through the composition builder phases (1–6 Slice 2), doctrine identity, and assignment workflow additions. Full summary in `docs/integrated_composition_builder_foundation.md`.*

| Test file | Tests | Coverage area |
|---|---|---|
| `test_vertical_slice.py` | ~15 | End-to-end operation lifecycle via HTTP |
| `test_operation_lifecycle.py` | ~12 | Operation status transitions |
| `test_operation_mutation_status_rules.py` | ~10 | Status-gated mutation guards |
| `test_signup_status_rules.py` | ~8 | Signup allowed/blocked by operation status |
| `test_assignment_lifecycle.py` | ~12 | Assign, remove, re-assign, slot exclusivity |
| `test_planner_sorting.py` | ~10 | Candidate scoring and slot ranking |
| `test_quick_assign.py` | ~8 | Quick-assign and quick-fill flows |
| `test_readiness_v2.py` | ~10 | Readiness snapshot calculation |
| `test_role_gap_readiness.py` | ~8 | Role and build gap tracking |
| `test_frozen_operation_slots.py` | ~6 | Slot immutability after generation |
| `test_guild_scoping.py` | ~8 | Cross-workspace boundary enforcement |
| `test_attendance.py` | ~10 | Attendance marking and status rules |
| `test_scout_attendance.py` | ~10 | Scout/support check-in, upsert behaviour |
| `test_reserve.py` | ~8 | Reserve / bench management |
| `test_operational_events.py` | ~10 | Event emission and payload correctness |
| `test_auth_dev_login.py` | ~5 | Dev login session creation |
| `test_workspace_membership.py` | ~5 | Member/officer/owner access control via HTTP |
| `test_add_workspace_member.py` | ~8 | Member addition, role validation |
| `test_signup_source.py` | ~5 | `source` column default and Discord value |
| `test_discord_schema.py` | ~15 | Discord table persistence layer |
| `test_discord_module_boundaries.py` | ~6 | Module importability, no SDK in requirements |
| `test_event_dispatch.py` | 10 | Post-commit dispatch: success, rollback, failure recording, allowlist, non-dispatchable skip |
| `test_discord_config_ui.py` | 35 | Snowflake validation, use case, routes, uniqueness, nav visibility |
| `test_discord_formatters.py` | 60 | All four formatters: structure, colors, gaps, roster grouping, JSON-serialisable, pure |
| `test_discord_identity.py` | 22 | All three error types, all resolution paths, wrong-workspace isolation |
| `test_discord_adapter.py` | 35 | All four handlers: success, error paths, source=discord, read-only verified |
| `test_discord_dispatcher.py` | 26 | Routing table, post/edit decision, workspace-scoped lookup, all noop conditions |

---

## 7. Recommended Next Implementation Options

Listed roughly by value-to-effort ratio. Each should be proposed and approved before implementation.

### High value, low risk

**A. Operation timeline page improvements**
The timeline page exists but could show which events triggered Discord actions and which were noops. Purely presentational, no schema change.

**B. Discord user identity linking UI**
Allow a workspace member to enter their Discord user snowflake from the web UI, storing it as `auth_provider='discord'` + `provider_user_id`. Unlocks the command adapter for users without OAuth. Small use case, one form page.

**C. Roster post as explicit officer action**
`POST /workspaces/{slug}/operations/{op_id}/discord/post-roster` — officer-initiated, calls `format_roster`, writes to `discord_messages`, emits `guild_operation.roster_posted` event. No live Discord API needed yet — stores the intended payload for review.

### Medium value, medium complexity

**D. Live Discord bot gateway (Phase 2 entry)**
Wire `dispatcher.dispatch()` to make actual Discord REST calls. The entire infrastructure is ready; this is adding `httpx` (or `discord.py` for gateway) and replacing the `pass` in `dispatch()` with an HTTP POST. Requires Discord bot token in config.

**E. Slash command registration + gateway handler**
Register commands with Discord, wire the gateway to parse `interaction.data` into the `payload` dict and call `adapter.handle_*_command`. The adapter is already fully implemented.

**F. `workspace.discord_config.updated` → Discord notification**
Add `workspace.discord_config.updated` to `DISPATCHABLE_EVENT_TYPES` and add a handler in the dispatcher that posts a setup confirmation to the officer channel. Useful as the first real end-to-end bot message.

### Lower priority / future phases

**G. Discord OAuth user linking**
Replace dev-only auth with Discord OAuth so users link their accounts automatically on first interaction. Requires a callback route and Discord application credentials.

**H. `discord_dispatch_failures` retry UI**
Admin page showing pending retry failures with manual resolve/dismiss actions.

**I. Rate limiter + retry strategy** (`app/discord/rate_limiter.py`)
Implement the skeleton to handle Discord 429 responses gracefully.

**J. Recruitment / payouts / regear**
Explicitly deferred. Design a new slice proposal before touching these.
