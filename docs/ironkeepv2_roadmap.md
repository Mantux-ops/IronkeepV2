# IronkeepV2 Roadmap

IronkeepV2 is a guild coordination platform for Albion Online, built as a clean-room rewrite of the original Ironkeep system. It manages the full lifecycle of guild operations (CTAs): creation, composition planning, player signup, slot assignment, readiness tracking, attendance recording, and Discord communication. The operational command center is the web application. Everything real — roster state, assignments, attendance, readiness — lives in the database and is mutated only through explicit use cases.

The architectural philosophy is vertical slices with strict domain boundaries. SQLite is the database. FastAPI + Jinja2 server-rendered templates are the presentation layer. There is no frontend framework, no Tailwind migration, no WebSockets, no external queues. Business logic lives in `app/application/use_cases.py`. Domain rules live in `app/domain/`. The database is the single source of truth and is never bypassed.

Discord is a **communication and interaction surface only**, not the operational brain. Officers post announcements and rosters explicitly from the web UI. Players check in via Discord buttons. All state mutations from Discord call the same use cases that the web UI calls. The Discord bot is a thin adapter process (`bot/`) that translates gateway events into adapter payloads — it contains no business logic and owns no workflow state. OperationalEvents drive automated outbound Discord messages post-commit; explicit officer actions (Post to Discord, Update Roster Post) drive outbound messages on demand. Discord failure never rolls back a domain transaction.

---

## Current Priorities

No slices are currently in progress. See Suggested Next Slices for candidates.

**Recently completed:** Launch Readiness Checklist + Pilot Guild Onboarding (slice 46) — `docs/launch_checklist.md` (11-section pre-launch checklist), `docs/pilot_onboarding.md` (officer onboarding guide: Discord setup, first workspace/operation workflow, ledger, known limitations, debug info), `docs/security_notes.md` (secrets handling, .env safety, Discord token rotation, SQLite sensitivity, network exposure), `README.md` (project overview, quick start, env-var table, docs index, scripts table, project structure). No app changes. No new tests (no docs link-validation pattern). Previous: Deployment Runbook + Process Supervision Foundation (slice 45) — `docs/deployment.md` (full runbook: env vars, startup, WAL notes, backup/restore, health checks, rollback, troubleshooting), `scripts/backup_db.py` CLI (wraps `app.backup`, `--dest`/`--backup-dir`/`--prefix`/`--verify`, 24 tests), `scripts/run_app.sh`, `scripts/run_scheduler.sh`, `docs/systemd/*.service.example` (systemd units for both processes). Previous: Backup / Restore + Recovery Hardening (slice 44) — new `app/backup.py` module (WAL-aware `create_backup` via Python sqlite3 API, `get_db_file_info` for safe metadata display, `backup_filename` generator, `validate_backup_destination`), `check_integrity` in `app/startup.py`, diagnostics page extended with DB file size / WAL state / backup recommendations / restore cautions, 60 new tests in `test_backup_restore.py`. Full suite: 1424 passed, 58 test files.

---

## Planned / Deferred

### Albion Online API Integration

**Why deferred:** Player lookup, item database, killboard verification, and build validation all require an external API dependency with its own rate limits, schema changes, and failure modes. V2 is intentionally API-free at this stage to keep the domain clean.

**What must stabilize first:** Composition and slot system must be stable. Build names are currently free-text strings — API integration would add structured item IDs, which is a schema evolution.

**Estimated complexity:** High. Schema changes for item IDs, external service boundary, caching layer, and failure handling.

---

### Advanced Discord Interactions (Beyond Check-in)

**Why deferred:** Signup via Discord slash command, reserve management via Discord, and assignment updates via Discord all risk recreating V1's pattern of Discord owning operational workflow state. They require careful domain-boundary design before implementation.

**What must stabilize first:** The existing `handle_component_interaction` and slash command adapter patterns must be validated in production with the current check-in flow.

**Estimated complexity:** Medium per command. The adapter layer is already in place. Risk is architectural, not technical.

---

### Regear / Payout Tracking

**Why deferred:** Regear and payout tracking are post-operation financial workflows with their own domain complexity (gear values, death records, contribution weights). V2 is focused on pre-operation coordination first.

**What must stabilize first:** Attendance recording must be complete and field-tested, since payout eligibility derives from attendance.

**Estimated complexity:** High. New domain models, financial validation rules, officer approval flows.

---

### Attendance Rollup / Season Dashboard

**Why deferred:** Guild-level attendance statistics (reliability scores, seasonal participation rates, player activity trends) require aggregation queries across many operations and a season management system.

**What must stabilize first:** Per-operation attendance recording must be reliable and complete.

**Estimated complexity:** Medium. Mostly query complexity, some new templates and domain concepts (Season entity).

---

### Calendar View

**Why deferred:** A calendar representation of scheduled operations adds value for scheduling coordination but has no operational urgency. The current list view on the dashboard is sufficient while operation volume is low.

**What must stabilize first:** Operation creation and scheduling workflows.

**Estimated complexity:** Low. Mostly a template and a date-grouping query.

---

### Mobile Optimization

**Why deferred:** The web UI is the operational command center for officers at a desk. Mobile use during operations is a secondary concern. The current responsive breakpoint (900px) handles tablet-width acceptably.

**What must stabilize first:** Core operational workflows on desktop.

**Estimated complexity:** Low–medium. CSS media query work, no domain changes.

---

### Advanced Composition Tooling

**Why deferred:** Weapon variant selection, role weight targets ("need exactly 3 DPS but any DPS build"), and priority-weighted auto-assignment all require richer composition domain models.

**What must stabilize first:** Basic slot generation and manual assignment workflows.

**Estimated complexity:** Medium–high. Schema evolution for composition slots, new domain validation rules.

---

### Recruitment Flows, Watchlists, Voice Tracking

**Why deferred:** These are V1 features that were cut intentionally. They add surface area without improving the core CTA coordination workflow. They will be reconsidered only after the core loop is stable.

**Estimated complexity:** Medium each. Separate domain concerns with their own data models.

---

## Completed

Slices are listed in implementation order. Each was test-driven and run to full green before the next began.

---

### 1. Auth Foundation

**Type:** Foundation / Auth

**Description:** Core user identity, workspace membership, and role-based authorization. Dev login (display-name based) replaces Discord OAuth for the development phase. All POST routes enforce server-side role checks. Auth helpers raise `AuthenticationRequired` / `PermissionDenied`; routes decide whether to redirect or return 403.

**Major files:** `app/application/use_cases.py` (dev_login_or_create_user, create_guild_workspace, add_workspace_member), `app/routes.py` (login/logout, workspace scoping), `app/schema.sql` (users, workspace_members), `app/domain/workspace_membership.py`

**Key decisions:**
- Auth helpers return user data or raise errors — they do not redirect. Routes own redirect logic.
- `can_mutate` flag passed to templates as presentation-only, not security.
- Workspace membership misses return 404 (not 403) to avoid leaking workspace existence to non-members.
- `auth_provider` / `provider_user_id` columns schema-ready for future Discord OAuth.

---

### 2. UI Foundation

**Type:** UX / Presentation

**Description:** Consistent layout system across all pages. Global nav, workspace nav, operation tabs, card/panel/badge/alert components, form patterns, table styles, action buttons. All implemented as custom CSS variables in `base.html` — no Tailwind, no external UI framework.

**Major files:** `app/templates/base.html`, all page templates, `app/templates/workspace_nav.html`, `app/templates/operation_tabs.html`, `app/templates/flash_messages.html`, `app/templates/page_header.html`

**Key decisions:**
- CSS custom properties (`--accent`, `--surface`, `--border`, etc.) allow global theming without touching every component.
- Status badge color system: `badge-draft`, `badge-planning`, `badge-locked`, `badge-completed`, `badge-archived`.
- PRG pattern enforced for all POST actions via flash messages.
- No JavaScript except the existing composition slot-row helper.

---

### 3. Discord Integration Boundary Design

**Type:** Architecture / Design Document

**Description:** Design-only slice. Produced `docs/discord_integration_boundary.md` defining exactly how Discord integrates with IronkeepV2 without becoming the operational brain. Established the architectural principles (P1–P10), source-of-truth rules, adapter boundaries, interaction lifecycle, event-to-Discord mapping, message update strategy, and explicit anti-patterns from V1.

**Major files:** `docs/discord_integration_boundary.md`

**Key decisions:**
- P3 updated: "Commands flow in; events and explicit officer actions flow out." Automated outbound via OperationalEvents; explicit outbound via officer-initiated use cases.
- Discord identity linking model established: `auth_provider='discord'` + `provider_user_id` per user.
- Message identity model established: `discord_messages` table, edit-before-post strategy.

---

### 4. Discord Infrastructure Foundation

**Type:** Foundation / Schema / Modules

**Description:** Schema additions and module skeleton for future Discord integration. No live Discord API calls. Added Discord config columns to `guild_workspaces`, `source` column to `signup_intents`, `discord_messages` table, `discord_dispatch_failures` table. Created `app/discord/` module skeleton.

**Major files:** `app/schema.sql`, `app/repositories.py` (Discord config + message helpers), `app/discord/__init__.py`, `app/discord/adapter.py`, `app/discord/dispatcher.py`, `app/discord/formatters.py`, `app/discord/identity.py`, `app/discord/message_store.py`, `app/discord/rate_limiter.py`

**Key decisions:**
- `discord_messages` uniqueness: `UNIQUE (guild_workspace_id, guild_operation_id, message_type)` — workspace-scoped, not just operation-scoped.
- `signup_intents.source` defaults to `'web'`; future Discord signups pass `source='discord'`.
- Discord SDK dependency excluded from `requirements.txt` — SDK lives only in `bot/requirements.txt`.

**Tests:** `test_discord_schema.py`, `test_discord_module_boundaries.py`, `test_signup_source.py`

---

### 5. Post-commit OperationalEvent Dispatch Foundation

**Type:** Foundation / Event Architecture

**Description:** Central, synchronous, best-effort post-commit event dispatch. Every use case emits OperationalEvents within its database transaction. After commit, `DISPATCHABLE_EVENT_TYPES` events are dispatched to `app.discord.dispatcher.dispatch`. Dispatcher failures write to `discord_dispatch_failures` in a separate transaction and never roll back the domain transaction.

**Major files:** `app/database.py` (`TransactionContext` wrapper), `app/events.py` (`DISPATCHABLE_EVENT_TYPES`, `dispatch_event`, `_record_failure`), `app/repositories.py` (`insert_operational_event`, `pending_dispatch` appending)

**Key decisions:**
- `TransactionContext` wraps `sqlite3.Connection` and owns `pending_dispatch: list[dict]`. No thread-local state, no monkeypatching of C extension objects.
- Dispatch is synchronous — no queues, no Celery, no Redis.
- Dispatch exceptions never propagate to the domain caller.
- Current dispatchable events: `workspace.created`, `guild_operation.published`, `guild_operation.locked`, `guild_operation.completed`, `readiness_snapshot.created`, `signup_intent.submitted`, `scout_attendance.recorded`, `support_attendance.recorded`.

**Tests:** `test_event_dispatch.py`

---

### 6. Discord Workspace Configuration UI

**Type:** UX / Discord

**Description:** Web UI for workspace owners/officers to configure Discord IDs (`discord_guild_id`, `discord_announcement_channel_id`, `discord_officer_channel_id`). Snowflake validation (15–20 digit strings), guild ID uniqueness enforced, empty values clear the config. Emits `workspace.discord_config.updated` (audit-only, not dispatchable).

**Major files:** `app/templates/workspace_discord_settings.html`, `app/templates/workspace_nav.html` (Settings link, officer-only), `app/routes.py` (GET/POST `/settings/discord`), `app/application/use_cases.py` (`update_workspace_discord_config`), `app/domain/guild_workspace.py` (`validate_discord_snowflake`, `validate_discord_config`)

**Key decisions:**
- Manual ID entry only — no Discord OAuth verification.
- Settings nav link hidden from members.
- Snowflake validation: digits-only, 15–20 chars.

**Tests:** `test_discord_config_ui.py`

---

### 7. Discord Formatter Foundation

**Type:** Discord / Pure Functions

**Description:** Pure formatting functions in `app/discord/formatters.py` returning JSON-serializable plain dict payloads matching the Discord REST API message/embed schema. No Discord SDK, no database access, no side effects.

**Formatters:** `format_operation_announcement`, `format_readiness_summary`, `format_roster`, `format_signup_confirmation`

**Major files:** `app/discord/formatters.py`

**Key decisions:**
- Inputs are plain dicts/read models from callers.
- Outputs are Discord-compatible `{"embeds": [...]}` / `{"embeds": [...], "components": [...]}` dicts.
- Status colors via `STATUS_COLORS` map: draft=grey, planning=blue, locked=gold, completed=green, archived=dark.
- `format_roster` groups slots by party number.
- `format_operation_announcement` and `format_roster` include a `components` action row with Scout Check-in, Support Check-in, and (optional) Open Signup Page link buttons.

**Tests:** `test_discord_formatters.py` (covers payload shape, component buttons, JSON serializability, SDK import prohibition)

---

### 8. Discord Identity Resolution Foundation

**Type:** Discord / Domain

**Description:** Pure DB-based resolution of Discord identity to application identity. No API calls, no OAuth, no bot gateway. Resolves Discord guild ID → GuildWorkspace, Discord user ID → app user, and verifies workspace membership. Returns structured errors for each failure mode.

**Functions:** `resolve_workspace_from_discord_guild`, `resolve_user_from_discord_id`, `resolve_member_from_discord`, `get_discord_identity_context`

**Errors:** `DiscordNotLinkedError`, `DiscordUserNotLinkedError`, `DiscordUserNotWorkspaceMemberError` — all subclass `IronkeepError`.

**Major files:** `app/discord/identity.py`

**Key decisions:**
- Resolution order: workspace first, then user, then membership. Each step can fail independently.
- Being a member of a different workspace does not satisfy membership check for the resolved workspace.
- All errors carry human-readable messages suitable for ephemeral Discord responses.

**Tests:** `test_discord_identity.py`

---

### 9. Discord Command Adapter Foundation

**Type:** Discord / Adapter

**Description:** Pure command adapter layer (`app/discord/adapter.py`) accepting plain dict interaction payloads and delegating to existing use cases. No Discord SDK imports. Handlers: `handle_signup_command`, `handle_readiness_command`, `handle_roster_command`, `handle_checkin_command`.

**Major files:** `app/discord/adapter.py`

**Key decisions:**
- All handlers: resolve identity → call use case or read repo → return Discord interaction response dict.
- `handle_signup_command` uses `source='discord'`.
- `handle_checkin_command` fetches the operation before calling `record_scout_attendance` to get the title for the confirmation message.
- Known `IronkeepError` subclasses become ephemeral error payloads (`type=4, flags=64`). Unknown exceptions propagate.
- No slash command registration in this layer.

**Tests:** `test_discord_adapter.py`

---

### 10. Discord Dispatcher Foundation

**Type:** Discord / Event Routing

**Description:** `app/discord/dispatcher.py` translates dispatchable OperationalEvents into intended Discord message actions without making API calls. Returns structured action dicts (`post_message`, `edit_message`, `noop` with reason).

**Events handled:** `guild_operation.published`, `guild_operation.locked`, `guild_operation.completed` → announcement payload; `readiness_snapshot.created` → readiness payload; signup and attendance events → noop currently.

**Major files:** `app/discord/dispatcher.py`

**Key decisions:**
- Dispatcher reads DB state but must not mutate operational state or call use cases.
- Missing Discord config returns `noop` (not an exception).
- `get_discord_message` is workspace-scoped: `(guild_workspace_id, guild_operation_id, message_type)`.
- Phase 1 implementation: resolves + logs actions. Phase 2 (actual API calls) is the post-commit dispatch path.

**Tests:** `test_discord_dispatcher.py`

---

### 11. Planner UX Hardening

**Type:** UX / Planner

**Description:** Replaced readiness table with a compact readiness summary bar (fill rate, state badge, gap pills, secondary stats). Added party fill count (3/5) to party headers with color classes. Added visual emphasis for open core slots (`row-open-core`, amber left border). Added unassigned signups panel. Enhanced reserve/bench panel with signup preferences.

**Major files:** `app/templates/operation_planner.html`, `app/templates/base.html` (CSS: gap-pill, fill-count, readiness-bar, row-open-core), `app/routes.py` (`get_planner` — passes `unassigned_participants`, `signup_prefs`)

**Key decisions:**
- Attendance marked/unmarked kept as a secondary stat in the readiness bar (not removed).
- No domain or schema changes — all template/CSS plus context variable additions.
- Party fill count color: green=full, amber=partial, red=empty.

**Tests:** Existing planner tests extended; `test_discord_announcement_preview.py` updated for new template structure.

---

### 12. Discord Proof-of-Life Bot

**Type:** Discord / Infrastructure

**Description:** Minimal Discord bot in `bot/` directory, isolated from the application. Verifies Discord gateway connectivity and command handling. Single slash command: `/ikv2_ping` (ephemeral response with latency and client ID).

**Major files:** `bot/bot.py`, `bot/config.py`, `bot/requirements.txt`, `bot/.env.example`

**Key decisions:**
- Discord SDK (`discord.py>=2.4.0`) is in `bot/requirements.txt` only. Root `requirements.txt` unchanged. Existing `test_discord_module_boundaries.py` still passes.
- All bot identity from environment variables (`DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_DEV_GUILD_ID`).
- Bot is swappable by changing env vars only — no hardcoded IDs, guild IDs, or tokens.
- `bot.py` MAY import from `app.discord.*` — it must NOT duplicate adapter, formatter, identity, or dispatcher logic.

---

### 13. Discord Announcement Preview

**Type:** Discord / UX

**Description:** Read-only Discord announcement preview card on the operation overview page. Uses `format_operation_announcement()` as the single source of preview truth. Renders a mock Discord embed with accurate field structure. Shows config gap warnings (no guild, no channel) with settings links.

**Major files:** `app/templates/operation_detail.html` (Discord Announcement Preview card, guarded by `can_mutate`), `app/routes.py` (`get_operation_detail` — computes `discord_preview`, `discord_config_gap`)

**Key decisions:**
- Preview is read-only. No `discord_messages` writes, no events, no API calls.
- Member users see no preview card — guarded by `can_mutate`.
- `discord_config_gap` values: `None` (config complete), `"no_guild"`, `"no_channel"`.

**Tests:** `test_discord_announcement_preview.py`

---

### 14. Discord Announcement Post Action

**Type:** Discord / Officer Action

**Description:** Explicit officer action to post or update the operation announcement to Discord. New use case `post_discord_announcement` follows the two-phase DB transaction pattern: read (phase 1) → REST call (external) → write (phase 2). Stores message identity in `discord_messages`. Emits `discord_announcement.posted` or `discord_announcement.updated`.

**Major files:** `app/discord/rest_client.py` (new), `app/application/use_cases.py` (`post_discord_announcement`), `app/routes.py` (POST `/discord/announce`), `app/templates/operation_detail.html` (Post/Update button + timestamp)

**Key decisions:**
- `rest_client.py` uses explicit 5-second timeouts. `TimeoutException` raises `DiscordApiError`. Web request never hangs indefinitely.
- REST failure → no `discord_messages` row, no event. Domain state is unaffected.
- Two-phase pattern: DB transaction closed before network call; new transaction opened after success to record the result. Prevents long-held DB locks during network I/O.
- `discord_announcement.posted` / `discord_announcement.updated` are audit-only events (not dispatchable).
- Button label: "Post to Discord" (first time) vs. "Update Discord Announcement" (with last-posted timestamp).

**Tests:** `test_discord_post_announcement.py` (all REST calls mocked)

---

### 15. Discord Roster Preview + Explicit Roster Post

**Type:** Discord / Officer Action / Planner

**Description:** Roster preview card on the operation planner page, plus an explicit "Post Roster to Discord" / "Update Roster Post" button. Uses `format_roster()`. Preview reflects current `OperationSlots` + active `Assignments`. Stores message identity in `discord_messages` with `message_type="roster"`. Emits `discord_roster.posted` or `discord_roster.updated`.

**Major files:** `app/application/use_cases.py` (`post_discord_roster`), `app/routes.py` (`get_planner` — roster preview context; POST `/discord/roster`), `app/templates/operation_planner.html` (Discord Roster Preview card)

**Key decisions:**
- Same two-phase DB transaction pattern as announcement post.
- No automatic roster posting when assignments change.
- `discord_roster.posted` / `discord_roster.updated` are audit-only events.
- `WEB_BASE_URL` env var used to build signup link button URL in the roster payload.

**Tests:** `test_discord_post_roster.py` (18 tests, all REST calls mocked)

---

### 16. Discord Scout/Support Check-in Buttons

**Type:** Discord / Interaction Surface

**Description:** Added `components` action rows to announcement and roster Discord message payloads. Three buttons: Scout Check-in, Support Check-in (both with `custom_id`), Open Signup Page (link button, `style: 5`). Added `handle_component_interaction(payload, db)` to the adapter. Added `on_interaction` handler to `bot/bot.py` routing component interactions to the adapter. Check-in calls `record_scout_attendance` — same use case as the web UI.

**Major files:** `app/discord/formatters.py` (`_build_components`, updated `format_operation_announcement`, `format_roster`), `app/discord/adapter.py` (`handle_component_interaction`, `_VALID_CHECKIN_ROLES`), `bot/bot.py` (`on_interaction`), `app/application/use_cases.py` (signup_url from `WEB_BASE_URL`)

**Key decisions:**
- Link button (`style: 5`) has no `custom_id`. Check-in buttons have no `url`. Discord API requirement.
- `WEB_BASE_URL` env var controls the signup page link. If not set, link button is omitted (not broken).
- `custom_id` format: `checkin:{role_type}:{operation_id}`. Parse is strict — wrong prefix, wrong segment count, invalid role → ephemeral error.
- No Discord-side state. All attendance truth in the application DB.
- Unknown exceptions propagate from the adapter to the bot's global handler.

**Tests:** `test_discord_component_checkin.py` (30 tests), `test_discord_formatters.py` (18 new component tests)

---

### 17. Planner Layout Foundation + Tier 1 UI Cleanup

**Type:** UX / Planner

**Description:** Widened the global operational layout (`--max-width` 1120 → 1280px, added `--max-width-wide: 1440px` and `.page--wide`). Removed Weapon and Priority columns from party tables — data conveyed by row styling and Build field. Collapsed Discord Roster Preview inside `<details>` by default. Promoted Quick Fill Party to `btn-primary`. Fixed global form `max-width` so inline planner forms are not artificially constrained.

**Major files:** `app/templates/base.html` (CSS variables, `.page--wide`, `details.discord-preview-details`), `app/templates/operation_planner.html`

**Key decisions:**
- `max-width: 560px` moved from global `form` selector to `.form` / `form.form` — keeps non-planner forms narrow while freeing inline planner forms.
- Discord Roster Preview collapse uses native `<details><summary>` — zero JS.
- `.page--wide` applied to planner only; other pages retain readable centered layout.

---

### 18. Planner Two-Column Layout

**Type:** UX / Planner

**Description:** Restructured `operation_planner.html` into a 2fr/3fr CSS grid on wide screens (≥960px): left column (Unassigned Signups + Reserve/Bench), right column (all Party panels). Both columns scroll independently within `max-height: 72vh`. Readiness strip and Discord Roster Preview remain full-width above the columns. Narrow screens collapse to single-column stacked layout.

**Major files:** `app/templates/operation_planner.html`, `app/templates/base.html` (`.planner-columns`, `.planner-col--left`, `.planner-col--right`)

**Key decisions:**
- Grid is `@media (min-width: 960px)` only — single-column on tablets/mobile.
- `overflow-y: auto; max-height: 72vh` on both columns — mirrors V1's `max-h-[72vh] overflow-auto` pattern.
- All existing form actions, field names, and POST targets unchanged.

---

### 19. Hide Archived Operations from Dashboard

**Type:** UX / Data Management

**Description:** Archived operations are hidden from the workspace dashboard by default. A `?show_archived=1` query parameter reveals them. Direct URL access to archived operation detail pages remains fully functional. Archived operations retain their badge and status. No rows deleted.

**Major files:** `app/repositories.py` (`get_guild_operations` — `include_archived` flag; `count_archived_guild_operations`), `app/templates/workspace_dashboard.html` (Show N archived / Hide archived toggle, `row-muted` class)

**Key decisions:**
- Archived operations are inaccessible from the dashboard by default but not deleted.
- Toggle is a plain URL query parameter — no JS, no AJAX.
- `count_archived_guild_operations` shown in the toggle link to indicate hidden state.

**Tests:** `test_dashboard_archived_filter.py`

---

### 20. Operation Detail Primary Action Elevation

**Type:** UX

**Description:** The contextually correct lifecycle action button (Publish / Lock Roster / Mark Completed / Archive) was moved from inside the Status card into the page header's right-action area. Only the next valid action is shown — no equal-weight buttons for different lifecycle stages.

**Major files:** `app/templates/operation_detail.html`

**Key decisions:**
- Inline header replaces `page_header.html` partial on the detail page.
- Status card removed. Lifecycle action is always visible at page load without scrolling.
- Same POST targets and form fields throughout.

---

### 21. Attendance Bulk Mark Present + Unmarked Row Emphasis

**Type:** UX / Attendance

**Description:** Post-operation attendance UX reduced from per-row form submissions to a single bulk action. New use case `bulk_mark_present` marks all unmarked active assignments as `present` and emits `attendance.recorded` for each. Attendance progress summary (X/Y marked, Z pending) shown above the table. Unmarked rows styled with `.row-unmarked-attendance` (amber left border, pale background). Existing per-row forms unchanged.

**Major files:** `app/application/use_cases.py` (`bulk_mark_present`), `app/routes.py` (POST `/attendance/bulk-present`), `app/templates/operation_attendance.html`, `app/templates/base.html` (`.row-unmarked-attendance` CSS)

**Key decisions:**
- Bulk action respects the same status gate as `record_attendance`: locked/completed allowed, others blocked.
- Existing attendance records are never overwritten by the bulk action.
- `.row-unmarked-attendance` is a separate semantic class from `.row-open-core` — planner domain and attendance domain styling remain independent.

**Tests:** `test_attendance_bulk_mark.py` (18 tests)

---

### 22. Dashboard Operational Awareness

**Type:** UX / Infra

**Description:** The workspace dashboard now shows readiness state per operation row without drilling into each operation. New repository function `get_latest_readiness_snapshots_for_workspace` fetches the most-recent snapshot for every operation in a single JOIN query. Dashboard displays: `readiness_state` badge, `assigned_slots / total_slots`, open slot count, unassigned signup count. Scheduled time formatted via a `friendly_dt` helper passed into template context (not a global filter).

**Major files:** `app/repositories.py` (`get_latest_readiness_snapshots_for_workspace`), `app/routes.py` (`get_workspace_dashboard` — `readiness_by_op`, `friendly_dt`), `app/templates/workspace_dashboard.html`

**Key decisions:**
- Single JOIN query — no N+1 queries.
- `friendly_dt` is a plain Python function passed directly into the template context, not registered as a global Jinja filter.
- Operations with no readiness snapshot show "No readiness yet."

**Tests:** `test_dashboard_readiness.py` (13 tests)

---

### 23. Workspace Member Removal

**Type:** UX / Auth / Data Management

**Description:** Owners and officers can remove members from a workspace via a new Members management page (`/workspaces/{slug}/members`). Removal deletes only the `workspace_members` row — users, participants, assignments, signup intents, attendance records, and operational events are all preserved. Historical display names remain visible through `participants.display_name`. Removed members immediately lose workspace access.

**Major files:** `app/application/use_cases.py` (`remove_workspace_member`), `app/repositories.py` (`delete_workspace_member`, `count_active_assignments_for_participant`, `find_participant_by_display_name`), `app/routes.py` (GET/POST `/members`, `/members/{id}/remove`), `app/templates/workspace_members.html` (new), `app/templates/workspace_nav.html` (Members link replaces Add Member)

**Key decisions:**
- Active assignment guard: removal blocked if target has active assignments — officer must unassign first.
- Permission matrix: owner can remove members and officers; officer can remove members only; members cannot remove anyone; no self-removal; owners cannot be removed.
- `workspace.member.removed` event is audit-only (not dispatchable).
- PRG pattern with `?error=` / `?success=` flash params on GET route.

**Tests:** `test_workspace_member_removal.py` (23 tests)

---

### 24. AlbionComposition Soft-Delete

**Type:** UX / Data Management

**Description:** Compositions can be retired (soft-deleted) by owners/officers. `albion_compositions.deleted_at` column added via migration. Retired compositions are hidden from the composition list and attach-plan dropdown by default. A `?show_deleted=1` toggle reveals them. Existing operations that reference a retired composition continue to work — frozen `OperationSlots` are unaffected. The composition name in operation plan display shows a "retired" badge.

**Major files:** `app/schema.sql` (`deleted_at TEXT NULL`), `app/database.py` (`_COLUMN_MIGRATIONS`), `app/repositories.py` (`get_albion_compositions` — `include_deleted` flag; `soft_delete_albion_composition`; `count_deleted_albion_compositions`), `app/application/use_cases.py` (`retire_composition`), `app/templates/compositions_list.html`, `app/templates/operation_detail.html` (retired badge)

**Key decisions:**
- `get_albion_composition` (single-row lookup) is NOT filtered — allows existing operations to display retired composition names.
- Attach-plan dropdown explicitly calls `get_albion_compositions(include_deleted=False)`.
- `albion_composition.deleted` event is audit-only (not dispatchable).
- No deletion of `composition_slot_templates` — existing slot templates remain available for inspection.

**Tests:** `test_composition_soft_delete.py` (20 tests)

---

### 25. Operation Timeline Hardening

**Type:** UX / Infra

**Description:** Redesigned `operation_timeline.html` from a raw event dump into a readable vertical timeline. Events displayed newest-first. Each entry shows: formatted date/time, a group badge (lifecycle / plan / signups / assignments / readiness / attendance / discord / other), human-readable label, actor info, and a `<details>` disclosure for the raw JSON payload.

**Major files:** `app/routes.py` (`_EVENT_LABELS` mapping, `_enrich_timeline_events` helper), `app/templates/operation_timeline.html` (full redesign), `app/templates/base.html` (group badge CSS, timeline layout CSS)

**Key decisions:**
- `_EVENT_LABELS` maps every event type that can appear on an operation timeline to `(group, human_label)`. Non-covered events fall back to a safe "other" group with the raw type as label.
- `_enrich_timeline_events` is a plain Python function passed into the template context — not a global Jinja filter.
- Raw payload available via `<details class="timeline-payload">` — not hidden, but not primary.
- No event deletion, editing, or filtering.

**Tests:** `test_timeline_display.py` (13 tests)

---

### 26. Planner Assignment Ergonomics

**Type:** UX / Planner

**Description:** Five targeted improvements to reduce officer clicks and scanning time during live roster building. Unassigned signups table replaced with dense, scannable `.signup-card` flex-wrap cards showing name, role badge, build, and availability. Quick assign button promoted to `btn-primary` as the first action on open slots. Manual assign (dropdown + Assign button) moved into a `<details class="slot-manual-assign"><summary>Manual assign</summary>` secondary disclosure. Reserve / Bench panel collapsed into `<details>` by default. Readiness strip made sticky on wide screens (`position: sticky; top: 3.5rem`) via `.readiness-sticky` class.

**Major files:** `app/templates/operation_planner.html`, `app/templates/base.html` (`.signup-card`, `.slot-manual-assign`, `.readiness-sticky`)

**Key decisions:**
- All POST targets and form field names unchanged — only visual hierarchy changed.
- `.signup-card__meta` suppresses willingness when value is "specific" (the default, least informative) and availability when value is "confirmed".
- Reserve panel collapse uses the existing `discord-preview-details` CSS class — no new pattern needed.
- Sticky readiness strip activated at `@media (min-width: 960px)` only — does not affect narrow screens.

**Tests:** `test_planner_ergonomics.py` (12 tests)

---

### 27. Signup Withdrawal

**Type:** UX / Data Management

**Description:** Players and officers can withdraw a signup intent without destroying any historical record. `signup_intents.withdrawn_at TEXT NULL` added via column migration. Withdrawal is allowed only in `planning` and `locked` statuses; blocked in `draft`, `completed`, and `archived`. Officers and owners may withdraw any signup. Members may withdraw only their own (display-name match — dev-auth phase, with code comment flagging the future identity-link requirement). Active slot assignment blocks withdrawal — the officer must remove the assignment first. Withdrawn signups disappear from the signup page list, the planner unassigned panel, and readiness/signup calculations. All historical records (participants, assignments, attendance, operational_events) are preserved.

**Major files:** `app/schema.sql` (`withdrawn_at TEXT NULL`), `app/database.py` (`_COLUMN_MIGRATIONS`), `app/repositories.py` (`get_signup_intent_by_id`, `withdraw_signup_intent`, `count_active_assignments_for_participant_in_operation`; `get_signup_intents` / `get_signups_with_display_names` / `get_participants_for_operation` all filter `withdrawn_at IS NULL`), `app/application/use_cases.py` (`withdraw_signup_intent`), `app/routes.py` (POST `/signups/{signup_id}/withdraw`, `_EVENT_LABELS` entry), `app/domain/operational_events.py` (`SIGNUP_INTENT_WITHDRAWN`), `app/templates/operation_signup.html` (Withdraw button column)

**Key decisions:**
- Soft-delete via `withdrawn_at` timestamp — no `status` enum change, no hard delete.
- `completed` and `archived` statuses block withdrawal to preserve post-operation signup history intact.
- Member ownership check uses display-name comparison for the dev-auth phase; a comment in use_cases.py and the test file documents the future identity-link requirement.
- Active assignment guard requires the officer to explicitly unassign first, preserving assignment audit integrity.
- `signup_intent.withdrawn` event is audit-only and not in `DISPATCHABLE_EVENT_TYPES`.
- Timeline label "Signup withdrawn" added to `_EVENT_LABELS` under the `signups` group.

**Tests:** `test_signup_withdrawal.py` (24 tests)

---

### 28. Operation Status Urgency Coloring

**Type:** UX / CSS

**Description:** Subtle per-status accent stripe applied to all operation sub-pages via a `data-op-status` attribute on the `<main>` element. A single `--op-status-accent` CSS custom property is scoped to each status value and consumed as a `border-top: 3px solid` rule on `.operation-tabs`. Colors mirror the existing `.badge-*` palette — no new hues introduced. Non-operation pages are unaffected; the `{% block main_attrs %}` hook in `base.html` is never set on workspace, dashboard, or settings pages.

**Status → accent colour:**
- `draft` → #adb5bd (cool grey)
- `planning` → #4a9eda (soft blue)
- `locked` → #c9a227 (amber)
- `completed` → #3a9a5c (green)
- `archived` → #868e96 (muted grey)

**Major files:** `app/templates/base.html` (`{% block main_attrs %}` hook + 11 lines of scoped CSS), `app/templates/operation_detail.html`, `app/templates/operation_planner.html`, `app/templates/operation_attendance.html`, `app/templates/operation_timeline.html`, `app/templates/operation_signup.html` (one line each)

**Key decisions:**
- CSS custom property approach keeps all color logic in one place — changing a status accent requires editing one line.
- `{% block main_attrs %}` is an empty block by default, so non-operation templates need zero changes.
- Only `.operation-tabs` consumes the variable — no backgrounds, shadows, or icon changes.
- No route, domain, schema, or use-case changes.

**Tests:** `test_op_status_coloring.py` (10 tests)

---

### 30. Discord OAuth Login

**Type:** Auth / Production Readiness

**Description:** Discord OAuth2 login flow alongside the existing dev display-name login. Dev login remains available in `IRONKEEP_ENV=dev` and is blocked in production (POST `/login` returns 403). Discord OAuth users are created with `auth_provider='discord'` and their stable Discord snowflake as `provider_user_id`. No workspace membership is granted automatically — an officer must add members manually. No merging of existing dev-auth users with Discord identities. If OAuth env vars are missing the app does not crash; the login page shows a "Discord OAuth is not configured" message and `GET /auth/discord` returns 503.

**OAuth flow:**
1. `GET /auth/discord` — generates a random `state` token, stores it in the session alongside a validated `oauth_next` path, redirects to Discord authorization URL.
2. Discord callback `GET /auth/discord/callback` — validates CSRF state, exchanges code for access token, fetches `/users/@me` identity, calls `discord_oauth_login` use case to find or create the user, sets session, redirects to `oauth_next`.

**Security:**
- CSRF protection via per-session `state` token compared on callback.
- `oauth_next` validated by `_safe_next()` before storing or redirecting: must start with `/` and not `//`. Invalid or absent values fall back to `/`.
- Discarding session state before redirect prevents state reuse.

**Environment variables added to `.env.example`:** `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_OAUTH_REDIRECT_URI`.

**Account linking:** Not implemented. Dev users and Discord users are separate records. Identity linking (connecting a dev-auth user to a Discord identity) is a future slice.

**Major files:** `app/auth/discord_oauth.py` (new — thin httpx wrapper, `is_oauth_configured`, `build_authorization_url`, `exchange_code`, `fetch_user_identity`, `DiscordOAuthError`; 5 s timeout on every call), `app/domain/users.py` (`DISCORD_AUTH_PROVIDER = "discord"`), `app/application/use_cases.py` (`discord_oauth_login`), `app/routes.py` (`_is_production()` function, `_safe_next()` helper, updated `GET /login` + `POST /login`, new `GET /auth/discord` + `GET /auth/discord/callback`), `app/main.py` (startup warning for missing OAuth vars — warning in production, info in dev; no crash), `app/templates/login.html` (rewritten: production shows Discord-only button or "not configured" error; dev shows display-name form plus optional Discord button), `.env.example`

**Key decisions:**
- Missing OAuth vars do not crash the app — `is_oauth_configured()` reads env vars at call time.
- `_is_production()` is a function, not a module-level constant, so env patches in tests take effect without restarting the module.
- Dev login (`POST /login`) returns HTTP 403 in production — not a redirect, not a soft disable.
- `discord_oauth_login` uses the stable Discord snowflake (`id`) as `provider_user_id`, not the mutable `username`. Display name is updated if the Discord `global_name` / `username` has changed since last login.
- No automatic workspace membership — the officer workflow for adding members is unchanged.
- `DiscordOAuthError` is a subclass of `IronkeepError` — all callback error paths redirect to `/login?error=...`.
- All Discord HTTP calls (`exchange_code`, `fetch_user_identity`) are mocked in tests — no real API calls.

**Tests:** `test_discord_oauth.py` (25 tests)

---

### 29. Discord Dispatcher Outbound Execution (Readiness Only)

**Type:** Discord / Infra

**Description:** Completed the post-commit dispatch execution path for `readiness_snapshot.created` events. The dispatcher now makes real Discord REST calls when both safety gates are enabled, posting or editing a `message_type="readiness"` message in the announcement channel. All other event types (`guild_operation.published/locked/completed`, signup, attendance) remain resolved-and-logged only — announcements and rosters are still explicit officer actions.

**Scope of auto-dispatch:**

| Event | Behaviour |
|---|---|
| `readiness_snapshot.created` | post or edit readiness summary (when both gates on) |
| `guild_operation.published` | resolved/logged only — **no auto-post** |
| `guild_operation.locked` | resolved/logged only — **no auto-edit** |
| `guild_operation.completed` | resolved/logged only — **no auto-edit** |
| All others | noop as before |

**Safety gates (both required):**
1. `DISCORD_DISPATCH_ENABLED=1` env var — process-level kill switch, default off.
2. `guild_workspaces.discord_auto_dispatch = 1` — per-workspace opt-in, default `0`.

**Execution flow (two-phase):**
- Phase 1: `resolve_action(event, db)` reads DB state, closes transaction.
- Phase 2: REST call (`post_message` or `edit_message`) outside any transaction.
  - On `edit_message` 404: falls back to `post_message` (message deleted externally).
- On REST success: `upsert_discord_message` in a new transaction.
- On REST failure: `discord_dispatch_failures` row written in a separate transaction. Never raises.

**No scheduler or retry loop.** Failures accumulate in `discord_dispatch_failures` for future retry handling. `dispatch()` is synchronous and best-effort.

**Major files:** `app/discord/dispatcher.py` (`_EXECUTABLE_EVENT_TYPES`, `_is_execution_enabled`, `_execute_action`, `_record_failure_direct`, full `dispatch()` implementation), `app/schema.sql` + `app/database.py` (`discord_auto_dispatch` column migration), `app/repositories.py` (`update_workspace_discord_config` gains `auto_dispatch` param), `app/application/use_cases.py` (`update_workspace_discord_config` threads flag through), `app/routes.py` (reads `discord_auto_dispatch` form field), `app/templates/workspace_discord_settings.html` (opt-in checkbox)

**Key decisions:**
- `_EXECUTABLE_EVENT_TYPES = frozenset({READINESS_SNAPSHOT_CREATED})` — enforced in code, not just convention. Non-readiness events never reach `_execute_action` even if `resolve_action` returns a non-noop action.
- Announcements and rosters remain explicit officer actions ("Post to Discord" / "Update Roster Post" buttons) regardless of any flag.
- `discord_auto_dispatch` defaults to `0` — no workspace auto-dispatches without an explicit opt-in.
- Settings page copy explicitly states "readiness updates only — announcements and rosters are never auto-posted."
- Failure rows in `discord_dispatch_failures` accumulate for future retry slice; no automatic retry in this slice.
- Architectural invariant updated: "OperationalEvents drive dispatcher resolution; only `readiness_snapshot.created` triggers REST execution."

**Tests:** `test_dispatcher_execution.py` (20 tests)

---

### 31. Account Linking (Dev User → Discord Identity)

**Type:** Auth / Identity

**Description:** Allows an existing dev-login user to link their account to a Discord OAuth identity without losing workspace memberships, historical audit ownership, or any other references. The stable `users.id` is preserved throughout — no rows are rewritten. A separate `user_auth_identities` table stores multiple login credentials per user (`dev` and `discord`). Login resolution checks `user_auth_identities` first, then falls back to the legacy `users.auth_provider`/`provider_user_id` columns for backward compatibility.

**Identity model:**
- `users.id` is the permanent account identity. `workspace_members.user_id` and `operational_events.actor_id` are never rewritten.
- New `user_auth_identities` table: `(user_id, auth_provider, provider_user_id, created_at)` with `UNIQUE (auth_provider, provider_user_id)` and `UNIQUE (user_id, auth_provider)` constraints.
- New Discord OAuth and dev users both get a `user_auth_identities` row on creation.
- Existing users are backfilled from `users.auth_provider`/`provider_user_id` via a `_DATA_MIGRATIONS` entry (idempotent `INSERT OR IGNORE`).

**Link flow:**
1. Logged-in dev user clicks "Link Discord Account" on `/account`.
2. `GET /auth/discord/link` validates eligibility (dev identity, no existing Discord identity), stores `linking=True` in session, redirects to Discord OAuth.
3. `GET /auth/discord/link/callback` validates state, fetches Discord identity, calls `link_discord_identity`.
4. If another user already claims that snowflake with no workspace references (orphan), it is atomically deleted. If the colliding user has references, `ConflictError` is raised and the linking is aborted.
5. A `user_auth_identities` row is inserted for the current user. `users.auth_provider` and `users.display_name` are never mutated during linking.
6. `user.discord_linked` events are emitted per workspace membership (audit-only, not dispatchable).

**Security:** Linking requires Discord re-authentication. Conflict resolution never silently overwrites a user with active references. Discord OAuth proves identity only — no automatic workspace membership or display-name overwrite.

**Display name policy:** For linked (dev + Discord) users, Discord's `global_name` / `username` is suppressed on future Discord logins — the existing app display name is preserved. For pure Discord users (no dev identity), display name auto-updates continue.

**Major files:** `app/schema.sql` (new `user_auth_identities` table), `app/database.py` (`_DATA_MIGRATIONS` backfill), `app/domain/operational_events.py` (`USER_DISCORD_LINKED`), `app/repositories.py` (`get_user_by_provider_identity` updated; new `insert_user_auth_identity`, `get_auth_identity`, `get_auth_identities_for_user`, `count_user_references`, `delete_user_and_identity`), `app/application/use_cases.py` (`link_discord_identity`, `_handle_orphan_or_block`, `_make_auth_identity`; updated `discord_oauth_login`, `dev_login_or_create_user`), `app/auth/discord_oauth.py` (`exchange_code_with_redirect` for distinct link redirect URI), `app/routes.py` (new `GET /account`, `GET /auth/discord/link`, `GET /auth/discord/link/callback`), `app/templates/account.html` (new), `app/templates/base.html` (My Account nav link, identity badge CSS), `.env.example` (`DISCORD_OAUTH_LINK_REDIRECT_URI`)

**Key decisions:**
- `user_auth_identities` instead of in-place `users` mutation — multiple credentials per account, stable `users.id`.
- No unlinking in this slice — forward-only identity enrichment.
- No automatic display-name merge — officer or explicit user action required.
- Orphan cleanup is atomic: only safe when the colliding user has zero `workspace_members` and `operational_events` references.
- `user.discord_linked` is workspace-scoped (one event per membership) and audit-only (not dispatchable).

**Tests:** `test_account_linking.py` (35 tests — use case coverage, repository lookup, backfill migration, orphan cleanup, conflict handling, HTTP route tests; all Discord API calls mocked)

---

### 32. Discord Metadata Cache

**Type:** Discord / UX / Data Management

**Description:** Caches Discord guild and channel names in the database so that raw snowflakes are replaced with readable names throughout the web UI. No Discord SDK. Uses the existing `rest_client.py` / `httpx` pattern. Metadata fetch failures never block or roll back any domain transaction.

**What is cached:**
- `entity_type = 'guild'` — guild `name`, `icon_hash` stored in `extra_json` (not rendered yet).
- `entity_type = 'channel'` — channel `name`, `channel_type` stored in `extra_json`.
- Roles are not cached in this slice.

**Refresh triggers:**
1. Automatic best-effort refresh after `POST /settings/discord` saves (fires after the config transaction commits; failure is silently swallowed — the config save always succeeds).
2. Manual "Refresh Discord Names" / "Fetch Discord Names" button on the settings page (owner/officer only).

**Failure behaviour:** On any REST error (404, timeout, non-2xx) the stale cache row is preserved — a stale name is better than no name. Each guild and channel fetch is wrapped independently so a channel failure never aborts the guild fetch and vice versa.

**Staleness:** Cache rows older than 24 hours (`_METADATA_CACHE_TTL_HOURS`) are marked `is_stale=True` by the `_enrich_discord_meta()` route helper. The settings page shows a `(stale)` badge next to the name and a ⚠ prefix on the Refresh button.

**Display:** The `discord_name(snowflake, meta_dict)` Jinja2 macro (in `app/templates/_discord_macros.html`) renders:
- Cache hit: `"Name · …last4"` (with optional `(stale)` suffix)
- Cache miss: `"…last4"` (truncated snowflake in `<code>`)

**Pages updated:** Discord settings page (names + refresh button + stale indicator), operation detail (Discord preview footer), operation planner (roster preview footer).

**Major files:** `app/schema.sql` (new `discord_metadata_cache` table with `UNIQUE (guild_workspace_id, entity_type, discord_entity_id)`), `app/discord/rest_client.py` (`fetch_guild_metadata`, `fetch_channel_metadata`), `app/repositories.py` (`upsert_discord_metadata`, `get_discord_metadata`, `get_discord_metadata_map`), `app/application/use_cases.py` (`refresh_discord_metadata`, `_METADATA_CACHE_TTL_HOURS`), `app/routes.py` (`_enrich_discord_meta` helper; updated `GET /settings/discord`, `POST /settings/discord`; new `POST /settings/discord/refresh-metadata`; `discord_meta` passed to `get_operation_detail` and `get_planner`), `app/templates/_discord_macros.html` (new — `discord_name` macro), `app/templates/workspace_discord_settings.html` (rewritten — names, refresh button, stale indicator), `app/templates/operation_detail.html` + `operation_planner.html` (Discord preview footers use macro)

**Key decisions:**
- No Discord SDK in `app/` — uses existing `httpx` REST client pattern.
- Guild and channel metadata only — no role caching yet.
- Metadata fetch failures are swallowed at the call site; they never reach the HTTP response or roll back config saves.
- Stale rows are preserved on failure — never deleted on error.
- `get_discord_metadata_map` fetches all rows for a workspace in one query (no N+1 per snowflake).
- Manual refresh is owner/officer only; regular members cannot trigger it.
- `icon_hash` stored in `extra_json` for future CDN icon rendering, but no icons rendered in this slice.

**Tests:** `test_discord_metadata_cache.py` (26 tests — repository CRUD, upsert-on-conflict, REST client mocking for 200/404/timeout, use-case failure isolation, refresh-on-save behaviour, settings save not blocked by fetch failure, refresh route RBAC, template rendering for name display/truncated ID/stale indicator)

---

### 33. Attendance Rollup / Player Reliability Scores

**Type:** Attendance / Infra / UX

**Description:** Officer-facing read-model providing attendance reliability context during planning. Calculates a rolling `present / total` ratio per player across the last 90 days of resolved operations. No schema changes — derived entirely from existing `attendance_records` and `assignments` data. No automation, no punitive gating, no auto-assignment.

**Score formula:**
- Numerator: `status IN ('present', 'late')` attendance records.
- Denominator: `status IN ('present', 'late', 'absent', 'no_show')` — excused excluded.
- Only records linked to an `assignments` row are counted (withdrawn signups and unassigned signups excluded by construction).
- Only operations with `status IN ('locked', 'completed')` are counted (draft/planning excluded).
- Rolling 90-day window based on `readiness_snapshots.created_at` or `attendance_records.recorded_at`.
- Minimum threshold: 3 resolved assignments required before a score is displayed (below threshold → `—`).

**Key design decisions:**
- Scores keyed by `participant_id`, not `display_name` — avoids dev-era identity debt.
- Single aggregate SQL query (`get_player_reliability_scores`) — no N+1 queries.
- `RELIABILITY_WINDOW_DAYS = 90` and `RELIABILITY_MIN_OPS = 3` as named constants in `use_cases.py`.
- No writes, no mutations, no sorting by score.
- Officer-facing only where avoidable — ordinary members cannot see reliability columns.

**Display format:** Primary `N/D` (e.g. `7/9`), optional secondary percentage. Colour classes: `rel-green` (≥80%), `rel-amber` (50–79%), `rel-red` (<50%).

**Pages updated:**
- `operation_planner.html` — `★ 7/9 ops` compact badge on unassigned signup cards (gated by `can_mutate`).
- `operation_attendance.html` — "Reliability" column showing `N/D · X%` or `—` (officer-only).
- `workspace_members.html` — "Attendance (90d)" column; bridges `display_name → participant_id` via a `participant_id_by_name` map built in the route.

**Major files:** `app/repositories.py` (`get_player_reliability_scores`, `get_participants_for_workspace`), `app/application/use_cases.py` (`RELIABILITY_WINDOW_DAYS`, `RELIABILITY_MIN_OPS`), `app/routes.py` (`get_planner`, `get_attendance`, `get_workspace_members` — each loads scores once), `app/templates/operation_planner.html`, `app/templates/operation_attendance.html`, `app/templates/workspace_members.html`, `app/templates/base.html` (`rel-green`, `rel-amber`, `rel-red`, `.signup-card__rel` CSS)

**Tests:** `test_player_reliability.py` (28 tests — score calculation, excused exclusion, minimum threshold, rolling window, workspace isolation, withdrawn signup exclusion, draft/planning exclusion, empty workspace, planner/attendance/members template rendering, no output below threshold)

---

### 34. Scheduler + Dispatch Retry Foundation

**Type:** Infra / Discord / Reliability

**Description:** Temporal infrastructure for IronkeepV2 without an external queue. A separate scheduler process (`python -m app.scheduler`) runs a plain polling loop, calling job functions directly — no APScheduler, no Celery, no Redis. The process exits immediately unless `SCHEDULER_ENABLED=1` is set, making it safe to omit in development.

**Two jobs shipped in this slice:**

1. **`retry_dispatch_failures`** — retries all `discord_dispatch_failures` rows in `status='pending_retry'` whose `next_attempt_at` backoff window has expired. Routes through the same `resolve_action` → `_EXECUTABLE_EVENT_TYPES` → `_is_execution_enabled` gates as the live dispatcher. On success: upserts `discord_messages`, marks row `resolved`. On failure: increments `retry_count`, advances `next_attempt_at`. At `MAX_RETRIES = 3` failures: marks row `exhausted`. If either safety gate is off, leaves rows `pending_retry` — they are not force-resolved.

2. **`refresh_stale_metadata`** — calls `refresh_discord_metadata` for every workspace where any `discord_metadata_cache` entry is older than `METADATA_STALE_HOURS = 24` hours, or where no cache entries exist.

**Backoff schedule:**
| retry_count | Wait before next attempt |
|---|---|
| 0 | 5 minutes |
| 1 | 30 minutes |
| 2 | 2 hours |
| 3 | exhausted |

**Schema additions (column migrations, no CREATE TABLE changes to `discord_dispatch_failures`):**
- `discord_dispatch_failures.payload_json TEXT NOT NULL DEFAULT '{}'` — original event payload for auditing.
- `discord_dispatch_failures.next_attempt_at TEXT NOT NULL DEFAULT ''` — ISO-8601 UTC timestamp for backoff scheduling. Empty string = immediately due (legacy rows).
- New `scheduler_runs` table — one row per job execution: `id, job_name, started_at, finished_at, status ('running'|'success'|'error'), result_json, error_message`. `finished_at IS NULL` + `status='running'` is the crash-detection sentinel.

**Safety rules enforced in code (not just convention):**
- Scheduler jobs may only read DB state, write `discord_dispatch_failures` status/retry fields, write `discord_metadata_cache`, and write `scheduler_runs`.
- Scheduler jobs may NOT mutate operation status, create/remove assignments, post announcements or rosters, or grant workspace memberships.
- The readiness-only dispatch policy (`_EXECUTABLE_EVENT_TYPES`) is enforced at the dispatcher layer — the retry job cannot bypass it.

**Observability:** `scheduler_runs` table queryable via SQLite. Each job execution logs result summary to stdout. Crash detection via `finished_at IS NULL`.

**Major files:** `app/scheduler/__init__.py`, `app/scheduler/jobs.py` (`retry_dispatch_failures`, `refresh_stale_metadata`, `run_job`, `write_scheduler_run_start/finish`, backoff helpers), `app/scheduler/__main__.py` (entry point, polling loop, `SCHEDULER_ENABLED` gate), `app/schema.sql` (new `scheduler_runs` table), `app/database.py` (two `_COLUMN_MIGRATIONS` for `discord_dispatch_failures`), `app/repositories.py` (`get_pending_dispatch_failures_due`, `resolve_dispatch_failure`, `bump_dispatch_failure`, `exhaust_dispatch_failure`, `insert_scheduler_run`, `update_scheduler_run_finished`, `get_scheduler_run`, `get_workspaces_needing_metadata_refresh`; updated `insert_discord_dispatch_failure`), `app/discord/dispatcher.py` (`_record_failure_direct` updated — writes `payload_json` + `next_attempt_at`), `app/events.py` (`_record_failure` updated — same columns)

**Key decisions:**
- Separate process — clean isolation from web process, no contention on Uvicorn event loop.
- Plain `while True` + `time.sleep` polling loop — zero new runtime dependencies (no APScheduler).
- `SCHEDULER_ENABLED` gate — process exits cleanly when not set; safe to exclude from dev.
- Gate-off behaviour: if `DISCORD_DISPATCH_ENABLED=0` or `discord_auto_dispatch=0`, failure rows stay `pending_retry` — they are not prematurely resolved.
- No manual retry route in this slice — scheduler loop only.

**Tests:** `test_scheduler_jobs.py` (32 tests — core retry logic, gate behaviour, noop resolution, exhaustion, future-backoff skip, discord_messages upsert on success, edit→404→post fallback, non-executable event type resolution, metadata refresh with stale/missing/fresh/no-discord/multi-workspace/error-resilience scenarios, scheduler_run observability, crash detection, run_job wrapper, backoff correctness, `_record_failure_direct` column verification)

---

### 35. Scheduler Admin / Observability UI

**Type:** Infra / UX

**Description:** Read-only scheduler health page for workspace owners and officers. Accessible at `GET /workspaces/{slug}/settings/scheduler`. No job execution, no retry buttons, no scheduler controls. Members cannot access the page (403). Unauthenticated users are redirected to login.

**Three sections:**
1. **Health banner** — four states: `never_run` (info, shows start command), `ok` (green), `stale` (warning, no run in >15 min), `stuck` (warning, a running job with no `finished_at` older than 10 min). A job started within the stuck window remains `running`, not `stuck` — avoids false positives on in-progress jobs.
2. **Pending dispatch failures** — workspace-scoped count of `discord_dispatch_failures WHERE status='pending_retry'`, or a "No pending" confirmation.
3. **Recent runs table** — up to 60 rows ordered `started_at DESC, id DESC` (stable). Columns: Job, Started, Duration, Status, Summary. Status badges: `success` (green), `error` (red), `running` (blue), `stuck` (amber italic). Duration computed from timestamps; unfinished rows show `—`. Rows with `status='running'` and no `finished_at` older than the stuck threshold get `.row-stuck` highlight. `result_json` rendered as `key: val · key: val` summary; full raw JSON in a `<details>` disclosure. Error messages inline below the summary.

**Route helpers (pure functions, unit-tested independently):**
- `_format_utc(ts)` — ISO-8601 → `"YYYY-MM-DD HH:MM UTC"`
- `_parse_result_summary(result_json)` — top-level primitives → compact string; `"(invalid result_json)"` on parse failure
- `_compute_duration(started_at, finished_at)` — seconds or minutes; `"—"` for unfinished
- `_run_badge_status(run, stuck_cutoff)` — `"success" | "error" | "running" | "stuck"`
- `_enrich_scheduler_run(run, stuck_cutoff)` — adds all computed fields to raw row
- `_scheduler_health(runs, stale_cutoff, stuck_cutoff)` — derives health state; stuck takes priority over stale

**Constants:** `SCHEDULER_STALE_THRESHOLD_MINUTES = 15`, `SCHEDULER_STUCK_THRESHOLD_MINUTES = 10`

**Note on scope:** `scheduler_runs` is a global process-level table (not workspace-scoped). All workspace owners/officers see the same run history. The per-workspace metric is the `discord_dispatch_failures` pending count, which is workspace-scoped.

**Navigation:** "Scheduler" link added to workspace nav alongside "Settings", visible only when `can_mutate` (owner or officer).

**No schema changes.** All data comes from `scheduler_runs` and `discord_dispatch_failures` tables added in slice 34.

**Major files:** `app/repositories.py` (`get_recent_scheduler_runs`, `get_latest_scheduler_run`, `get_stuck_scheduler_runs`, `count_pending_dispatch_failures`), `app/routes.py` (route + six helper functions + two threshold constants), `app/templates/workspace_scheduler_status.html` (new), `app/templates/workspace_nav.html` (Scheduler nav link), `app/templates/base.html` (`badge-success`, `badge-error`, `badge-running`, `badge-stuck`, `.sched-table`, `.row-stuck`, `.result-details` CSS)

**Key decisions:**
- Read-only only — no POST routes, no mutation, `can_mutate=False` explicit in template context.
- Stuck detection requires both `finished_at IS NULL` and age > threshold — avoids marking a currently-running job as stuck.
- `_parse_result_summary` excludes nested objects/arrays — only top-level primitive values are surfaced in the summary line.
- Invalid `result_json` renders a safe `"(invalid result_json)"` string rather than crashing the page.
- Workspace-scoped failure count is the only per-workspace metric; run history is intentionally global.

**Tests:** `test_scheduler_status.py` (48 tests — access control, never_run/ok/stale/stuck banners, recent-running-not-stuck, success/error/stuck/running badges, error message rendering, result_json summary, invalid JSON safety, `<details>` disclosure, pending failure count, zero failures message, workspace scoping of failure count, stable ordering, POST 405, and unit tests for all six pure helper functions)

---

### 36. Operation Reminder Jobs

**Type:** Infra / Discord

**Description:** Scheduler job that sends pre-operation reminder posts to the announcement (or officer) channel at T-2h and T-30m before each planning or locked operation. Per-workspace opt-in via a new `discord_reminders_enabled` checkbox on the Discord settings page. All delivery state is tracked in a new `operation_reminder_deliveries` table, ensuring exactly-once delivery across scheduler restarts and crash recovery.

**Invariants (enforced in code):**
- Reminders are scheduler-owned, NOT dispatcher-owned.
- Reminders NEVER use operational events.
- Reminders NEVER touch `discord_messages`.
- Reminders ALWAYS create new posts (never edit).
- Reminders are informational only — no lifecycle or assignment mutations.
- Only `planning` and `locked` operations are eligible.
- Reminders NEVER fire at or after `scheduled_start_at`.
- Retries NEVER fire outside the reminder grace window.
- `skipped` status is mandatory when the window closes without sending.
- Stale `claimed` rows (older than `REMINDER_CLAIM_TIMEOUT_SECONDS = 600`) are reclaimable and retryable.
- Formatter is pure: no DB access, no SDK imports, equal output for equal input.
- Readiness snapshot is optional and never recomputed live.
- The `When` embed field always shows explicit UTC.

**Claim/finalize flow (retry-safe):**
1. `INSERT OR IGNORE` to ensure a delivery row exists for `(operation, window)`.
2. Atomic `UPDATE status='claimed'` WHERE `status='pending'` OR `(status='claimed' AND claimed_at <= stale_cutoff)` — returns `rowcount=1` on success.
3. REST `post_message` call outside any DB transaction.
4. `UPDATE status='sent'` on REST success; row stays `claimed` on REST failure (stale-claim timeout enables retry on next scheduler run while still within the grace window).
5. `UPDATE status='skipped'` when the operation is no longer eligible or the window has closed.

**Reminder windows:**
- `T-2h`: fires when `now >= scheduled_start_at - 2h` and `now < scheduled_start_at`.
- `T-30m`: fires when `now >= scheduled_start_at - 30m` and `now < scheduled_start_at`.

**Channel preference:** announcement channel first; officer channel as fallback. If neither is configured the workspace is excluded from the eligible query (requires at least one channel).

**Schema additions:**
- `operation_reminder_deliveries` table (`id`, `guild_workspace_id`, `guild_operation_id`, `reminder_window`, `status`, `claimed_at`, `sent_at`, `skipped_at`, `skip_reason`, `created_at`; `UNIQUE (guild_operation_id, reminder_window)`).
- `guild_workspaces.discord_reminders_enabled INTEGER NOT NULL DEFAULT 0` (column migration).

**Major files:** `app/schema.sql` (new `operation_reminder_deliveries` table + indexes), `app/database.py` (`discord_reminders_enabled` column migration), `app/discord/formatters.py` (`format_operation_reminder` — pure, amber color, explicit UTC `When` field, optional readiness, no components), `app/repositories.py` (`get_operations_eligible_for_reminders`, `get_reminder_delivery`, `try_claim_reminder_delivery`, `finalize_reminder_delivery`, `skip_reminder_delivery`; `update_workspace_discord_config` gains `reminders_enabled` param), `app/application/use_cases.py` (`update_workspace_discord_config` threads `reminders_enabled` through), `app/routes.py` (reads `discord_reminders_enabled` form field), `app/templates/workspace_discord_settings.html` (new opt-in checkbox), `app/scheduler/jobs.py` (`REMINDER_WINDOWS`, `REMINDER_CLAIM_TIMEOUT_SECONDS`, `send_operation_reminders`, `_process_reminder_window`, `_reminder_channel`), `app/scheduler/__main__.py` (registers `send_operation_reminders` in the polling loop)

**Key decisions:**
- `operation_reminder_deliveries` is the deduplication mechanism — a `UNIQUE (guild_operation_id, reminder_window)` constraint ensures no double-delivery even across restarts.
- Stale claim recovery: `REMINDER_CLAIM_TIMEOUT_SECONDS = 600`; a claimed row older than 10 minutes is reclaimable. This means a REST failure can be retried on the next scheduler run as long as we're still within the grace window.
- No `discord_messages` writes — reminders are ephemeral channel posts, not tracked editable messages.
- No `operational_events` writes — reminders are infrastructure, not domain events.
- `discord_reminders_enabled` is independent of `discord_auto_dispatch` — both flags default to 0 and must be explicitly opted in.
- The formatter uses a fixed amber color (`0xF39C12`) instead of status-derived colors, signalling "informational" rather than operation state.
- `get_operations_eligible_for_reminders` requires both a Discord guild link AND at least one channel configured — if neither channel is set, the workspace is simply excluded from the query rather than requiring a per-window skip.

**Tests:** `test_operation_reminders.py` (76 tests — formatter purity/UTC/fields/color/readiness, repository claim/finalize/skip/stale-recovery/already-done, eligible query filters, job happy path, not-yet-due windows, stale claim recovery, REST failure resilience, ineligibility after claim, no-channel handling, reminders disabled/no-Discord gates, multiple windows per op, multiple operations, workspace isolation, past-start skip, scheduler_run observability, settings round-trip HTTP, module boundary invariants — no discord_messages writes, no operational_events writes, no SDK imports, formatter purity)

---

### 43. Operational Health + Diagnostics Foundation

**Type:** Infra / UX

**Description:** Adds production survivability infrastructure: a centralised diagnostics module, startup validation, an unauthenticated `/health` JSON endpoint, and a workspace-scoped diagnostics settings page. No external monitoring stack required.

**`app/diagnostics.py`** (new) — single source of truth for health logic:
- `SCHEDULER_STALE_MINUTES = 15` / `SCHEDULER_STUCK_MINUTES = 10` (re-used by routes.py constants for backward compat)
- `format_utc(ts)` — ISO-8601 → "YYYY-MM-DD HH:MM UTC", "—" for absent/bad values
- `is_stale(ts, threshold_minutes, now=None)` — deterministic staleness predicate
- `scheduler_health(runs, now=None)` → `{status, message, last_seen_at}` — centralised health state computation
- `db_health(db)` → `{reachable, wal_mode}` — single PRAGMA query, no mutation

**`app/startup.py`** (new) — startup validation called from lifespan:
- `check_db_writable(db_path)` — parent dir and file writability
- `check_core_tables(db)` — verifies required tables (`users`, `guild_workspaces`, `workspace_members`, `scheduler_runs`, `discord_dispatch_failures`, `payout_ledger_entries`) exist after `init_schema()`
- `validate(db_path, is_production)` → `list[str]` warnings; raises `RuntimeError` on fatal issues

**`app/main.py`** — `startup.validate()` wired into the `lifespan` hook; warnings logged, fatal errors surface before the app accepts traffic.

**Repository additions:**
- `get_global_pending_retry_count(db)` — pending retries across all workspaces
- `get_recent_error_run_count(db, hours=24)` — failed scheduler_runs in a rolling window
- `get_last_scheduler_run_at(db)` — most recent `started_at` (lightweight heartbeat read)

**Routes:**
- `GET /health` — unauthenticated JSON; fields: `status`, `db_reachable`, `wal_mode`, `scheduler`, `scheduler_last_seen_at`, `pending_retries`, `recent_error_runs_24h`. Returns 503 when degraded (stuck job or DB unreachable). No secrets exposed.
- `GET /workspaces/{slug}/settings/diagnostics` — officer/owner-gated HTML page showing DB state, scheduler health banner, retry backlog (global + workspace), recent error count, links to `/health` and scheduler settings.

**`workspace_nav.html`** — "Diagnostics" link added alongside Settings/Scheduler (officer/owner gate unchanged).

**Key decisions:**
- Existing `_format_utc`, `_scheduler_health`, `SCHEDULER_STALE_THRESHOLD_MINUTES` etc. in routes.py remain unchanged — diagnostics.py is additive, not a refactor, ensuring zero test regressions.
- `/health` returns 503 only for truly degraded states (stuck job, DB unreachable) — stale scheduler returns 200 with `scheduler: "stale"` since it's an ops concern, not a request-serving failure.
- Startup warnings are logged but not fatal (dev-friendly); `RuntimeError` reserved for DB path and table-presence failures that would make the app non-functional.

**Tests:** `test_operational_health.py` (57 tests — 12 test groups covering all helpers, startup, repository queries, `/health` endpoint, diagnostics page, stale detection consistency, and nav link visibility)

---

### 44. Backup / Restore + Recovery Hardening

**Type:** Infra

**Description:** Improves operational survivability and recovery confidence. Adds a dedicated `app/backup.py` module with WAL-aware backup, file metadata visibility, and restore validation. Extends the diagnostics page with DB size, WAL state, and operator-facing backup/restore guidance. No scheduled backups, no cloud integration, no external daemon.

**`app/backup.py`** (new):
- `human_size(size_bytes)` — byte count → compact string ("12.3 MB"), "—" for None
- `backup_filename(prefix, now)` — generates `{prefix}_YYYYMMDD_HHMMSS.db` using UTC (no local TZ ambiguity, no directory separators)
- `validate_backup_destination(dest_path)` — guards against: dest is a directory, parent missing, parent not writable, dest already exists (no silent overwrites)
- `create_backup(source_db_path, dest_path)` — WAL-aware hot backup via `sqlite3.Connection.backup()` (Python C API, no CLI, checkpoint-aware); returns `{source, dest, size_bytes, size_human, created_at}`
- `get_db_file_info(db_path)` — returns `{display_name (basename only), exists, size_bytes, size_human, modified_at (ISO UTC), wal_present, wal_size_bytes, wal_size_human}`. Display name is filename-only — no absolute path leaked to UI.

**`app/startup.py`** — added `check_integrity(db)`:
- Runs `PRAGMA integrity_check(1)` (fast, first-error-only)
- Raises `RuntimeError` if result is not `"ok"` with a clear restore message
- Suitable for post-restore validation before restarting the application

**`app/routes.py`** — extended `get_diagnostics`:
- Imports `backup` module
- Calls `backup.get_db_file_info(database._DB_PATH)` after the DB transaction closes
- Passes `db_file_info` context variable to the template

**`workspace_diagnostics.html`** — extended with:
- Database section now shows: file name, file size, last modified, WAL file present/size (alongside existing reachable/WAL-mode rows)
- New "Backup & Recovery" section with: backup recommendations (WAL-aware Python API, include WAL/SHM on OS-level copy, off-directory storage, periodic verification) and restore cautions (stop app before replacing DB, verify core tables, run integrity_check, data-loss notice for entries post-backup)

**Key decisions:**
- `display_name` is always `Path(db_path).name` — never the parent directory — so no filesystem layout is exposed in the HTML.
- `validate_backup_destination` refuses to overwrite existing files; operator must explicitly remove old backups before creating new ones.
- `check_integrity` uses `PRAGMA integrity_check(1)` (limit 1) for speed; full check (`PRAGMA integrity_check`) is documented as the manual operator step.
- No CLI shelling: `sqlite3.Connection.backup()` handles WAL checkpointing correctly without requiring the sqlite3 CLI or file-level copies.

**Tests:** `test_backup_restore.py` (60 tests — 8 test groups covering human_size, backup_filename, validate_backup_destination, create_backup WAL-aware behavior, get_db_file_info, check_integrity, diagnostics page backup section, and path sanitization)

---

### 45. Deployment Runbook + Process Supervision Foundation

**Type:** Docs / Infra

**Description:** Documents and standardises how IronkeepV2 runs in production. Adds a complete deployment runbook, shell start scripts, a Python backup CLI, and systemd service unit examples. No app-behavior changes. No Docker or cloud lock-in.

**`docs/deployment.md`** — full production runbook covering:
- Architecture overview (two-process model: web + scheduler)
- System requirements and Python version
- All environment variables (required, optional, safety rules)
- First-time setup procedure
- Web process startup (`uvicorn`, workers=1, WAL rationale)
- Scheduler process startup (safety guarantees, claim/finalize idempotency)
- SQLite / WAL notes (three-file model, why OS-level copy is unsafe, when to use the Python API)
- Backup procedure (live WAL-aware backup, verification, recommended cron schedule)
- Restore procedure (step-by-step, data-loss warning)
- Health check usage (`/health` JSON, diagnostics page)
- Rollback procedure (code rollback, additive-only schema note)
- Log locations (journald commands)
- Troubleshooting table (common symptoms → cause → resolution)

**`scripts/run_app.sh`** — bash wrapper around `uvicorn app.main:app`:
- Reads `IRONKEEP_HOST`, `IRONKEEP_PORT`, `IRONKEEP_LOG_LEVEL` with sensible defaults
- Uses `exec` for clean process replacement under systemd
- `set -euo pipefail` for safe error handling

**`scripts/run_scheduler.sh`** — bash wrapper around `python -m app.scheduler`:
- Exports `SCHEDULER_ENABLED=1` and `DISCORD_DISPATCH_ENABLED=1` by default (overridable)
- Uses `exec` for clean process replacement

**`scripts/backup_db.py`** — Python CLI wrapping `app.backup`:
- `--dest PATH` — explicit backup destination
- `--backup-dir DIR` — auto-named timestamped file in given directory
- `--prefix STR` — custom filename prefix (default: `ironkeep_backup`)
- `--verify` — runs `startup.check_core_tables` + `startup.check_integrity` on the completed backup
- Reads `IRONKEEP_DB_PATH` from environment (defaults to `ironkeep_v2.db`)
- Exits 0 on success, 1 on any error (with message to stderr)
- `main(argv=None)` is importable for testing

**`docs/systemd/ironkeep-app.service.example`** — systemd unit for the web process:
- `EnvironmentFile=` for secrets outside the repo
- `Restart=on-failure`, `RestartSec=5s`
- Security hardening: `NoNewPrivileges`, `ProtectSystem`, `ReadWritePaths`, `PrivateTmp`

**`docs/systemd/ironkeep-scheduler.service.example`** — systemd unit for the scheduler:
- Same security hardening as the web unit
- `TimeoutStopSec=60` for in-progress job completion

**Key decisions:**
- `scripts/backup_db.py` is a plain Python file (not a package) that inserts the project root into `sys.path` at the top — runnable standalone without installation.
- `--verify` calls `check_core_tables` + `check_integrity`, making it a self-contained post-backup health check useful in cron scripts.
- Shell scripts use `exec` so the process PID is the uvicorn/Python PID, not a bash wrapper — systemd `Type=simple` works correctly.
- Systemd units reference `EnvironmentFile=/etc/ironkeep/ironkeep.env` as the canonical secrets location (outside the repo, `chmod 600`).

**Tests:** `test_backup_script.py` (24 tests — 5 test groups covering resolve_destination, main() success, main() error paths, env var handling, and _build_parser argument parsing)

---

### 46. Launch Readiness Checklist + Pilot Guild Onboarding

**Type:** Docs

**Description:** Creates the operational materials needed to safely onboard the first real guild. No app-behavior changes. No new tests (no docs link-validation pattern exists).

**`docs/launch_checklist.md`** — 11-section pre-launch checklist:
1. Environment variables (all required vars with verification steps)
2. Process supervision (systemd enable check, restart-on-reboot)
3. Health endpoint (`/health` returns `"status": "ok"`, all fields verified)
4. Diagnostics page (reachable + WAL + scheduler healthy + zero error count)
5. Backup created and verified (`--verify` flag, off-path storage)
6. Restore rehearsal (non-production dry-run, `check_core_tables` + `check_integrity`)
7. Discord configuration tested (announcement channel, post/update roster, bot permissions)
8. OAuth login tested (end-to-end flow, role assignment, redirect URI check)
9. Reminder job tested (scheduler ran, no duplicate)
10. Ledger export tested (CSV columns present, signed amounts preserved)
11. Rollback plan known (git command, additive-only schema note, pre-restore copy step)
- Sign-off block: date, verifier, guild name, workspace slug

**`docs/pilot_onboarding.md`** — guild officer onboarding guide:
- Prerequisites (Discord server, bot, officer account, public URL, announcement channel)
- Discord permissions and OAuth2 scopes table
- First workspace setup (5 steps: login → create workspace → Discord settings → invite officers → create composition)
- First operation workflow (9 steps: create → attach composition → publish → signup → assign → post → update roster → mark attendance → complete)
- Readiness and reminder expectations (no live polling, reminder deduplication, no automatic gate)
- Payout ledger workflow (entry types, status lifecycle table, CSV export)
- Known limitations (alliance, bulk payout, role variants, mobile, email auth, audit export, public pages)
- Support and debug information to collect (10-item checklist with explicit "do not share" note)

**`docs/security_notes.md`** — security guidance:
- Secrets table (session secret, bot token, client secret, DB file, backup files)
- Where secrets go (`EnvironmentFile=`, `chmod 600`, no CLI args)
- Generating the session secret
- Private repository warning (accidental commit recovery: rotate → filter-repo → force-push → assume compromised)
- SQLite database security (filesystem permissions, no web-root placement, backup encryption guidance, WAL/SHM sensitivity)
- Discord token handling (what the token grants, rotation steps in Developer Portal)
- Do-not-commit file checklist (`.gitignore` patterns)
- Session security (cookie flags in production, no revocation, reset-secret = mass logout)
- Network exposure (reverse proxy for TLS, scheduler outbound-only, no DB port, `/health` unauthenticated by design)
- Out-of-scope items (TLS, DDoS, rate limiting, security audit log)

**`README.md`** (new) — project overview:
- Architecture summary (FastAPI + SQLite, Jinja2, two-process model)
- Quick start for development (no external dependencies)
- Documentation index table linking all five key docs
- Environment variables reference table
- Health check usage
- Running tests
- Scripts table
- Project structure tree
- License/private-repo note linking to security_notes.md

**Key decisions:**
- No tests added — there is no docs link-validation pattern in the test suite, and markdown linting is an external tooling concern.
- `README.md` is intentionally developer-facing, not marketing copy; quick-start section is the entry point for new contributors.
- Known limitations are documented explicitly rather than hidden — pilot users should know what to expect.

---

### 42. Payout Ledger Finalization Integrity

**Type:** Domain / UX

**Description:** Makes the `approved → paid` transition explicit, irreversible, and fully auditable. Adds `paid_at` and `paid_by_user_id` columns, a `mark_payout_ledger_entry_paid` use case, an officer/owner-gated POST route, a "Mark paid" button (approved-only), timeline event, and CSV export support for the new columns.

**Schema:** `paid_at TEXT NULL` and `paid_by_user_id TEXT NULL REFERENCES users(id)` added to `payout_ledger_entries` in `schema.sql` and via `_COLUMN_MIGRATIONS` in `database.py`.

**Domain:** `assert_payable(entry)` added to `app/domain/payout_ledger.py`. Only `approved` entries may transition to `paid`; `draft`, `voided`, and already-`paid` entries raise `ValidationError` with a clear message. Transition table in module docstring updated.

**Repository:** `mark_payout_ledger_entry_paid(db, entry_id, ws_id, paid_at, paid_by_user_id)` — sets `status='paid'`, `paid_at`, `paid_by_user_id`, and `updated_at` atomically. Returns rowcount.

**Event:** `PAYOUT_LEDGER_ENTRY_PAID = "payout_ledger.entry.paid"` added to `operational_events.py` and `_OPERATION_LEVEL_EVENTS`. Timeline label `"Ledger entry paid"` added to `_EVENT_LABELS`. Event payload includes `entry_type`, `amount_silver`, `participant_id`.

**Use case:** `mark_payout_ledger_entry_paid(guild_workspace_id, entry_id, actor_user_id)` — officer/owner-gated, calls `assert_payable`, delegates to repository, emits `PAYOUT_LEDGER_ENTRY_PAID` event.

**Route:** `POST /workspaces/{slug}/operations/{op_id}/ledger/{entry_id}/mark-paid` — PRG pattern, error-redirects on invalid transitions.

**Template:** "Mark paid" button with confirmation dialog renders only for `status == 'approved'`. Audit column shows ✓ `paid_at` + payer display_name in green for paid entries. `actor_ids` set in both ledger page and CSV export routes now includes `paid_by_user_id`.

**CSV:** `paid_at` and `paid_by` columns added to `_LEDGER_CSV_COLUMNS` (between `updated_at` and `voided_at`). `_entry_to_csv_row` populates them; empty string for non-paid entries.

**Key decisions:**
- `paid` is a terminal state — no re-void, re-approve, or edit allowed. Enforced in domain (`assert_voidable`, `validate_status_transition`, `assert_mutable`).
- `draft → paid` is forbidden by domain; must follow `draft → approved → paid`.
- Paid entries remain visible in all lists and exports (full audit trail).

**Tests:** `test_payout_ledger_finalization.py` (50 tests — domain `assert_payable` (4), repository (6), use case happy path (6), invalid transitions (3), RBAC (4), paid immutability (3), HTTP route (7), UI visibility (4), audit column (4), timeline (3), CSV (5), backward compat (1))

---

### 41. Payout Ledger Export v1

**Type:** UX / Data

**Description:** Adds a read-only `GET /workspaces/{slug}/operations/{op_id}/ledger/export.csv` endpoint that streams the full operation ledger as a UTF-8 CSV file. Officer/owner-gated. Workspace-scoped. Uses the existing `list_payout_ledger_entries_for_operation` and `get_users_by_ids` calls — no new repository logic. Voided entries are included (full audit trail). Signed adjustment amounts preserved. Creator and voider user IDs resolved to `display_name` via batch user lookup.

**Exported columns (stable):** `operation_id`, `participant_id`, `entry_type`, `status`, `amount_silver`, `note`, `created_by`, `created_at`, `updated_at`, `voided_at`, `voided_by`

**Behavior:**
- Empty operation → header-only CSV, 200 OK.
- `Content-Disposition: attachment; filename="ledger_<title>_<id[:8]>.csv"`.
- `Content-Type: text/csv; charset=utf-8`.
- Notes with commas, newlines, or double-quotes are RFC-4180-compliant (Python `csv.DictWriter` handles escaping).
- No secrets, payloads, or internal UUIDs exposed beyond `operation_id` and `participant_id` (already visible on the ledger page).
- No mutation side effects.

**No schema changes.** Purely additive route + helper.

**Major files:** `app/routes.py` (`_LEDGER_CSV_COLUMNS`, `_entry_to_csv_row`, `get_ledger_export_csv`), `app/templates/operation_ledger.html` ("Export CSV" link in Entries card header)

**Key decisions:**
- `StreamingResponse(iter([buf.getvalue()]))` keeps the route synchronous and avoids chunked encoding complexity for files that are always small (ledger entries per op).
- `_entry_to_csv_row` truncates unknown `user_id` to `[:8]` as a safe fallback if the user row is missing.
- Filename sanitisation replaces spaces with underscores and slashes with dashes, capped at 40 chars.

**Tests:** `test_payout_ledger_export.py` (27 tests — permission enforcement, content-type, content-disposition + filename, empty export, all-column populated export, value correctness, creator display_name, note field, empty note, negative adjustment, positive adjustment, voided entry included, voided_at present, voided_by display_name, workspace isolation, deterministic ordering, CSV escaping for comma/newline/double-quote, export link on ledger page)

---

### 40. Payout Ledger Audit + Timeline Hardening

**Type:** UX / Audit

**Description:** Strengthened auditability, timeline clarity, and immutable-state visibility for payout ledger activity. Four areas improved: timeline structured rendering, immutable-state UX, ledger totals centralisation, and audit column on the ledger page.

**Timeline:** Payout-group events (`payout_ledger.entry.*`) now render an inline structured summary (entry type · formatted silver amount · note) immediately above the raw-payload disclosure, via new `_parse_payout_event_detail` helper and extended `_enrich_timeline_events`. Event payloads for `PAYOUT_LEDGER_ENTRY_CREATED` now also include `note`.

**Ledger totals:** Two parallel paths added:
- `get_ledger_totals_for_operation(db, op_id, ws_id)` — single `GROUP BY status` SQL query; voided amounts excluded from `active_total` by design.
- `compute_ledger_totals(entries)` — pure-Python twin for use when entries already in memory. Both paths are tested to produce identical results for the same dataset.

**Ledger template:** Replaced inline Jinja arithmetic with `ledger_totals` context dict. Totals strip now shows active count + silver, per-status breakdowns (draft/approved/paid), and voided count with "(excluded from total)" note. New Audit column shows `created_at` + creator display_name, ✎ `updated_at` when different from `created_at`, ✕ `voided_at` + voider display_name in red. Negative adjustment amounts rendered in `var(--error)` red. Immutable UX: `paid` rows show "Paid — locked" badge + "Finalized — no further changes" hint; `voided` rows show "Voided — excluded from totals" hint; action buttons absent with visible reason.

**New repository function:** `get_users_by_ids(db, user_ids)` — batch user lookup by list of IDs.

**Major files:** `app/repositories.py` (`get_users_by_ids`, `get_ledger_totals_for_operation`), `app/routes.py` (`compute_ledger_totals`, `_parse_payout_event_detail`, extended `_enrich_timeline_events`, extended `get_operation_ledger`), `app/application/use_cases.py` (note added to CREATED event payload), `app/templates/operation_ledger.html` (rewritten), `app/templates/operation_timeline.html` (payout inline summary)

**Tests:** `test_payout_ledger_audit.py` (54 tests — `compute_ledger_totals` (9), `get_ledger_totals_for_operation` SQL (7), `_parse_payout_event_detail` (7), `_enrich_timeline_events` payout detail (4), timeline HTTP (5), audit column HTTP (4), immutable UX HTTP (5), totals strip HTTP (4), negative amount color (1), status badges (4), no mutation finalized HTTP (3), aggregation consistency (1))

---

### 39. Regear / Payout Tracking — Ledger Foundation

**Type:** Domain / Attendance

**Description:** Minimal data foundation for tracking regear/payout entries linked to operations and participants. Full lifecycle (draft → approved → paid → voided) with RBAC, immutability enforcement, workspace/operation scoping, and a minimal officer UI.

**Schema:** New `payout_ledger_entries` table with columns `id`, `guild_workspace_id`, `guild_operation_id`, `participant_id`, `entry_type` (`regear | payout | adjustment`), `amount_silver`, `note`, `status` (`draft | approved | paid | voided`), `created_by_user_id`, `created_at`, `updated_at`, `voided_at`, `voided_by_user_id`. `CHECK` constraints enforce valid `entry_type`/`status` enums and `amount_silver >= 0` for regear/payout (adjustment may be negative). Indexes on workspace, operation, and participant FKs.

**Domain module:** `app/domain/payout_ledger.py` — `VALID_ENTRY_TYPES`, `VALID_STATUSES`, `IMMUTABLE_STATUSES`, `_VALID_TRANSITIONS`, and validation functions `validate_entry_type`, `validate_amount`, `validate_status_transition`, `assert_mutable`, `assert_voidable`.

**Repository functions:** `insert_payout_ledger_entry`, `get_payout_ledger_entry`, `list_payout_ledger_entries_for_operation`, `list_payout_ledger_entries_for_participant`, `update_payout_ledger_entry_draft`, `approve_payout_ledger_entry`, `void_payout_ledger_entry`.

**Use cases (all officer/owner-gated):** `create_payout_ledger_entry`, `update_payout_ledger_entry`, `approve_payout_ledger_entry`, `void_payout_ledger_entry`. Each emits a corresponding `payout_ledger.entry.*` operational event.

**Routes:** `GET /workspaces/{slug}/operations/{op_id}/ledger` (officer/owner), `POST /ledger/create`, `POST /ledger/{entry_id}/approve`, `POST /ledger/{entry_id}/void`. Ledger tab added to `operation_tabs.html` (gated by `can_mutate`).

**Key decisions:**
- `paid` and `voided` are immutable — no edits, no re-void, no re-approve.
- `approved` entries can be voided but not updated (must draft-first).
- No `display_name`-based identity inference anywhere.
- No Discord posting, no automatic payout calculation.

**Tests:** `test_payout_ledger.py` (89 tests — schema constraints, domain validation, repository CRUD/list/update/approve/void, use cases RBAC/workspace isolation/immutability/invalid transitions, HTTP routes access/empty/populated/voided styling/action gating)

---

### 38. Dispatch Retry Queue Visibility

**Type:** Infra / UX

**Description:** Extended the existing Scheduler Admin page (`GET /workspaces/{slug}/settings/scheduler`) with a read-only **"Pending Discord Retries"** table section, inserted between the health banner and the Recent Runs table. Shows up to 50 `pending_retry` rows for the workspace, ordered by `next_attempt_at ASC` (soonest-due first), with `attempted_at ASC, id ASC` tiebreaks. The count badge already present on the page is preserved and unchanged.

**Table columns:** Event type · Retry count · Last attempt (UTC) · Next attempt (UTC) · Error (safely truncated at 120 chars)

**Behavior:**
- Clear empty-state message when no pending retries exist.
- Non-pending rows (`resolved`, `exhausted`) are never shown.
- Non-trivial `payload_json` is hidden behind a `<details>/<summary>` disclosure element, capped at 2 000 chars. Trivial `{}` payloads produce no disclosure.
- No POST route added — page remains strictly read-only. `POST` returns 405.
- Existing officer/owner permission gate preserved.

**Route helpers added (pure functions):**
- `_truncate_error(msg, max_len=120)` — returns `—` for None/empty, appends `…` when cut.
- `_enrich_dispatch_failure(row)` — adds `attempted_at_fmt`, `next_attempt_at_fmt`, `error_summary`, `payload_safe`.

**New repository function:** `list_pending_dispatch_failures_for_workspace(db, ws_id, limit=50)` — ordered, limit-capped, workspace-scoped. Existing `count_pending_dispatch_failures` unchanged.

**No schema changes.** All data comes from `discord_dispatch_failures` added in Slice 34.

**Major files:** `app/repositories.py` (`list_pending_dispatch_failures_for_workspace`), `app/routes.py` (`_truncate_error`, `_enrich_dispatch_failure`, extended `get_scheduler_status`), `app/templates/workspace_scheduler_status.html` (new section)

**Key decisions:**
- New repository function rather than repurposing `get_pending_discord_dispatch_failures` — cleaner ordering and explicit UI semantics.
- Empty `next_attempt_at` (legacy rows) sorts first — they are already due.
- `payload_safe` is `None` for `{}` or whitespace — no disclosure element rendered for trivially empty payloads.

**Tests:** `test_dispatch_retry_queue.py` (45 tests — repository ordering/scoping/limit/exclusions, `_truncate_error` unit tests, `_enrich_dispatch_failure` unit tests, HTTP page rendering, empty state, non-pending exclusion, error truncation, payload disclosure, null error, workspace scoping, permission enforcement (owner/officer/member/unauthenticated), no POST route)

---

### 37. Albion Online API Integration

**Type:** Infra / Identity

**Description:** Adds per-workspace Albion Online character identity claims. Workspace members submit a pending character claim (looked up via the Albion Online gameinfo API); officers and owners approve or reject it. Approved claims are visible on the members page and account page. A separate `albion_character_cache` table caches API responses. `participants.albion_player_id` is added as a write-dark bridge column for future use. No scheduler job; no planner/attendance changes; no alliance or killboard system.

**Identity separation invariants (non-negotiable):**
- `users / user_auth_identities` = authentication identity.
- `player_game_identities` = verified game character claims.
- `participants` = operational roster entities.
- These three systems are permanently independent. No automatic merges, no `display_name`-based inference, no planner/attendance logic traversing between them.

**RBAC rules:**
- Owners may approve any claim, including their own.
- Officers may approve any claim EXCEPT their own.
- Members, officers, and owners may submit pending claims.
- Officers and owners may reject any pending claim.

**Write-dark invariant for `participants.albion_player_id`:**
- Column exists purely as dormant infrastructure.
- No repository helper reads/writes it.
- No use case or route reads/writes it.
- No planner, attendance, assignment, payout, or reliability logic references it.
- All existing participant rows remain `NULL` for this column.

**Cache refresh invariant:**
- `refresh_albion_character_cache()` updates `albion_character_cache` only.
- NEVER mutates `verification_status`, `reviewed_at`, `reviewed_by`, or `review_note` on `player_game_identities`.

**Schema additions:**
- `player_game_identities` table: `(id, guild_workspace_id, user_id, game, albion_player_id, character_name, verification_status, claimed_at, reviewed_at, reviewed_by, review_note, created_at); UNIQUE (guild_workspace_id, user_id, game); UNIQUE INDEX (albion_player_id, guild_workspace_id); INDEX (guild_workspace_id, verification_status)`.
- `albion_character_cache` table: `(id, albion_player_id, character_name, guild_id, guild_name, kill_fame, death_fame, extra_json, fetched_at); UNIQUE (albion_player_id)`.
- `participants.albion_player_id TEXT NULL` column migration (no FK, no unique index, write-dark).

**Major files:** `app/schema.sql` (two new tables + indexes), `app/database.py` (`participants.albion_player_id` column migration), `app/albion/__init__.py` + `app/albion/rest_client.py` (pure HTTP client; `search_albion_characters`, `fetch_albion_character`; `AlbionApiError`; 1 req/s rate limiter; 5s timeout; no DB/Discord/domain imports), `app/domain/albion_identity.py` (`validate_albion_player_id`, `validate_albion_character_name`; no UUID-regex enforcement), `app/domain/operational_events.py` (`ALBION_IDENTITY_CLAIMED`, `ALBION_IDENTITY_APPROVED`, `ALBION_IDENTITY_REJECTED` — workspace-level, audit-only, not dispatchable), `app/repositories.py` (10 new functions for `player_game_identities` and `albion_character_cache`), `app/application/use_cases.py` (`claim_albion_character`, `approve_albion_character_claim`, `reject_albion_character_claim`, `refresh_albion_character_cache` — two-phase DB/API pattern), `app/routes.py` (updated `GET /account`; new `POST /account/albion/claim`, `POST /account/albion/refresh`, `POST /workspaces/{slug}/members/{user_id}/albion/approve`, `POST /workspaces/{slug}/members/{user_id}/albion/reject`; updated `GET /workspaces/{slug}/members`), `app/templates/account.html` (Albion section: per-workspace claim status, search form, claim buttons), `app/templates/workspace_members.html` (Albion column: character name + approve/reject actions for pending claims)

**Key decisions:**
- No UUID-format validation on `albion_player_id` — the Albion API is the authority on validity; we only reject empty or overly long values.
- Two-phase use case pattern for all API calls: DB conflict checks → API call outside transaction → DB write (claim + cache upsert + event).
- `participants.albion_player_id` uses `NULL` sentinel for write-dark status; no `0` or empty-string sentinel.
- `refresh_albion_character_cache` emits no operational event — it is a non-state-changing cache operation.
- No scheduler job — all identity operations are user-initiated.
- Claim replacement: pending/rejected claims are deleted before re-insertion, preserving the `UNIQUE (guild_workspace_id, user_id, game)` constraint. Another user's rejected claim for the same character is also cleared on new claim.
- Albion identity events are deliberately excluded from `DISPATCHABLE_EVENT_TYPES` — they must never trigger Discord outbox dispatch.
- Search is user-initiated GET (`/account?search_q=...`) — acceptable to call the API from a GET handler since it is explicit user action, not background activity.

**Tests:** `test_albion_identity.py` (96 tests — domain validation (no UUID enforcement), schema/migration/FK invariants, repository CRUD + uniqueness + batch-fetch, REST client search/fetch/error/module-boundary, claim use case (happy path, API failure, conflict, reclaim, duplicate, non-member), approve (RBAC matrix: owner self, officer self-blocked, officer→other, member blocked), reject, rejected-claim replace flow, refresh (cache-only, verification state preserved across all statuses, API failure), write-dark participant invariant (column never read by core logic, reliability, planner, display_name tests), display_name non-inference invariant, account page route (search, claim, refresh, unauthenticated), members page route (pending badge, approve, reject, RBAC, approved character display), module boundary (no sqlite3/discord/domain imports in rest_client))

---

## Test Coverage Summary

| Test file | Area |
|---|---|
| `test_auth_dev_login.py` | Dev login, session |
| `test_workspace_membership.py` | Role checks, access control |
| `test_add_workspace_member.py` | Member management |
| `test_guild_scoping.py` | Workspace isolation |
| `test_vertical_slice.py` | End-to-end operation lifecycle |
| `test_operation_lifecycle.py` | Status transitions |
| `test_operation_mutation_status_rules.py` | Status-gated mutations |
| `test_signup_status_rules.py` | Signup open/closed guards |
| `test_signup_source.py` | source='web'/'discord' |
| `test_assignment_lifecycle.py` | Assign, remove, quick-assign |
| `test_quick_assign.py` | Quick-assign + quick-fill |
| `test_reserve.py` | Reserve/bench management |
| `test_planner_sorting.py` | Slot ordering |
| `test_frozen_operation_slots.py` | Slot immutability rules |
| `test_readiness_v2.py` | Readiness snapshot calculation |
| `test_role_gap_readiness.py` | Role/build gap detection |
| `test_attendance.py` | Assignment attendance recording |
| `test_scout_attendance.py` | Scout/support check-in |
| `test_operational_events.py` | Event emission and structure |
| `test_event_dispatch.py` | Post-commit dispatch |
| `test_discord_schema.py` | Discord tables and columns |
| `test_discord_module_boundaries.py` | SDK isolation, import boundaries |
| `test_discord_config_ui.py` | Discord settings form |
| `test_discord_formatters.py` | Formatter payloads, components |
| `test_discord_identity.py` | Identity resolution |
| `test_discord_adapter.py` | Command adapter handlers |
| `test_discord_dispatcher.py` | Event → action routing |
| `test_discord_announcement_preview.py` | Preview rendering |
| `test_discord_post_announcement.py` | Announcement post action |
| `test_discord_post_roster.py` | Roster post action |
| `test_discord_component_checkin.py` | Button check-in interactions |
| `test_dashboard_archived_filter.py` | Archived operation dashboard filter |
| `test_attendance_bulk_mark.py` | Bulk mark present, unmarked row emphasis |
| `test_dashboard_readiness.py` | Dashboard readiness snapshot display |
| `test_workspace_member_removal.py` | Member removal, permission matrix |
| `test_composition_soft_delete.py` | Composition soft-delete lifecycle |
| `test_timeline_display.py` | Timeline human labels, badges, ordering |
| `test_planner_ergonomics.py` | Compact cards, quick assign, sticky strip |
| `test_lock_from_planner.py` | Lock Roster button on planner page |
| `test_production_hardening.py` | Env vars, session secret, WAL mode, dev banner |
| `test_signup_withdrawal.py` | Withdrawal permissions, status gates, repo filtering, HTTP |
| `test_op_status_coloring.py` | data-op-status on operation pages, non-operation pages clean |
| `test_dispatcher_execution.py` | Gates, readiness REST execution, scope boundary, settings UI |
| `test_discord_oauth.py` | OAuth flow, callback validation, dev-login guard, login page variants, `_safe_next` |
| `test_account_linking.py` | `link_discord_identity` use case, identity table backfill, orphan cleanup, conflict handling, HTTP linking flow |
| `test_discord_metadata_cache.py` | Metadata repository CRUD, REST client mocking, refresh failure isolation, refresh-on-save, RBAC, template name display |
| `test_player_reliability.py` | Reliability score calculation, threshold, window, workspace isolation, excused/withdrawn exclusion, template rendering (planner, attendance, members) |
| `test_scheduler_jobs.py` | Retry logic, gate behaviour, backoff, exhaustion, noop resolution, discord_messages upsert, metadata refresh, scheduler_run observability, crash detection |
| `test_scheduler_status.py` | Health banners, access control, run table badges/summary/details, stuck detection, pending failure count, pure helper unit tests |
| `test_operation_reminders.py` | Formatter purity, claim/finalize flow, stale claim recovery, eligible query filters, job happy-path, not-yet-due windows, already-done deduplication, REST failure resilience, workspace isolation, settings round-trip, boundary invariants |
| `test_albion_identity.py` | Domain validation, schema/migration/FK invariants, repository CRUD + uniqueness + batch-fetch, REST client mocking + module boundary, claim/approve/reject/refresh use cases, RBAC matrix, write-dark participant invariant, display_name non-inference, account + members page routes |
| `test_dispatch_retry_queue.py` | Repository ordering/scoping/limit/exclusions, `_truncate_error` unit tests, `_enrich_dispatch_failure` unit tests, HTTP page rendering, empty state, non-pending exclusion, error truncation, payload disclosure, null error, workspace scoping, permission enforcement, no POST route |
| `test_payout_ledger.py` | Schema constraints, domain validation, repository CRUD + list + update + approve + void, use cases (RBAC, workspace isolation, immutability, invalid transitions), HTTP GET ledger page (access, empty/populated, voided styling), HTTP POST create/void/approve |
| `test_payout_ledger_audit.py` | `compute_ledger_totals` pure helper, `get_ledger_totals_for_operation` SQL path, `_parse_payout_event_detail`, `_enrich_timeline_events` payout detail, timeline HTTP (entry type/amount/actor/label), ledger audit column (creator/voider/timestamps), immutable UX (paid-locked/voided hints/action gates), totals strip, negative amount color, status badges, no mutation on finalized, aggregation consistency |
| `test_payout_ledger_export.py` | Permission enforcement (unauth/member/officer/owner), content-type header, content-disposition + filename, empty export (200 + header-only), populated export (all columns, values, creator resolution, note), signed adjustments (negative/positive), voided entry included (status/voided_at/voided_by), workspace isolation, deterministic ordering, CSV escaping (comma/newline/double-quote), export link on ledger page |
| `test_payout_ledger_finalization.py` | `assert_payable` domain (approved/draft/voided/already-paid), repository `mark_payout_ledger_entry_paid` (status/paid_at/paid_by/updated_at/rowcount), use case happy path (transition/metadata/event/payload), invalid transitions (draft→paid/voided→paid/double-paid), RBAC (owner/officer/member/non-member), paid immutability (void/approve/update blocked), HTTP mark-paid route (owner/officer/member/unauth/draft/approved/already-paid), UI Mark paid visibility (approved/draft/paid/voided), audit column (paid_at/paid_by/checkmark), timeline rendering (label/amount/actor), CSV paid columns (header/paid values/empty non-paid/paid_by resolution/backward compat) |
| `test_operational_health.py` | `format_utc` (valid/None/empty/unparseable), `is_stale` (None/empty/recent/old/boundary), `scheduler_health` (never_run/ok/stale/stuck/last_seen_at), `db_health` (reachable/wal_mode), `check_db_writable` (writable/nonexistent parent), `check_core_tables` (present/missing), `startup.validate` (healthy/bad path), repository health queries (global pending count/error count/last run at), `/health` JSON endpoint (200/content-type/fields/status/no secrets/no auth), diagnostics page HTTP (owner/officer/member/unauth/db/scheduler/retries/errors/links), stale detection consistency (threshold constants/14min/16min), nav link visibility (owner/member) |

| `test_backup_restore.py` | `human_size` (zero/None/bytes/KB/MB/GB/large no-decimal), `backup_filename` (default prefix/custom/deterministic/format/no separators), `validate_backup_destination` (valid/nonexistent parent/is-dir/already-exists/string path), `create_backup` (file created/result keys/tables present/data present/source unchanged/source missing/valid SQLite/UTC created_at/size_human non-empty), `get_db_file_info` (existing/size/size_human/modified_at/display_name basename/no separators/nonexistent exists-false/size-none/modified-none/no WAL/WAL present/deeply nested), `check_integrity` (healthy DB/healthy with data/corrupt file/in-memory DB), diagnostics backup section (heading/recommendations/restore cautions/filename/size/WAL/member 403/officer 200/no absolute path), path sanitization (deeply nested/string type/nonexistent basename/Windows-style) |
| `test_backup_script.py` | `resolve_destination` (explicit dest/backup-dir/default source dir/custom prefix/dest overrides backup-dir), `main()` success (returns 0/file created/auto-named in backup-dir/--verify passes on good backup/custom prefix), `main()` errors (dest exists/source missing/dest dir missing/no crash on missing dir), env var handling (IRONKEEP_DB_PATH respected/nonexistent path returns 1), `_build_parser` (--dest/--backup-dir/--prefix/--verify default false/--verify true/no-args/all-combined) |

**Total: 1448 tests, 59 test files.** All pass.

---

## Explicitly Rejected / Out of Scope

### Discord as Operational Brain

**Rejected because:** In V1, the Discord bot owned the CTA signup flow, assignment confirmation, attendance marking, role assignment decisions, and lifecycle transitions. This made it impossible to use the web UI without the bot, created dual-write inconsistencies, and made the system impossible to debug when Discord was down or rate-limited. V2's architectural boundary explicitly inverts this: the web UI owns all state; Discord is a surface.

---

### Assignment Mutation from Discord

**Rejected because:** Allowing Discord buttons or slash commands to create or remove slot assignments would make Discord a co-owner of roster state. If Discord is down during a CTA, the roster must still be usable. Assignment authority belongs exclusively to the web planner, enforced through `use_cases.create_assignment` with full role checks.

---

### Stateful Bot Workflow Ownership

**Rejected because:** V1's bot used conversation state (multi-step DM flows for signup, confirmation sequences, reminder timers in bot memory). These patterns are fragile, restart-sensitive, and untestable. V2 interactions are stateless: each component interaction is a single round-trip to the adapter, which reads fresh DB state for every call.

---

### Auto-posting Announcements/Rosters on Lifecycle Events

**Rejected because:** Automatic announcement posting (e.g., "auto-announce when operation is published") creates a hidden side effect that officers cannot predict, suppress, or retry. Announcements and rosters remain explicit officer actions ("Post to Discord" / "Update Roster Post") only. Readiness summaries are the sole exception — they auto-post when the workspace `discord_auto_dispatch` flag and `DISCORD_DISPATCH_ENABLED` env var are both enabled, which requires deliberate officer opt-in.

---

### Discord-First Architecture

**Rejected because:** Designing features for Discord convenience first (Discord DMs as the primary notification channel, Discord roles as the authorization model, Discord threads as the operational record) would make the web UI a second-class citizen and recreate V1's dependency structure. The web UI is the command center. Discord is a projection of it.

---

### React / Next.js Rewrite

**Rejected because:** A frontend framework rewrite would add build tooling, a client-side state model, API contract maintenance, and a significantly larger surface area for bugs. Server-rendered Jinja2 with PRG is appropriate for this domain: operations are not real-time, state changes are infrequent, and the web app does not need sub-second UI updates.

---

### Tailwind Migration (While Using Custom CSS)

**Rejected because:** The current custom CSS variable system (`base.html`) provides global theming and component consistency without a build step. Migrating to Tailwind while keeping the same template structure would increase template verbosity, require a build pipeline, and provide no user-visible improvement. If Tailwind is ever adopted, it must replace the current CSS system entirely — not coexist with it.

---

### WebSocket / Real-Time Planner State

**Rejected because:** Real-time planner state (seeing another officer's assignments appear live) adds a persistent connection layer, conflict resolution logic, and operational complexity that is not warranted by the current scale. Officers coordinate by convention (one caller per operation), making optimistic concurrent editing unnecessary.

---

### External Message Queues (Celery, Redis, RabbitMQ)

**Rejected because:** The post-commit dispatch system is synchronous and best-effort by design. Adding an external queue would increase infrastructure complexity, add failure modes (queue unavailability), and require careful idempotency design across two systems. The `discord_dispatch_failures` table provides a durable retry log for when a queue is eventually needed.

---

### Outbox Pattern / Event Sourcing / CQRS

**Rejected because:** V2 is not an event-sourced system. `operational_events` is an append-only audit log, not a state-reconstruction mechanism. Introducing projections, event replay, or read-model derivation from events would add architectural complexity that is not justified by the current data scale or query requirements.

---

### Hidden Side-Effect Automation

**Rejected because:** Any action that the officer cannot see, predict, suppress, or retry creates operational risk during a live CTA. All outbound Discord messages are either explicit officer actions (announced with a button) or post-commit dispatch (logged in `discord_dispatch_failures` on failure). No silent automations.

---

## Architectural Invariants

These rules are non-negotiable. Any slice that violates them requires explicit architectural review.

**1. The database is the single source of truth.**
No operational state exists in Discord, bot memory, session variables, or derived caches. All queries go to SQLite. No read replicas, no denormalized caches.

**2. No state mutation before commit.**
Use cases write within a `database.transaction()` context manager. If any write in a transaction fails, the entire transaction rolls back. No partial writes, no compensating transactions.

**3. Post-commit dispatch is best-effort and never rolls back the domain transaction.**
`dispatch_event` is called after `db.commit()`. Any exception in the dispatch path is caught, logged to `discord_dispatch_failures`, and discarded. The domain transaction is already committed and is not affected.

**4. All writes are workspace-scoped.**
Every entity in the schema has `guild_workspace_id`. Every repository function that reads or writes operation-level data accepts and enforces `guild_workspace_id`. Cross-workspace data access is impossible by construction.

**5. Business logic lives in use cases.**
Routes are thin: parse request → call use case → redirect or render. No domain decisions in routes. No domain decisions in templates. No domain decisions in Discord adapters.

**6. Adapters are thin translators.**
`app/discord/adapter.py` handlers follow: resolve identity → call use case → format response. No business logic, no domain rules, no DB writes outside of use case calls.

**7. Formatters are pure functions.**
`app/discord/formatters.py` functions take plain dicts in, return plain dicts out. No database access, no side effects, no SDK imports. Calling a formatter twice with the same input returns equal outputs.

**8. Discord SDK is isolated to `bot/`.**
`app/` never imports `discord`. `bot/` is a separate process. Tests in `tests/` assert this isolation. `bot/requirements.txt` is separate from root `requirements.txt`.

**9. All Discord user interactions call the same use cases as the web UI.**
A Discord check-in calls `record_scout_attendance`. A Discord signup calls `submit_signup_intent`. No Discord-specific code paths for domain logic.

**10. Explicit officer actions for all outbound Discord messages.**
No Discord message is sent without an officer initiating it (clicking "Post to Discord" / "Update Roster Post") or without a logged dispatchable event triggering it. No silent posting.

**11. Two-phase DB transactions for network calls.**
Use cases that call external APIs (Discord REST) close the DB transaction before the network call, then open a new transaction to record the result. This prevents long-held DB locks during network I/O.

**12. OperationalEvents are append-only.**
Events are never updated or deleted. They are the immutable audit trail of all state-changing actions.

**13. PRG pattern for all POST routes.**
Every form submission POST ends with a redirect (success → `?success=`, failure → `?error=`). No template rendering directly from a POST handler.

**14. Server-side auth checks on every POST route.**
`can_mutate` in templates is presentation-only. All POST routes verify role before calling any use case. A hidden button is not a security control.

---

## Suggested Next Slices

Ranked by operational impact and implementation risk. Categories: [UX], [Planner], [Attendance], [Infra], [Discord], [Auth].

---

### 1. Regear / Payout Tracking [Attendance] [Domain]

**Why now:** Post-operation financial workflows (gear replacement cost, death records, contribution-weighted silver splits) are the natural follow-on to stable attendance recording. V1 had these; they were cut intentionally from V2 to reduce scope.

**Operational impact:** High for member trust and participation incentives.

**Implementation risk:** High. New domain models (death records, gear values, payout approval flows), new admin UI, and financial validation rules.

**Category:** [Attendance] [Domain]

---

### 2. Advanced Composition Tooling [Planner] [Domain]

**Why now:** The current slot system maps a single role+build to a slot. Real CTA compositions often have build variants per role ("DPS: Hallowfall or Hellion"). Expressing this requires richer slot template models and a configurator UI.

**Operational impact:** Medium. Mainly improves planner accuracy for flexible compositions.

**Implementation risk:** High. Schema evolution for `composition_slot_templates`, new domain validation, and UI redesign for the composition builder.

**Category:** [Planner] [Domain]
