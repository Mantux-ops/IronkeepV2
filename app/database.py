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
    # Payout ledger finalization — explicit paid timestamp and actor (Slice 42).
    "ALTER TABLE payout_ledger_entries ADD COLUMN paid_at         TEXT NULL",
    "ALTER TABLE payout_ledger_entries ADD COLUMN paid_by_user_id TEXT NULL",
]


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
    finally:
        conn.close()
