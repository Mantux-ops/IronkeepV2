-- IronkeepV2 schema — vertical slice 1
-- NOTE: operation_slots has NO status column.
--       A slot is "assigned" if an active assignments row exists for it.
--       A slot is "open" if no active assignments row exists for it.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Tenant root
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS guild_workspaces (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    primary_game TEXT NOT NULL DEFAULT 'albion',
    -- Discord integration (nullable until workspace owner links a Discord server)
    discord_guild_id                TEXT UNIQUE,
    discord_announcement_channel_id TEXT,
    discord_officer_channel_id      TEXT,
    -- 0 = auto-dispatch disabled (default); 1 = readiness summaries auto-post/edit
    discord_auto_dispatch           INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Users and workspace membership
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    auth_provider     TEXT NOT NULL,
    provider_user_id  TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (auth_provider, provider_user_id)
);

-- ---------------------------------------------------------------------------
-- Auth identities  (multiple login credentials per user account)
-- Allows one users record to have both a dev identity (local fallback) and
-- a Discord identity (production login) without mutating users.auth_provider.
-- UNIQUE(auth_provider, provider_user_id) — prevents identity claim conflicts.
-- UNIQUE(user_id, auth_provider)          — at most one credential per provider.
-- No updated_at: credentials are never mutated, only inserted or (future) deleted.
-- ---------------------------------------------------------------------------
-- ---------------------------------------------------------------------------
-- Discord metadata cache  (names for guild / channel snowflakes)
-- Populated by REST fetch on Discord settings save or manual refresh.
-- Never blocks domain transactions — failures are logged and ignored.
-- Stale rows are preserved: a stale name is better than no name.
-- ---------------------------------------------------------------------------
-- ---------------------------------------------------------------------------
-- Albion character cache  (global — not workspace-scoped)
-- Best-effort read-cache for Albion Online API responses.
-- Keyed by stable albion_player_id.  Stale rows are preserved: old guild
-- data is better than no data.  Never gates any domain decision.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS albion_character_cache (
    id               TEXT PRIMARY KEY,
    albion_player_id TEXT NOT NULL,
    character_name   TEXT NOT NULL,
    guild_id         TEXT,
    guild_name       TEXT,
    kill_fame        INTEGER,
    death_fame       INTEGER,
    -- Raw API response for forward compatibility
    extra_json       TEXT NOT NULL DEFAULT '{}',
    fetched_at       TEXT NOT NULL,    -- ISO-8601 UTC; drives staleness display
    UNIQUE (albion_player_id)
);

CREATE INDEX IF NOT EXISTS idx_albion_character_cache_player_id
    ON albion_character_cache(albion_player_id);

-- ---------------------------------------------------------------------------
-- Player game identities  (workspace-scoped verified game character claims)
-- Links a users.id to a stable Albion player ID within one workspace.
-- Verification flow: user submits a pending claim → officer/owner approves.
-- Identity separation invariant: this table is INDEPENDENT from participants.
-- No automatic merges, no display_name inference, no planner/attendance logic
-- traverses between this table and participants.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_game_identities (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    game                TEXT NOT NULL DEFAULT 'albion',
    albion_player_id    TEXT NOT NULL,
    character_name      TEXT NOT NULL,
    -- 'pending' | 'approved' | 'rejected'
    verification_status TEXT NOT NULL DEFAULT 'pending',
    claimed_at          TEXT NOT NULL,
    reviewed_at         TEXT,
    reviewed_by         TEXT REFERENCES users(id),
    review_note         TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (guild_workspace_id, user_id, game)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pgi_albion_id_workspace
    ON player_game_identities(albion_player_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_pgi_workspace_status
    ON player_game_identities(guild_workspace_id, verification_status);

CREATE INDEX IF NOT EXISTS idx_pgi_user
    ON player_game_identities(user_id);

CREATE TABLE IF NOT EXISTS discord_metadata_cache (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    entity_type         TEXT NOT NULL,    -- 'guild' | 'channel'
    discord_entity_id   TEXT NOT NULL,    -- the snowflake
    name                TEXT NOT NULL,
    -- 'guild'  → {"icon_hash": "abc123"} (for future icon rendering)
    -- 'channel'→ {"channel_type": 0}     (0=text, 5=announcement, etc.)
    extra_json          TEXT NOT NULL DEFAULT '{}',
    fetched_at          TEXT NOT NULL,    -- ISO-8601 UTC; drives staleness display
    UNIQUE (guild_workspace_id, entity_type, discord_entity_id)
);

CREATE TABLE IF NOT EXISTS user_auth_identities (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL REFERENCES users(id),
    auth_provider     TEXT NOT NULL,
    provider_user_id  TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    UNIQUE (auth_provider, provider_user_id),
    UNIQUE (user_id, auth_provider)
);

CREATE TABLE IF NOT EXISTS workspace_members (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    user_id             TEXT NOT NULL REFERENCES users(id),
    role                TEXT NOT NULL,  -- owner | officer | member
    created_at          TEXT NOT NULL,
    UNIQUE (guild_workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_user
    ON workspace_members(user_id);

CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace
    ON workspace_members(guild_workspace_id);

-- ---------------------------------------------------------------------------
-- Operations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS guild_operations (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    title               TEXT NOT NULL,
    operation_type      TEXT NOT NULL DEFAULT 'zvz',   -- zvz | ganking | roads | hellgate
    scheduled_start_at  TEXT NOT NULL,                  -- ISO-8601 UTC
    status              TEXT NOT NULL DEFAULT 'draft',  -- draft | planning | locked | completed | archived
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Albion compositions (workspace-level templates)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS albion_compositions (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    name                TEXT NOT NULL,
    description         TEXT,
    -- NULL = active; ISO-8601 timestamp = retired/soft-deleted
    deleted_at          TEXT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- Individual slot templates inside a composition.
-- These are MUTABLE — they can be edited without affecting already-generated
-- operation slots (which are a frozen snapshot at generation time).
CREATE TABLE IF NOT EXISTS composition_slot_templates (
    id                      TEXT PRIMARY KEY,
    guild_workspace_id      TEXT NOT NULL REFERENCES guild_workspaces(id),
    albion_composition_id   TEXT NOT NULL REFERENCES albion_compositions(id),
    party_number            INTEGER NOT NULL,  -- 1-based party index
    slot_index              INTEGER NOT NULL,  -- 1-based slot within party
    role                    TEXT NOT NULL,
    build_name              TEXT NOT NULL,
    weapon_name             TEXT,
    priority                TEXT NOT NULL DEFAULT 'normal',  -- core | normal
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    UNIQUE (guild_workspace_id, albion_composition_id, party_number, slot_index)
);

-- ---------------------------------------------------------------------------
-- Operation plan  (attaches a composition to an operation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operation_plans (
    id                      TEXT PRIMARY KEY,
    guild_workspace_id      TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id      TEXT NOT NULL UNIQUE REFERENCES guild_operations(id),
    albion_composition_id   TEXT NOT NULL REFERENCES albion_compositions(id),
    signup_status           TEXT NOT NULL DEFAULT 'open',  -- open | closed
    max_participants        INTEGER,
    notes                   TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Operation slots  (frozen snapshot — copied from composition at plan time)
-- NO status column.  Assignment state is derived from the assignments table.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operation_slots (
    id                                  TEXT PRIMARY KEY,
    guild_workspace_id                  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id                  TEXT NOT NULL REFERENCES guild_operations(id),
    -- nullable: tracks which template this was cloned from (audit only)
    source_composition_slot_template_id TEXT,
    party_number                        INTEGER NOT NULL,
    slot_index                          INTEGER NOT NULL,
    role                                TEXT NOT NULL,
    build_name                          TEXT NOT NULL,
    weapon_name                         TEXT,
    priority                            TEXT NOT NULL DEFAULT 'normal',
    created_at                          TEXT NOT NULL,
    UNIQUE (guild_workspace_id, guild_operation_id, party_number, slot_index)
);

-- ---------------------------------------------------------------------------
-- Participants  (guild-scoped members who sign up or get assigned)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS participants (
    id                      TEXT PRIMARY KEY,
    guild_workspace_id      TEXT NOT NULL REFERENCES guild_workspaces(id),
    display_name            TEXT NOT NULL,
    albion_character_name   TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    UNIQUE (guild_workspace_id, display_name)
);

-- ---------------------------------------------------------------------------
-- Signup intents  (a participant declares intent to attend an operation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signup_intents (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    participant_id      TEXT NOT NULL REFERENCES participants(id),
    preferred_role      TEXT NOT NULL,
    preferred_build_name TEXT,
    -- specific = wants exact role/build | flexible = any role | fill = whatever is needed
    willingness         TEXT NOT NULL DEFAULT 'specific',
    -- confirmed | tentative | absent
    availability        TEXT NOT NULL DEFAULT 'confirmed',
    -- 'web' | 'discord' — tracks which surface submitted the signup (audit only)
    source              TEXT NOT NULL DEFAULT 'web',
    -- NULL = active; ISO-8601 timestamp = withdrawn (soft-delete)
    withdrawn_at        TEXT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (guild_workspace_id, guild_operation_id, participant_id)
);

-- ---------------------------------------------------------------------------
-- Assignments  (a participant is assigned to an operation slot)
-- Assignment state ("assigned" | "removed") owns whether a slot is filled.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignments (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    operation_slot_id   TEXT NOT NULL REFERENCES operation_slots(id),
    participant_id      TEXT NOT NULL REFERENCES participants(id),
    assigned_role       TEXT NOT NULL,
    assigned_build_name TEXT NOT NULL,
    -- assigned | removed  (soft-delete so history is kept)
    status              TEXT NOT NULL DEFAULT 'assigned',
    assigned_at         TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Readiness snapshots  (point-in-time readiness summary, append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readiness_snapshots (
    id                        TEXT PRIMARY KEY,
    guild_workspace_id        TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id        TEXT NOT NULL REFERENCES guild_operations(id),
    total_slots               INTEGER NOT NULL,
    assigned_slots            INTEGER NOT NULL,
    open_slots                INTEGER NOT NULL,
    unassigned_signup_count   INTEGER NOT NULL,
    -- Dict of role → open-slot count, e.g. {"DPS": 2, "Tank": 1}
    missing_roles_json        TEXT    NOT NULL DEFAULT '{}',
    -- Dict of build_name → open-slot count, e.g. {"Bow": 1, "Daggers": 1}
    missing_builds_json       TEXT    NOT NULL DEFAULT '{}',
    -- Attendance awareness (assignment-based only)
    attendance_marked_count   INTEGER NOT NULL DEFAULT 0,
    attendance_unmarked_count INTEGER NOT NULL DEFAULT 0,
    -- Scout / support participation (not assignment-based)
    scout_count               INTEGER NOT NULL DEFAULT 0,
    support_count             INTEGER NOT NULL DEFAULT 0,
    -- Reserves (bench players marked for possible insertion)
    reserve_count             INTEGER NOT NULL DEFAULT 0,
    -- ready | forming | not_ready
    readiness_state           TEXT NOT NULL,
    created_at                TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Operational events  (immutable audit log — one row per state-change command)
-- guild_operation_id is nullable for workspace-level events (e.g. comp created)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operational_events (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT,  -- NULL for workspace-level events
    event_type          TEXT NOT NULL,
    actor_type          TEXT NOT NULL DEFAULT 'system',  -- system | user | bot
    actor_id            TEXT,
    entity_type         TEXT NOT NULL,
    entity_id           TEXT NOT NULL,
    payload_json        TEXT NOT NULL DEFAULT '{}',
    occurred_at         TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Scout / support attendance  (NOT linked to assignments)
-- Any participant can check in as scout or support for an operation.
-- One row per participant per operation; re-checking-in is an upsert.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scout_attendance_records (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    participant_id      TEXT NOT NULL REFERENCES participants(id),
    -- 'scout' | 'support'
    role_type           TEXT NOT NULL,
    notes               TEXT,
    recorded_at         TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (guild_workspace_id, guild_operation_id, participant_id)
);

-- ---------------------------------------------------------------------------
-- Attendance records  (one row per assignment per operation, upsert on re-mark)
-- Tied to assignment_id so we know the exact role/build the participant was
-- expected to fill.  Unassigned signers cannot have attendance records.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance_records (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    assignment_id       TEXT NOT NULL REFERENCES assignments(id),
    participant_id      TEXT NOT NULL REFERENCES participants(id),
    -- present | late | absent | no_show | excused
    status              TEXT NOT NULL,
    notes               TEXT,
    recorded_at         TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (guild_workspace_id, guild_operation_id, assignment_id)
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_guild_operations_workspace
    ON guild_operations(guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_albion_compositions_workspace
    ON albion_compositions(guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_composition_slot_templates_composition
    ON composition_slot_templates(albion_composition_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_operation_plans_operation
    ON operation_plans(guild_operation_id);

CREATE INDEX IF NOT EXISTS idx_operation_slots_operation
    ON operation_slots(guild_operation_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_participants_workspace
    ON participants(guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_signup_intents_operation
    ON signup_intents(guild_operation_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_assignments_operation
    ON assignments(guild_operation_id, guild_workspace_id);

-- Critical: queried on every readiness calculation and slot assignment check
CREATE INDEX IF NOT EXISTS idx_assignments_slot_status
    ON assignments(operation_slot_id, status);

-- Partial unique index: at most one active assignment per participant per operation.
-- Rows with status='removed' are excluded so historical rows never conflict.
CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_one_active_per_participant
    ON assignments(guild_workspace_id, guild_operation_id, participant_id)
    WHERE status = 'assigned';

CREATE INDEX IF NOT EXISTS idx_readiness_snapshots_operation
    ON readiness_snapshots(guild_operation_id, guild_workspace_id, created_at);

CREATE INDEX IF NOT EXISTS idx_operational_events_workspace
    ON operational_events(guild_workspace_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_operational_events_operation
    ON operational_events(guild_operation_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_attendance_records_operation
    ON attendance_records(guild_operation_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_attendance_records_participant
    ON attendance_records(participant_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_scout_attendance_operation
    ON scout_attendance_records(guild_operation_id, guild_workspace_id);

-- ---------------------------------------------------------------------------
-- Operation reserves  (bench/reserve state for signed-up, unassigned players)
-- One row per participant per operation.  No status column: a row means
-- the participant is currently on reserve; deleting the row ends reserve.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operation_reserves (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    participant_id      TEXT NOT NULL REFERENCES participants(id),
    notes               TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (guild_workspace_id, guild_operation_id, participant_id)
);

CREATE INDEX IF NOT EXISTS idx_operation_reserves_operation
    ON operation_reserves(guild_operation_id, guild_workspace_id);

-- ---------------------------------------------------------------------------
-- Discord integration tables
-- discord_messages: durable store of posted Discord message IDs so the bot
--   can edit or delete messages without relying on in-process state.
--   Operation-level only in this slice; workspace-level messages are future.
-- discord_dispatch_failures: retry tracking for failed outbound Discord calls.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discord_messages (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    -- 'announcement' | 'roster' | 'readiness'
    message_type        TEXT NOT NULL,
    discord_channel_id  TEXT NOT NULL,
    discord_message_id  TEXT NOT NULL,
    discord_guild_id    TEXT NOT NULL,
    posted_at           TEXT NOT NULL,
    last_edited_at      TEXT,
    is_deleted          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (guild_workspace_id, guild_operation_id, message_type)
);

CREATE INDEX IF NOT EXISTS idx_discord_messages_workspace
    ON discord_messages(guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_discord_messages_operation
    ON discord_messages(guild_operation_id, guild_workspace_id);

CREATE TABLE IF NOT EXISTS discord_dispatch_failures (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    -- nullable: some failures may be workspace-level (no operation context)
    guild_operation_id  TEXT REFERENCES guild_operations(id),
    event_type          TEXT NOT NULL,
    entity_id           TEXT,
    error_code          INTEGER,
    error_message       TEXT,
    attempted_at        TEXT NOT NULL,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    -- 'pending_retry' | 'failed' | 'resolved'
    status              TEXT NOT NULL DEFAULT 'pending_retry'
);

CREATE INDEX IF NOT EXISTS idx_discord_dispatch_failures_workspace
    ON discord_dispatch_failures(guild_workspace_id, status);

-- ---------------------------------------------------------------------------
-- Operation reminder deliveries  (deduplication + state tracking for the
-- send_operation_reminders scheduler job)
--
-- One row per (operation, reminder_window).  The UNIQUE constraint ensures a
-- reminder is never delivered twice even across scheduler restarts.
--
-- Claim/finalize flow (retry-safe):
--   1. INSERT OR IGNORE to ensure the row exists (no-op if already present).
--   2. UPDATE status='claimed' WHERE status='pending'
--         OR (status='claimed' AND claimed_at <= <stale_cutoff>)
--      Returns rowcount=1 when the claim succeeds; 0 means busy or done.
--   3. REST call (outside any DB transaction).
--   4. UPDATE status='sent'  (success) or leave 'claimed' (REST failure,
--      retried on next run after the stale-claim timeout expires).
--   5. Skipped rows (status='skipped') are never retried.
--
-- Invariants (enforced in jobs.py):
--   - Reminders NEVER fire at/after scheduled_start_at.
--   - Retries only fire while still within the reminder grace window.
--   - Status 'skipped' is mandatory when the window closes without sending.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operation_reminder_deliveries (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    -- 'T-2h' | 'T-30m'
    reminder_window     TEXT NOT NULL,
    -- 'pending' | 'claimed' | 'sent' | 'skipped'
    status              TEXT NOT NULL DEFAULT 'pending',
    claimed_at          TEXT,   -- ISO-8601 UTC; set when status='claimed'
    sent_at             TEXT,   -- ISO-8601 UTC; set when status='sent'
    skipped_at          TEXT,   -- ISO-8601 UTC; set when status='skipped'
    skip_reason         TEXT,   -- human-readable reason for skipping
    created_at          TEXT NOT NULL,
    UNIQUE (guild_operation_id, reminder_window)
);

CREATE INDEX IF NOT EXISTS idx_reminder_deliveries_operation
    ON operation_reminder_deliveries(guild_operation_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_reminder_deliveries_status
    ON operation_reminder_deliveries(status, guild_workspace_id);

-- ---------------------------------------------------------------------------
-- Payout ledger entries  (regear/payout/adjustment tracking per operation)
--
-- Each entry is linked to a workspace + operation + participant.
-- Status lifecycle: draft → approved → paid.  Any non-paid row can be voided.
--
-- amount_silver constraints:
--   regear / payout  → must be >= 0 (a debt owed to or by the guild)
--   adjustment       → may be any integer (negative to reduce a payout balance)
--
-- Identity: participant_id (not user_id) follows the same pattern used by
--   assignments and attendance_records.  No display_name-based identity logic.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payout_ledger_entries (
    id                  TEXT PRIMARY KEY,
    guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
    guild_operation_id  TEXT NOT NULL REFERENCES guild_operations(id),
    participant_id      TEXT NOT NULL REFERENCES participants(id),
    -- 'regear' | 'payout' | 'adjustment'
    entry_type          TEXT NOT NULL
                        CHECK(entry_type IN ('regear', 'payout', 'adjustment')),
    -- silver amount; regear/payout must be >= 0; adjustments may be negative
    amount_silver       INTEGER NOT NULL DEFAULT 0
                        CHECK(entry_type = 'adjustment' OR amount_silver >= 0),
    note                TEXT,
    -- 'draft' | 'approved' | 'paid' | 'voided'
    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK(status IN ('draft', 'approved', 'paid', 'voided')),
    created_by_user_id  TEXT NOT NULL REFERENCES users(id),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    voided_at           TEXT NULL,
    voided_by_user_id   TEXT NULL REFERENCES users(id),
    paid_at             TEXT NULL,
    paid_by_user_id     TEXT NULL REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_payout_ledger_workspace
    ON payout_ledger_entries(guild_workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_payout_ledger_operation
    ON payout_ledger_entries(guild_operation_id, guild_workspace_id);

CREATE INDEX IF NOT EXISTS idx_payout_ledger_participant
    ON payout_ledger_entries(participant_id, guild_workspace_id);

-- ---------------------------------------------------------------------------
-- Scheduler runs  (observability log — one row per job execution)
-- A row with finished_at IS NULL and status='running' indicates a crash.
-- Rows are never deleted automatically.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scheduler_runs (
    id            TEXT PRIMARY KEY,
    job_name      TEXT NOT NULL,
    started_at    TEXT NOT NULL,   -- ISO-8601 UTC
    finished_at   TEXT,            -- NULL while running / on crash
    -- 'running' | 'success' | 'error'
    status        TEXT NOT NULL,
    result_json   TEXT NOT NULL DEFAULT '{}',
    error_message TEXT
);
