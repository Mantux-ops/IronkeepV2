"""
Operational health diagnostics — shared utilities.

This module is the single source of truth for:
  - Scheduler stale/stuck threshold constants
  - UTC timestamp formatting
  - Stale timestamp detection
  - Scheduler health state computation
  - DB reachability + WAL mode checks

These utilities are imported by routes.py (health endpoint, diagnostics page)
and may be imported by tests directly without starting the full app.

Design rules:
  - No FastAPI imports here.
  - No authentication logic here.
  - No template references here.
  - Pure Python + sqlite3 only.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Threshold constants (single source of truth)
# ---------------------------------------------------------------------------

#: Minutes of silence before the scheduler is considered stale (no recent run).
SCHEDULER_STALE_MINUTES: int = 15

#: Minutes a job must be in 'running' state with no finished_at before it is
#: considered stuck / crashed.
SCHEDULER_STUCK_MINUTES: int = 10


# ---------------------------------------------------------------------------
# UTC formatting
# ---------------------------------------------------------------------------

def format_utc(ts: str | None) -> str:
    """
    Format an ISO-8601 UTC timestamp for human-readable display.

    Returns '—' for None or unparseable values.
    Example: "2026-05-16 14:30 UTC"
    """
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return ts


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------

def is_stale(ts: str | None, threshold_minutes: int, now: datetime | None = None) -> bool:
    """
    Return True if ``ts`` is older than ``threshold_minutes`` ago.

    Returns True for None/empty (absent timestamp = always stale).
    ``now`` defaults to datetime.now(timezone.utc) when not supplied.
    """
    if not ts:
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=threshold_minutes)).isoformat()
    return ts < cutoff


# ---------------------------------------------------------------------------
# Scheduler health state
# ---------------------------------------------------------------------------

def scheduler_health(
    runs: list[dict],
    now: datetime | None = None,
) -> dict:
    """
    Compute overall scheduler health from the recent run list.

    Returns a dict::

        {
          "status":       "never_run" | "ok" | "stale" | "stuck",
          "message":      str,
          "last_seen_at": str | None,   # ISO-8601 of the most recent run
        }

    Priority: stuck > stale > ok.

    ``now`` defaults to datetime.now(timezone.utc).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    stale_cutoff = (now - timedelta(minutes=SCHEDULER_STALE_MINUTES)).isoformat()
    stuck_cutoff = (now - timedelta(minutes=SCHEDULER_STUCK_MINUTES)).isoformat()

    if not runs:
        return {
            "status":       "never_run",
            "message":      (
                "The scheduler has never run on this server. "
                "Start it with: SCHEDULER_ENABLED=1 python -m app.scheduler"
            ),
            "last_seen_at": None,
        }

    # Check for stuck jobs first (highest severity).
    stuck = [
        r for r in runs
        if r.get("status") == "running"
        and not r.get("finished_at")
        and (r.get("started_at") or "") < stuck_cutoff
    ]
    if stuck:
        s = stuck[0]
        return {
            "status":  "stuck",
            "message": (
                f"A job appears stuck or the scheduler crashed — "
                f"'{s['job_name']}' started at {format_utc(s.get('started_at'))} "
                f"and never finished."
            ),
            "last_seen_at": s.get("started_at"),
        }

    latest_at = runs[0].get("started_at") or ""
    if latest_at < stale_cutoff:
        return {
            "status":  "stale",
            "message": (
                f"Scheduler may be stopped — last activity was at "
                f"{format_utc(latest_at)}."
            ),
            "last_seen_at": latest_at or None,
        }

    return {
        "status":       "ok",
        "message":      f"Scheduler is active. Last run: {format_utc(latest_at)}.",
        "last_seen_at": latest_at or None,
    }


# ---------------------------------------------------------------------------
# DB health
# ---------------------------------------------------------------------------

def db_health(db: sqlite3.Connection) -> dict:
    """
    Return a minimal DB health dict::

        {"reachable": True,  "wal_mode": True}
        {"reachable": False, "wal_mode": False, "error": str}

    Performs a single lightweight PRAGMA query; never mutates state.
    """
    try:
        row = db.execute("PRAGMA journal_mode").fetchone()
        wal = (row[0].lower() == "wal") if row else False
        return {"reachable": True, "wal_mode": wal}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "wal_mode": False, "error": str(exc)}
