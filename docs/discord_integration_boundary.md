# Discord Integration Boundary Design

Design-only. No implementation. No Discord OAuth, bot code, slash commands, webhooks, queues, or scheduler jobs.

---

## 1. Architectural Principles

**P1. Application domain is the one source of truth.**
Every piece of operational data — signup, assignment, attendance, readiness — lives in the database and is owned by the application domain. Discord holds nothing. It renders and accepts commands.

**P2. Discord is a surface, not a system.**
The Discord bot is a thin I/O adapter. It translates Discord interaction payloads into application use-case calls and translates OperationalEvents into Discord API calls. It does not contain business logic.

**P3. Commands flow in; events and explicit officer actions flow out.**
Discord user interactions are inbound commands that call the same use cases that the web UI calls.
Automatic outbound Discord messages are driven by OperationalEvents after commit.
Explicit outbound actions, such as "Post Roster to Discord", are application use cases initiated from the web UI and recorded with OperationalEvents.

**P4. No Discord-first state mutations.**
No Discord interaction may mutate operational state that the application has not already modelled. There is no "Discord-only" state. A signup submitted via Discord is identical in schema to one submitted via the web form.

**P5. Bot absence is non-fatal.**
If the bot is offline, the application continues to function. The web UI is always the authoritative fallback. Outbound Discord messages are best-effort, not transactional guarantees.

**P6. Web-only operations remain web-only until explicitly promoted.**
Officer actions such as publishing an operation, generating slots, and assigning participants are web-only in V2. They may later gain Discord command surfaces, but that is a deliberate promotion, not a default.

---

## 2. Source-of-Truth Rules

| Data | Source of truth | Discord may... | Discord must never... |
|------|-----------------|----------------|-----------------------|
| GuildOperation existence and lifecycle | Application DB | Read and display | Create, delete, or transition |
| SignupIntent | Application DB | Accept submission via command | Overwrite, interpret, or merge |
| Assignment | Application DB | Display roster | Assign, move, or remove |
| AttendanceRecord | Application DB | Accept check-in signal | Mark final attendance, set excused/no-show |
| ReadinessSnapshot | Application DB | Display snapshot | Calculate or own readiness state |
| OperationSlot | Application DB | Display slot list | Modify slot definitions |
| Guild/workspace identity | Application DB | Link by stored Discord guild ID | Invent workspace scope |
| Message IDs for posted rosters | Application DB | Write back posted message ID | Drive workflow from stored message ID alone |
| User identity | Application DB | Verify Discord identity links | Be the only identity path in a workspace |

---

## 3. Adapter Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                       Application layer                      │
│  use_cases.py — identical functions called by web and bot   │
└──────────────────┬──────────────────────────────────────────┘
                   │ domain objects in / domain objects out
         ┌─────────┴──────────┐
         │                    │
┌────────▼──────┐    ┌────────▼──────────────┐
│  Web routes   │    │  Discord adapter       │
│  (routes.py)  │    │  (app/discord/)        │
│               │    │  ┌──────────────────┐  │
│  Renders HTML │    │  │ CommandHandler   │  │
│  Returns HTTP │    │  │ EventDispatcher  │  │
└───────────────┘    │  └──────────────────┘  │
                     └────────────┬───────────┘
                                  │ Discord SDK objects
                     ┌────────────▼───────────┐
                     │  Discord API / Gateway  │
                     └────────────────────────┘
```

**`app/discord/` module structure (when implemented):**

```
app/discord/
  adapter.py          # CommandHandler: receives interaction → calls use case
  dispatcher.py       # EventDispatcher: receives OperationalEvent → sends Discord API call
  formatters.py       # Pure functions: domain objects → Discord message payloads
  identity.py         # Discord user ↔ app user resolution helpers
  message_store.py    # Reads/writes discord_messages table (message IDs and edit tokens)
  rate_limiter.py     # Retry strategy and bucket tracking
```

The adapter module must not import from `app/routes.py`. It calls `app/application/use_cases.py` directly. `routes.py` and `app/discord/adapter.py` are two separate surfaces over the same use-case layer.

---

## 4. Interaction Lifecycle

### A. Inbound: Discord → Application

```
User types /signup ──► Discord Gateway
                              │
                    CommandHandler.handle(interaction)
                              │
                    1. Resolve workspace
                       identity.discord_guild_to_workspace(guild_id)
                              │
                    2. Resolve user
                       identity.discord_user_to_app_user(discord_user_id)
                              │
                    3. Validate interaction has required fields
                              │
                    4. Call use case
                       use_cases.submit_signup_intent(...)
                              │
                    5. Respond to interaction
                       discord.respond(interaction, success_embed)
```

Rules:
- Steps 1–3 fail fast with a Discord ephemeral error response if resolution fails.
- Step 4 raises domain exceptions (`ValidationError`, `ConflictError`) — translated to ephemeral error responses; no stack traces exposed.
- Step 5 is the only place Discord objects are constructed; use cases never touch them.

### B. Automatic outbound: OperationalEvent → Discord

Triggered after commit by the EventDispatcher. Best-effort. A Discord failure never rolls back the domain transaction.

```
use_case mutates state
       │
       ├─ writes OperationalEvent (same transaction)
       │
       └─ (after commit) EventDispatcher.dispatch(event: dict)
               │
       lookup: event_type → handler
               │
       handler reads domain data if needed (read-only DB query)
               │
       formatters.format_*(domain_data) → Discord payload
               │
       discord_api.send / edit
               │
       message_store.record(message_id, channel_id, event_type, entity_id)
```

### C. Explicit outbound: officer action → use case → Discord

Triggered by an officer clicking an action on the web UI (e.g. "Post Roster to Discord").
The use case is the authority; the Discord post is its side effect.

```
Officer clicks "Post Roster to Discord" on web
       │
       routes.py calls use_cases.publish_discord_roster(operation_id, channel_id)
               │
       use case reads current assignments from DB
               │
       calls formatters.format_roster(assignments) → Discord embed payload
               │
       calls discord_api.post(channel_id, embed)
               │
       stores returned message_id in discord_messages table
               │
       emits discord_roster.posted OperationalEvent (same transaction as record)
               │
       returns to web route → HTTP response
```

The OperationalEvent records that the roster was posted and at what time.
Subsequent assignment changes do NOT auto-edit the roster post.
Officers must explicitly click "Update Roster Post" to re-post, which calls `update_discord_roster(...)`.
This prevents roster messages from flickering with each individual assignment change.

---

## 5. OperationalEvent → Discord Message Mapping

| OperationalEvent | Trigger type | Discord action | Channel | Editable later? |
|------------------|-------------|---------------|---------|-----------------|
| `guild_operation.published` | Automatic | Post announcement embed | `#cta-announcements` | Yes — update when status changes |
| `guild_operation.locked` | Automatic | Edit announcement embed: "Roster locked" | Same message | Yes |
| `guild_operation.completed` | Automatic | Edit announcement embed: "Completed" | Same message | No further edits |
| `guild_operation.archived` | — | No action | — | — |
| `operation_slots.generated` | — | No action | — | — |
| `operation_plan.attached` | — | No action | — | — |
| `signup_intent.submitted` | Automatic | Ephemeral confirmation to player | Ephemeral | No |
| `assignment.created` | — | No automatic message | — | — |
| `readiness_snapshot.created` | Automatic | Post/edit readiness summary in officer channel | `#officer-board` | Yes — edit existing if present |
| `discord_roster.posted` | Explicit (officer) | Post roster embed | Officer-chosen channel | Yes — on explicit "Update Roster Post" |
| `attendance.recorded` | — | No action | — | — |
| `scout_attendance.recorded` | — | No action | — | — |

---

## 6. Message Update Strategy

**Problem:** Discord messages can only be edited by the bot that posted them. Message IDs must be stored or the message cannot be updated.

**Design — `discord_messages` table:**

```sql
CREATE TABLE discord_messages (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT REFERENCES guild_operations(id),
    message_type        TEXT NOT NULL,  -- "announcement" | "roster" | "readiness"
    discord_channel_id  TEXT NOT NULL,
    discord_message_id  TEXT NOT NULL,
    discord_guild_id    TEXT NOT NULL,
    posted_at           TEXT NOT NULL,
    last_edited_at      TEXT,
    is_deleted          BOOLEAN NOT NULL DEFAULT 0,
    UNIQUE (guild_operation_id, message_type)
);
```

**Update flow:**
1. Before posting: look up `discord_messages` for `(guild_operation_id, message_type)`.
2. If a live `discord_message_id` exists: call `discord_api.edit_message(...)`.
3. If none exists: call `discord_api.create_message(...)`, store returned ID.
4. If edit returns 404 (message deleted externally): post fresh, store new ID.

**Stale message protection:** if `last_edited_at` is older than a configurable threshold (e.g. 7 days), treat as stale — post fresh or skip.

---

## 7. Discord Identity and Guild Linking

### Workspace ↔ Discord guild

Add `discord_guild_id` (nullable, unique) to `guild_workspaces`. Owner links it via a web UI form. Discord OAuth required for verified linking; pre-OAuth fallback is manual guild ID entry by the workspace owner.

```sql
ALTER TABLE guild_workspaces ADD COLUMN discord_guild_id TEXT UNIQUE;
ALTER TABLE guild_workspaces ADD COLUMN discord_announcement_channel_id TEXT;
ALTER TABLE guild_workspaces ADD COLUMN discord_officer_channel_id TEXT;
```

### User ↔ Discord identity

`users.auth_provider = 'discord'` with `provider_user_id` = Discord snowflake. Players without a Discord link can use the web UI fully. Discord-linked players can use bot commands. Players without a link receive an ephemeral bot response directing them to the web link flow.

### Command resolution (pseudocode)

```python
# app/discord/identity.py

def discord_guild_to_workspace(discord_guild_id: str, db) -> dict:
    workspace = repositories.get_workspace_by_discord_guild_id(db, discord_guild_id)
    if not workspace:
        raise DiscordNotLinkedError("This Discord server is not linked to a workspace.")
    return workspace

def discord_user_to_app_user(discord_user_id: str, db) -> dict:
    user = repositories.get_user_by_provider_identity(db, "discord", discord_user_id)
    if not user:
        raise DiscordUserNotLinkedError("Link your Discord account at [web URL]/link.")
    return user
```

---

## 8. Allowed Discord Capabilities vs Forbidden Responsibilities

### Allowed

- Announce operation published/locked status (automatic, event-driven).
- Accept signup intent via slash command (`/signup` → `submit_signup_intent`).
- Accept scout/support check-in via slash command (`/checkin` → `record_scout_attendance`).
- Display current readiness snapshot on command (`/readiness`).
- Display assignment list on command (`/roster`).
- Post/edit roster embed on explicit officer action from the web UI.
- Notify officers of readiness state change (automatic, event-driven).
- Ephemeral acknowledgements to command issuers.
- Remind assigned players before operation (scheduled job reads DB, bot sends DM).

### Forbidden

- Owning lifecycle transitions (publish, lock, complete, archive).
- Storing signup data locally in the bot process.
- Computing readiness, gaps, or assignment candidates.
- Initiating assignment flows without a domain command.
- Running payout or regear calculations.
- Making authorization decisions (role checks happen in use cases).
- Tracking voice attendance or presence independently.
- Running recruitment workflows.
- Owning watchlists, ban lists, or rotation queues.
- Interpreting signup collisions or deduplication.
- Sending messages based on internal bot state rather than OperationalEvents.

---

## 9. Signup Flow via Discord

```
/signup role:Healer build:Hallowfall availability:confirmed

CommandHandler
  ├─ identity.discord_guild_to_workspace(guild_id)  → workspace
  ├─ identity.discord_user_to_app_user(user_id)     → app_user
  ├─ repositories.get_active_operation_for_workspace(workspace_id)
  │    (status == "planning" and signup_status == "open")
  ├─ use_cases.submit_signup_intent(
  │      guild_workspace_id = workspace.id,
  │      guild_operation_id = operation.id,
  │      display_name       = app_user.display_name,
  │      preferred_role     = "Healer",
  │      preferred_build    = "Hallowfall",
  │      willingness        = "specific",
  │      availability       = "confirmed",
  │      source             = "discord",
  │    )
  └─ respond ephemerally: "Signed up as Healer / Hallowfall ✓"
```

| Discord command param | SignupIntent field |
|----------------------|--------------------|
| `role:` | `preferred_role` |
| `build:` | `preferred_build_name` |
| `availability:` | `availability` |
| `flexible:` | `willingness` |
| — | `source = "discord"` |
| — | `display_name` from linked app user |

Add `source` column to `signup_intents` (no domain-rule effect; audit/display only).

---

## 10. Attendance Check-In Flow via Discord

Scout/support check-in is the primary Discord-appropriate attendance interaction. It happens in real-time during the operation.

```
/checkin role:scout notes:south-zone

CommandHandler
  ├─ resolve workspace + user
  ├─ find locked/completed operation
  └─ use_cases.record_scout_attendance(
         guild_workspace_id,
         guild_operation_id,
         display_name = app_user.display_name,
         role_type    = "scout",
         notes        = "south-zone",
     )
```

Assigned attendance (present/late/absent) is officer-only and stays web-only. Officers see attendance state on the web planner; they do not mark it through Discord.

---

## 11. Background Automation Boundaries

### Allowed automations (scheduled jobs)

| Job | Trigger | Action |
|-----|---------|--------|
| Pre-operation reminder | `scheduled_start_at - N minutes` | Read assignments from DB → send DM to each assigned player |
| Signup deadline warning | `plan.signup_deadline - M minutes` | Read signup count vs slot count → post readiness summary to officer channel |
| Readiness ping | Configurable interval before operation | Call `recalculate_readiness` use case → EventDispatcher posts to officer channel |

### Forbidden automations

- Auto-assigning players without an officer command.
- Auto-locking, auto-completing, or auto-archiving operations.
- Auto-removing or re-prioritizing signups.
- Running payout or regear calculations on a schedule.

### Scheduler constraint

The scheduler reads OperationalEvents and DB state; it does not maintain its own process state. Scheduled jobs store their last-run cursor in a `scheduler_state` table. A bot restart does not miss jobs.

---

## 12. Rate Limit and Retry Strategy

1. **Exponential backoff with jitter** on `429 Too Many Requests`. Respect `retry_after` header exactly.
2. **Global rate limit sentinel**: back off globally when a global 429 is received.
3. **Non-critical bulk messages** (reminder DMs): 1–2s delay between messages when sending to many players.
4. **Critical ephemeral responses**: respond within Discord's 3-second interaction window using `InteractionResponse.defer()` + `followup.send()` for domain calls taking >1s.
5. **Retry budget**: max 3 retries per outbound message. After 3 failures, log to `discord_dispatch_failures`. No silent discard.

```sql
CREATE TABLE discord_dispatch_failures (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    entity_id           TEXT,
    error_code          INTEGER,
    error_message       TEXT,
    attempted_at        TEXT NOT NULL,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL   -- "pending_retry" | "failed" | "resolved"
);
```

---

## 13. What Remains Web-Only vs Discord-Capable

| Action | Web-only | Discord-capable |
|--------|----------|-----------------|
| Create operation | ✓ | |
| Attach plan | ✓ | |
| Generate slots | ✓ | |
| Publish operation | ✓ | |
| Lock operation | ✓ | |
| Complete / archive | ✓ | |
| Assign player to slot | ✓ | |
| Remove assignment | ✓ | |
| Reserve/bench | ✓ | |
| Recalculate readiness | ✓ | |
| Create composition | ✓ | |
| Manage workspace members | ✓ | |
| Submit signup | ✓ | ✓ (Phase 2) |
| Scout/support check-in | ✓ | ✓ (Phase 2) |
| View readiness snapshot | ✓ | ✓ (Phase 2, read-only) |
| View roster (assignments) | ✓ | ✓ (Phase 2, read-only) |
| Announce operation | — | ✓ (Phase 2, automatic via event) |
| Pre-op reminder DMs | — | ✓ (Phase 2, scheduled) |
| Mark assigned attendance | ✓ | |
| Post roster embed | ✓ (officer initiates) | Bot executes |
| Update roster embed | ✓ (officer initiates) | Bot executes |

---

## 14. Recommended Implementation Order

**Phase 0 (current): No bot.**
Operational core proven on the web. Every use case callable independently of Discord.

**Phase 1: Infrastructure foundations (no user-visible Discord features)**
1. Add `discord_guild_id` + channel config columns to `guild_workspaces`.
2. Add `discord` auth provider support (already possible via `auth_provider` column).
3. Add `discord_messages` table.
4. Add `discord_dispatch_failures` table.
5. Add `source` column to `signup_intents`.
6. Define `app/discord/` module structure with empty handlers.
7. Write EventDispatcher skeleton — logs events without calling Discord API yet.

**Phase 2: Read-only bot + signup command**
1. Bot connects to gateway. Verifies workspace linking.
2. `/roster` — fetches assignments, returns embed.
3. `/readiness` — fetches latest snapshot, returns embed.
4. `guild_operation.published` event → announcement embed.
5. `/signup` command → `submit_signup_intent` use case.
6. `/checkin` command → `record_scout_attendance` use case.

**Phase 3: Explicit roster post + reminder jobs**
1. "Post Roster to Discord" button on web operation detail.
2. "Update Roster Post" button.
3. Pre-operation reminder DM job (reads from DB by `scheduled_start_at`).
4. Readiness ping to officer channel.

**Phase 4: Discord OAuth identity linking**
1. OAuth flow to link Discord snowflake to app user.
2. Discord OAuth as an auth provider alongside dev login.

**Out of scope for V2:** payout notifications, regear notifications, recruitment flows, watchlists, voice tracking, ban/rotation management, analytics feeds.

---

## 15. Anti-Patterns from Old Ironkeep to Avoid

| Anti-pattern | What it meant | V2 rule |
|--------------|--------------|---------|
| **Bot as workflow owner** | CTA lifecycle driven by slash command success/failure | Use cases own lifecycle; bot calls them |
| **Signup state in bot memory** | Signups tracked in bot dicts between restarts | All state persists in DB before responding |
| **Discord interaction as transaction** | Operation state changed only if Discord interaction succeeded | DB write first, Discord response after |
| **Bot-defined authorization** | Permission check inside command handler | Use cases enforce roles; bot passes credentials |
| **Auto-assignment on signup** | Bot auto-filled party slots when signup arrived | Assignment is explicit, caller-owned |
| **Reminders as stateful bot loops** | `asyncio.sleep` + bot-held timers | Scheduler reads DB; bot process is stateless |
| **CTA command creating the operation** | `/cta create` inserted a row | Only web creates operations in V2 (Phase 0/1) |
| **Discord formatting mixed with business logic** | Embeds built inside command handlers | Pure `formatters.py` functions, pure domain objects in |
| **Absence of OperationalEvents** | State changed silently | Every mutation emits an event in the same transaction |
| **Guild-agnostic bot** | One bot namespace, no workspace isolation | Every command resolves workspace from `discord_guild_id`; cross-guild commands rejected |
| **Discord as canonical attendance source** | Attendance truth derived from voice + reactions | Application DB owns attendance; Discord is one optional input signal |
| **Message IDs in bot memory** | Bot stored message IDs in memory | `discord_messages` table; message IDs are durable |
| **Mass DM from event loops** | Bot looped all members to DM on every event | DMs are scheduled jobs reading from DB; no event-triggered mass DM |
| **Explicit-only outbound** (old gap) | Only explicit actions posted to Discord | Automatic event-driven outbound AND explicit officer-initiated outbound are both valid, distinct paths |
