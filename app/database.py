"""
Database connection, transaction context manager, and schema initialisation.

The module-level _DB_PATH is configurable so tests can point at an isolated
temp file without touching production data.

Environment variables
---------------------
IRONKEEP_DB_PATH
    Absolute path to the SQLite database file.  If not set, defaults to
    "ironkeep_v2.db" relative to the process working directory.  Always
    use an absolute path in production to avoid cwd-dependent data loss.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from pathlib import Path

_DB_PATH: str = os.environ.get("IRONKEEP_DB_PATH", "ironkeep_v2.db")

_log = logging.getLogger(__name__)


def configure(path: str | None = None) -> None:
    """
    Override the database path.

    If *path* is provided, use it directly (the normal test path).
    If *path* is None, re-read IRONKEEP_DB_PATH from the environment
    (useful for testing the env-override behaviour).

    Call before init_schema().
    """
    global _DB_PATH
    _DB_PATH = path if path is not None else os.environ.get("IRONKEEP_DB_PATH", "ironkeep_v2.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class TransactionContext:
    """
    Thin wrapper around sqlite3.Connection that adds post-commit event dispatch.

    sqlite3.Connection is a C extension type that does not accept arbitrary
    attributes, so we cannot attach _pending_dispatch to it directly.

    pending_dispatch accumulates OperationalEvent dicts written during the
    transaction.  database.transaction() drains this list by calling
    app.events.dispatch_event for each entry after a successful commit.
    On rollback the list is discarded with the context object.

    All sqlite3.Connection attributes and methods (execute, commit, rollback,
    close, row_factory, etc.) are forwarded transparently via __getattr__.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.pending_dispatch: list[dict] = []

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


@contextlib.contextmanager
def transaction():
    """
    Open a connection wrapped in a TransactionContext, yield it, then commit
    on success or rollback on error.

    After a successful commit the connection is closed, then every event
    accumulated in ctx.pending_dispatch is dispatched through
    app.events.dispatch_event (best-effort, synchronous, never raises).

    Usage::

        with database.transaction() as db:
            repositories.insert_something(db, ...)
    """
    conn = get_connection()
    ctx = TransactionContext(conn)
    try:
        yield ctx
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Post-commit dispatch: only reached when no exception was raised.
    # conn is already closed; ctx.pending_dispatch is still in memory.
    # Deferred import avoids circular dependency (app.events imports app.database).
    from app import events as _app_events  # noqa: PLC0415

    for event in ctx.pending_dispatch:
        try:
            _app_events.dispatch_event(event)
        except Exception as exc:  # dispatch_event must not raise, but guard anyway
            _log.error("Unexpected error in post-commit dispatch loop: %s", exc)


# Incremental column additions for existing databases.
# Each ALTER TABLE is idempotent: silently skipped when the column already
# exists (SQLite raises OperationalError "duplicate column name" in that case).
# One-time data migrations — safe to run on every startup.
# Each is wrapped in INSERT OR IGNORE so re-runs are no-ops.
# Used for backfilling new tables from existing data (cannot be expressed as
# ALTER TABLE column additions).
_DATA_MIGRATIONS: list[str] = [
    # Backfill user_auth_identities from existing users rows.
    # After this runs every user has at least one identity row, which allows
    # get_user_by_provider_identity to resolve purely via the new table.
    # hex(randomblob(16)) produces a 32-char hex UUID-like PK that is
    # deterministic-enough for a one-time seed; real inserts use uuid.uuid4().
    """
    INSERT OR IGNORE INTO user_auth_identities
        (id, user_id, auth_provider, provider_user_id, created_at)
    SELECT
        lower(hex(randomblob(16))),
        id,
        auth_provider,
        provider_user_id,
        created_at
    FROM users
    """,
]

_COLUMN_MIGRATIONS: list[str] = [
    "ALTER TABLE readiness_snapshots ADD COLUMN attendance_marked_count   INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE readiness_snapshots ADD COLUMN attendance_unmarked_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE readiness_snapshots ADD COLUMN scout_count               INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE readiness_snapshots ADD COLUMN support_count             INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE readiness_snapshots ADD COLUMN reserve_count             INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE readiness_snapshots ADD COLUMN missing_builds_json       TEXT    NOT NULL DEFAULT '{}'",
    # Discord infrastructure foundation
    "ALTER TABLE guild_workspaces ADD COLUMN discord_guild_id                TEXT",
    "ALTER TABLE guild_workspaces ADD COLUMN discord_announcement_channel_id TEXT",
    "ALTER TABLE guild_workspaces ADD COLUMN discord_officer_channel_id      TEXT",
    "ALTER TABLE signup_intents   ADD COLUMN source TEXT NOT NULL DEFAULT 'web'",
    # Composition soft-delete
    "ALTER TABLE albion_compositions ADD COLUMN deleted_at TEXT NULL",
    # Signup withdrawal (soft-delete)
    "ALTER TABLE signup_intents ADD COLUMN withdrawn_at TEXT NULL",
    # Discord auto-dispatch flag (readiness summaries only)
    "ALTER TABLE guild_workspaces ADD COLUMN discord_auto_dispatch INTEGER NOT NULL DEFAULT 0",
    # Scheduler + dispatch retry foundation
    "ALTER TABLE discord_dispatch_failures ADD COLUMN payload_json    TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE discord_dispatch_failures ADD COLUMN next_attempt_at TEXT NOT NULL DEFAULT ''",
    # Reminder jobs opt-in (per-workspace; off by default)
    "ALTER TABLE guild_workspaces ADD COLUMN discord_reminders_enabled INTEGER NOT NULL DEFAULT 0",
    # Albion player ID bridge — dormant infrastructure for future officer-driven linking.
    # NOT used by planner, attendance, assignments, payouts, or reliability in this slice.
    "ALTER TABLE participants ADD COLUMN albion_player_id TEXT NULL",
    # Discord mention support: snowflake of the participant when created from a
    # Discord interaction.  Lets roster posts render <@id> (live server nickname).
    "ALTER TABLE participants ADD COLUMN discord_user_id TEXT NULL",
    # Payout ledger finalization — explicit paid timestamp and actor (Slice 42).
    "ALTER TABLE payout_ledger_entries ADD COLUMN paid_at         TEXT NULL",
    "ALTER TABLE payout_ledger_entries ADD COLUMN paid_by_user_id TEXT NULL",
    # Phase 3: inline build management — reusable doctrine entity FK on slot templates.
    "ALTER TABLE composition_slot_templates ADD COLUMN albion_build_id TEXT NULL REFERENCES albion_builds(id)",
    # Phase 10 Slice 1: Discord-first workspace bootstrap.
    # discord_provisioned_at: set when a workspace is created automatically via
    # on_guild_join.  NULL means manually created.  Used by setup-required UI.
    "ALTER TABLE guild_workspaces ADD COLUMN discord_provisioned_at TEXT NULL",
    # Phase 10 Slice 2: Setup completion and safe owner bootstrap.
    # discord_guild_owner_id: Discord snowflake of the guild owner at install time.
    # Used by complete_discord_workspace_setup to verify ownership claims.
    "ALTER TABLE discord_guild_installs ADD COLUMN discord_guild_owner_id TEXT NULL",
    # Phase 4: structured equipment doctrine — full loadout snapshot on slot templates and operation slots.
    "ALTER TABLE composition_slot_templates ADD COLUMN offhand_name TEXT NULL",
    "ALTER TABLE composition_slot_templates ADD COLUMN head_name    TEXT NULL",
    "ALTER TABLE composition_slot_templates ADD COLUMN armor_name   TEXT NULL",
    "ALTER TABLE composition_slot_templates ADD COLUMN shoes_name   TEXT NULL",
    "ALTER TABLE composition_slot_templates ADD COLUMN cape_name    TEXT NULL",
    "ALTER TABLE composition_slot_templates ADD COLUMN food_name    TEXT NULL",
    "ALTER TABLE composition_slot_templates ADD COLUMN potion_name  TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN offhand_name TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN head_name    TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN armor_name   TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN shoes_name   TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN cape_name    TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN food_name    TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN potion_name  TEXT NULL",
    # Tactical Doctrine Identity slice — battlefield role layer.
    "ALTER TABLE albion_builds ADD COLUMN doctrine_role TEXT NULL",
    "ALTER TABLE composition_slot_templates ADD COLUMN doctrine_role TEXT NULL",
    "ALTER TABLE operation_slots ADD COLUMN doctrine_role TEXT NULL",
    # Phase 11 Slice 3: stale marking for imported Albion guild roster players.
    # NULL = active; non-NULL = ISO timestamp when player was first marked stale.
    "ALTER TABLE workspace_albion_players ADD COLUMN stale_at TEXT NULL",
    # Phase 11 Slice 4: guild ownership / anti-stealing model.
    # All linked guilds default to 'unverified'.  Verified guilds require an
    # explicit future admin/officer approval step — not yet implemented.
    "ALTER TABLE workspace_albion_guilds ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unverified'",
    "ALTER TABLE workspace_albion_guilds ADD COLUMN verified_at TEXT NULL",
    "ALTER TABLE workspace_albion_guilds ADD COLUMN verified_by_user_id TEXT NULL REFERENCES users(id)",
    "ALTER TABLE workspace_albion_guilds ADD COLUMN verification_method TEXT NULL",
    # Phase 12.3: Versioned build system — new columns on albion_builds.
    # Legacy builds (created before Phase 12.3) get safe defaults; their flat
    # equipment fields (weapon_name, offhand_name, …) are preserved unchanged.
    # current_version_id is a logical FK to albion_build_versions.id; not
    # declared as a DB-level FK here to avoid migration ordering issues with
    # the circular reference — enforced at the application layer instead.
    "ALTER TABLE albion_builds ADD COLUMN description TEXT NULL",
    "ALTER TABLE albion_builds ADD COLUMN event_type TEXT NOT NULL DEFAULT 'other'",
    "ALTER TABLE albion_builds ADD COLUMN minimum_ip INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE albion_builds ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'",
    "ALTER TABLE albion_builds ADD COLUMN current_version_id TEXT NULL",
    "ALTER TABLE albion_builds ADD COLUMN created_by TEXT NULL",
    "ALTER TABLE albion_builds ADD COLUMN updated_by TEXT NULL",
    "ALTER TABLE albion_builds ADD COLUMN archived_at TEXT NULL",
    "ALTER TABLE albion_builds ADD COLUMN archived_by TEXT NULL",
    # Super-admin workspace soft-delete (god-mode portal).
    # NULL = active; ISO-8601 timestamp = soft-deleted (hidden from normal users).
    "ALTER TABLE guild_workspaces ADD COLUMN deleted_at TEXT NULL",
    "ALTER TABLE guild_workspaces ADD COLUMN deleted_by TEXT NULL REFERENCES users(id)",
]


def _migrate_workspace_albion_guilds_add_server(conn: sqlite3.Connection) -> None:
    """
    Add the *server* column to workspace_albion_guilds and update the UNIQUE
    constraint from (guild_workspace_id, albion_guild_id) to
    (guild_workspace_id, server, albion_guild_id).

    Idempotent: no-op if *server* column already exists (fresh DB created from
    the updated schema.sql already has the right schema).

    Migration strategy (SQLite cannot ALTER a UNIQUE constraint):
      1. Create workspace_albion_guilds_v2 with the new schema.
      2. Copy every existing row, backfilling server = 'europe'.
      3. DROP the old table.
      4. RENAME the new table.
      5. Recreate the workspace-scoped index.
    Foreign-key enforcement is disabled for the duration of the rename.
    """
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(workspace_albion_guilds)"
    ).fetchall()}
    if "server" in cols:
        return  # Already migrated — nothing to do.

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""
        CREATE TABLE workspace_albion_guilds_v2 (
            id                    TEXT PRIMARY KEY,
            guild_workspace_id    TEXT NOT NULL REFERENCES guild_workspaces(id),
            albion_guild_id       TEXT NOT NULL,
            guild_name            TEXT NOT NULL,
            server                TEXT NOT NULL DEFAULT 'europe',
            alliance_id           TEXT,
            alliance_name         TEXT,
            last_imported_at      TEXT,
            verification_status   TEXT NOT NULL DEFAULT 'unverified',
            verified_at           TEXT,
            verified_by_user_id   TEXT REFERENCES users(id),
            verification_method   TEXT,
            created_at            TEXT NOT NULL,
            UNIQUE(guild_workspace_id, server, albion_guild_id)
        )
    """)
    conn.execute("""
        INSERT INTO workspace_albion_guilds_v2
            (id, guild_workspace_id, albion_guild_id, guild_name, server,
             alliance_id, alliance_name, last_imported_at,
             verification_status, verified_at, verified_by_user_id,
             verification_method, created_at)
        SELECT
            id, guild_workspace_id, albion_guild_id, guild_name, 'europe',
            alliance_id, alliance_name, last_imported_at,
            COALESCE(verification_status, 'unverified'),
            verified_at, verified_by_user_id, verification_method,
            created_at
        FROM workspace_albion_guilds
    """)
    conn.execute("DROP TABLE workspace_albion_guilds")
    conn.execute(
        "ALTER TABLE workspace_albion_guilds_v2 "
        "RENAME TO workspace_albion_guilds"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_albion_guilds_workspace "
        "ON workspace_albion_guilds(guild_workspace_id)"
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def _migrate_albion_builds_rebuild(conn: sqlite3.Connection) -> None:
    """Rebuild ``albion_builds`` to add DB-level integrity for Phase 12.3b.

    Two improvements in one table rebuild (SQLite cannot add constraints via
    ALTER TABLE):

    1. ``weapon_name TEXT NULL``  — was NOT NULL; versioned builds store NULL
       here instead of the legacy sentinel ``""``.
    2. ``FOREIGN KEY (current_version_id) REFERENCES albion_build_versions(id)``
       — ensures current_version_id can only point at an existing version row.

    Idempotent: detects the already-migrated state by checking whether
    ``weapon_name`` allows NULL in ``PRAGMA table_info``.

    Safety:
    * Validates every V2 row's ``current_version_id`` before dropping the old
      table so corruption is caught before any data loss.
    * Runs with ``PRAGMA foreign_keys = OFF`` to allow the transient rename.
    * Calls ``PRAGMA foreign_key_check(albion_builds)`` after rename.
    * Rolls back on any error — the old table is never dropped until the new
      one is fully populated and validated.
    * Recreates the ``idx_albion_builds_workspace`` index.
    * The ``composition_slot_templates.albion_build_id → albion_builds.id`` FK
      is preserved because the table name is unchanged after the rename.
    """
    rows = conn.execute("PRAGMA table_info(albion_builds)").fetchall()
    if not rows:
        # Table does not exist yet (fresh DB will be created from schema.sql).
        _log.info("albion_builds does not exist yet — skipping rebuild.")
        return

    # Detect: notnull flag for weapon_name column (index 3 in PRAGMA result).
    weapon_col = next((r for r in rows if r[1] == "weapon_name"), None)
    if weapon_col is None:
        _log.warning("weapon_name column not found in albion_builds — skipping rebuild.")
        return
    if weapon_col[3] == 0:
        # notnull == 0  →  NULL already allowed  →  migration already applied.
        _log.debug("albion_builds rebuild already applied, skipping.")
        return

    # Check that current_version_id column exists (added by _COLUMN_MIGRATIONS).
    col_names = {r[1] for r in rows}
    if "current_version_id" not in col_names:
        _log.warning(
            "current_version_id column missing from albion_builds — "
            "column migrations may not have run yet.  Skipping rebuild."
        )
        return

    _log.info(
        "Rebuilding albion_builds: weapon_name → nullable, "
        "adding FOREIGN KEY on current_version_id."
    )

    # Pre-flight: validate V2 rows before dropping the old table.
    broken = conn.execute(
        """
        SELECT b.id FROM albion_builds b
        WHERE b.current_version_id IS NOT NULL
          AND b.current_version_id NOT IN (
              SELECT id FROM albion_build_versions
          )
        """
    ).fetchall()
    if broken:
        ids = ", ".join(r[0] for r in broken)
        raise RuntimeError(
            f"albion_builds rebuild aborted: rows have current_version_id "
            f"pointing at non-existent albion_build_versions rows: {ids}. "
            "Fix the data corruption before running the migration."
        )

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        # Build exact column list from current table so we never silently drop
        # columns added by future migrations.  We explicitly cast known columns
        # to their correct nullability in the new definition.
        conn.execute("""
            CREATE TABLE albion_builds_new (
                id                  TEXT PRIMARY KEY,
                guild_workspace_id  TEXT NOT NULL REFERENCES guild_workspaces(id),
                name                TEXT NOT NULL,
                role                TEXT NOT NULL,
                weapon_name         TEXT NULL,
                offhand_name        TEXT,
                head_name           TEXT,
                armor_name          TEXT,
                shoes_name          TEXT,
                cape_name           TEXT,
                food_name           TEXT,
                potion_name         TEXT,
                notes               TEXT,
                doctrine_role       TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                retired_at          TEXT,
                description         TEXT NULL,
                event_type          TEXT NOT NULL DEFAULT 'other',
                minimum_ip          INTEGER NOT NULL DEFAULT 0,
                status              TEXT NOT NULL DEFAULT 'draft',
                current_version_id  TEXT NULL
                    REFERENCES albion_build_versions(id),
                created_by          TEXT NULL,
                updated_by          TEXT NULL,
                archived_at         TEXT NULL,
                archived_by         TEXT NULL
            )
        """)
        conn.execute("""
            INSERT INTO albion_builds_new
                (id, guild_workspace_id, name, role, weapon_name,
                 offhand_name, head_name, armor_name, shoes_name,
                 cape_name, food_name, potion_name, notes, doctrine_role,
                 created_at, updated_at, retired_at,
                 description, event_type, minimum_ip, status,
                 current_version_id, created_by, updated_by,
                 archived_at, archived_by)
            SELECT
                 id, guild_workspace_id, name, role,
                 -- Migrate empty-string sentinel to NULL for versioned builds.
                 CASE WHEN current_version_id IS NOT NULL AND weapon_name = ''
                      THEN NULL ELSE weapon_name END,
                 offhand_name, head_name, armor_name, shoes_name,
                 cape_name, food_name, potion_name, notes, doctrine_role,
                 created_at, updated_at, retired_at,
                 description, event_type, minimum_ip, status,
                 current_version_id, created_by, updated_by,
                 archived_at, archived_by
            FROM albion_builds
        """)
        conn.execute("DROP TABLE albion_builds")
        conn.execute("ALTER TABLE albion_builds_new RENAME TO albion_builds")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_albion_builds_workspace "
            "ON albion_builds(guild_workspace_id, retired_at)"
        )
        violations = conn.execute("PRAGMA foreign_key_check(albion_builds)").fetchall()
        if violations:
            raise RuntimeError(
                f"albion_builds PRAGMA foreign_key_check found violations after "
                f"rebuild: {violations}"
            )
        conn.commit()
        _log.info("albion_builds rebuild complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


# ---------------------------------------------------------------------------
# Super-admin: permanent workspace deletion
# ---------------------------------------------------------------------------

#: Every table carrying a guild_workspace_id column.  Deleting a workspace
#: permanently removes all of its rows across these tables.  Kept in one place
#: so a new workspace-scoped table is a one-line addition here.
_WORKSPACE_CHILD_TABLES: tuple[str, ...] = (
    "player_game_identities",
    "discord_metadata_cache",
    "workspace_members",
    "guild_operations",
    "albion_compositions",
    "composition_slot_templates",
    "albion_builds",
    "operation_plans",
    "operation_slots",
    "participants",
    "signup_intents",
    "assignments",
    "readiness_snapshots",
    "operational_events",
    "scout_attendance_records",
    "attendance_records",
    "operation_reserves",
    "discord_guild_installs",
    "discord_messages",
    "discord_dispatch_failures",
    "operation_reminder_deliveries",
    "albion_build_versions",
    "albion_build_slot_items",
    "payout_ledger_entries",
    "workspace_albion_guilds",
    "workspace_albion_players",
)


def hard_delete_workspace(workspace_id: str) -> dict[str, int]:
    """Permanently delete a workspace and every row that belongs to it.

    This is a destructive super-admin operation.  Because the schema uses no
    ON DELETE CASCADE (and has a circular FK between albion_builds and
    albion_build_versions), the delete runs on a dedicated connection with
    ``PRAGMA foreign_keys = OFF`` inside a single transaction, mirroring the
    table-rebuild migrations.  After deletion ``PRAGMA foreign_key_check`` is
    run and any violation aborts the whole operation with a rollback.

    Returns a mapping of ``{table_name: rows_deleted}`` (including
    ``guild_workspaces``).

    Does NOT touch global/user tables (users, user_auth_identities, item
    catalog, scheduler_runs, superadmin_audit_log).
    """
    conn = sqlite3.connect(_DB_PATH)
    deleted: dict[str, int] = {}
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        for table in _WORKSPACE_CHILD_TABLES:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE guild_workspace_id = ?",
                (workspace_id,),
            )
            deleted[table] = cur.rowcount
        cur = conn.execute(
            "DELETE FROM guild_workspaces WHERE id = ?", (workspace_id,)
        )
        deleted["guild_workspaces"] = cur.rowcount

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"hard_delete_workspace aborted: foreign_key_check found "
                f"dangling references after delete: {violations}"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()
    return deleted


def init_schema() -> None:
    """
    Create all tables and indexes from schema.sql (idempotent).

    After the main schema:
    - Enable WAL journal mode for better read/write concurrency (persistent
      on the file; setting it repeatedly is a no-op).
    - Apply incremental column additions.  Each ALTER TABLE is wrapped in a
      try/except so it silently no-ops on databases that already have the
      column (new DBs get the columns via CREATE TABLE, so the ALTER would
      fail and be skipped).
    """
    schema_sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.executescript(schema_sql)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
        for stmt in _COLUMN_MIGRATIONS:
            try:
                conn.execute(stmt)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists — new DB created via CREATE TABLE
        for stmt in _DATA_MIGRATIONS:
            try:
                conn.execute(stmt)
                conn.commit()
            except sqlite3.OperationalError as exc:
                _log.warning("Data migration skipped (%s): %.120s", exc, stmt.strip())
        _migrate_workspace_albion_guilds_add_server(conn)
        _migrate_albion_builds_rebuild(conn)
    finally:
        conn.close()
