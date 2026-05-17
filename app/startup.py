"""
Startup validation for IronkeepV2.

Called from the FastAPI lifespan hook after database.init_schema() completes.
Validates that the runtime environment is sane before the app accepts traffic.

Rules:
  - Fatal errors raise RuntimeError (app will refuse to start).
  - Warnings are returned as a list of strings and logged by the caller.
  - No network calls in startup validation.
  - No business logic here — infrastructure checks only.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

_log = logging.getLogger(__name__)

# Core tables that must exist after init_schema().
_REQUIRED_TABLES = {
    "users",
    "guild_workspaces",
    "workspace_members",
    "scheduler_runs",
    "discord_dispatch_failures",
    "payout_ledger_entries",
}


def check_db_writable(db_path: str) -> None:
    """
    Raise RuntimeError if the database file path is not writable.

    Checks:
      1. Parent directory exists and is writable.
      2. If the file already exists, it is writable.
      3. If the file does not exist, the parent directory allows creation.

    Does not create the file.
    """
    p = Path(db_path)
    parent = p.parent

    if not parent.exists():
        raise RuntimeError(
            f"Database directory does not exist: {parent}\n"
            "Create it before starting the application."
        )
    if not os.access(parent, os.W_OK):
        raise RuntimeError(
            f"Database directory is not writable: {parent}"
        )
    if p.exists() and not os.access(p, os.W_OK):
        raise RuntimeError(
            f"Database file exists but is not writable: {p}"
        )


def check_core_tables(db: sqlite3.Connection) -> None:
    """
    Raise RuntimeError if any required core tables are missing.

    This catches cases where init_schema() failed silently or the DB file
    was replaced with a pre-migration backup.
    """
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    present = {r[0] for r in rows}
    missing = _REQUIRED_TABLES - present
    if missing:
        raise RuntimeError(
            f"Database schema is incomplete — missing tables: "
            f"{', '.join(sorted(missing))}.\n"
            "Run database.init_schema() to apply migrations."
        )


def check_integrity(db: sqlite3.Connection) -> None:
    """
    Run ``PRAGMA integrity_check(1)`` on the database connection.

    Raises RuntimeError if the first integrity issue found is not ``"ok"``.
    Uses a limit of 1 so the check terminates quickly on large corrupted DBs.
    Pass-through for healthy databases is essentially instant.

    Suitable for use after a restore to verify the restored file is intact.
    """
    rows = db.execute("PRAGMA integrity_check(1)").fetchall()
    if not rows or rows[0][0] != "ok":
        first = rows[0][0] if rows else "(no output)"
        raise RuntimeError(
            f"Database integrity check failed: {first}\n"
            "The database may be corrupted. Restore from a known-good backup."
        )


def validate(db_path: str, is_production: bool) -> list[str]:
    """
    Perform all startup validation checks.

    Returns a (possibly empty) list of warning strings for the caller to log.
    Raises RuntimeError on any fatal condition.

    Parameters
    ----------
    db_path:
        Absolute path to the SQLite database file (from IRONKEEP_DB_PATH).
    is_production:
        True when IRONKEEP_ENV=production.  Enables stricter checks.
    """
    warnings: list[str] = []

    # --- DB path writability ---
    check_db_writable(db_path)

    # --- Core table presence (after init_schema ran) ---
    try:
        conn = sqlite3.connect(db_path)
        try:
            check_core_tables(conn)
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(f"Startup schema check failed: {exc}") from exc

    # --- Environment variable warnings ---
    _optional_vars = {
        "DISCORD_BOT_TOKEN":         "Discord bot posting will fail at runtime.",
        "WEB_BASE_URL":              "Discord embed signup links will be omitted.",
        "DISCORD_CLIENT_ID":         "Discord OAuth login will be unavailable.",
        "DISCORD_CLIENT_SECRET":     "Discord OAuth login will be unavailable.",
        "DISCORD_OAUTH_REDIRECT_URI":"Discord OAuth login will be unavailable.",
    }
    for var, consequence in _optional_vars.items():
        if not os.getenv(var, "").strip():
            warnings.append(f"{var} is not set — {consequence}")

    if is_production:
        if not os.getenv("DISCORD_BOT_TOKEN", "").strip():
            warnings.append(
                "Running in production without DISCORD_BOT_TOKEN — "
                "all Discord posting will fail."
            )

    return warnings
