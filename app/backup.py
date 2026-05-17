"""
SQLite backup and restore utilities for IronkeepV2.

Design rules:
  - No shelling out to the sqlite3 CLI.  All backup/restore logic uses the
    Python sqlite3 C API's Connection.backup() which handles WAL checkpointing
    correctly and produces a consistent snapshot.
  - No cloud / S3 / remote storage.
  - No destructive restore operations — this module only *validates* and
    *creates* backups; actual restore is a manual operator step.
  - No scheduled backup logic here — this is a library, not a job.
  - No FastAPI / template imports.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Human-readable sizes
# ---------------------------------------------------------------------------

_SIZE_UNITS = [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10), ("B", 1)]


def human_size(size_bytes: int | None) -> str:
    """
    Convert a byte count to a compact human-readable string.

    Examples:
      0           → "0 B"
      1500        → "1.5 KB"
      15_728_640  → "15.0 MB"
    Returns "—" for None.
    """
    if size_bytes is None:
        return "—"
    if size_bytes == 0:
        return "0 B"
    for unit, threshold in _SIZE_UNITS:
        if size_bytes >= threshold:
            if unit == "B":
                return f"{size_bytes} B"
            value = size_bytes / threshold
            if value >= 10:
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
    return f"{size_bytes} B"


# ---------------------------------------------------------------------------
# Backup filename generation
# ---------------------------------------------------------------------------

def backup_filename(
    prefix: str = "ironkeep_backup",
    now: datetime | None = None,
) -> str:
    """
    Generate a timestamped backup filename.

    Format: ``{prefix}_YYYYMMDD_HHMMSS.db``
    UTC time is always used to avoid ambiguity across DST boundaries.

    Examples:
      backup_filename()                  → "ironkeep_backup_20260516_220100.db"
      backup_filename(prefix="restore")  → "restore_20260516_220100.db"
    """
    if now is None:
        now = datetime.now(timezone.utc)
    return f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}.db"


# ---------------------------------------------------------------------------
# Backup destination validation
# ---------------------------------------------------------------------------

def validate_backup_destination(dest_path: str | Path) -> None:
    """
    Validate that ``dest_path`` is a safe target for a backup write.

    Raises RuntimeError if any of the following is true:
      - Destination is an existing directory.
      - Parent directory does not exist.
      - Parent directory is not writable.
      - Destination already exists (prevents silent overwrites).

    Does not create the file.
    """
    p = Path(dest_path)

    if p.is_dir():
        raise RuntimeError(
            f"Backup destination is a directory, not a file: {p}"
        )
    if not p.parent.exists():
        raise RuntimeError(
            f"Backup destination directory does not exist: {p.parent}"
        )
    if not os.access(p.parent, os.W_OK):
        raise RuntimeError(
            f"Backup destination directory is not writable: {p.parent}"
        )
    if p.exists():
        raise RuntimeError(
            f"Backup destination already exists — remove it first to avoid "
            f"overwriting an existing backup: {p}"
        )


# ---------------------------------------------------------------------------
# WAL-aware backup
# ---------------------------------------------------------------------------

def create_backup(source_db_path: str | Path, dest_path: str | Path) -> dict:
    """
    Create a consistent WAL-aware SQLite backup.

    Uses ``sqlite3.Connection.backup()`` which:
      - Checkpoints and copies the WAL frames atomically.
      - Works correctly while other connections are reading/writing.
      - Produces a standalone DB file that does not depend on the WAL.

    Parameters
    ----------
    source_db_path:
        Path to the live SQLite database file.
    dest_path:
        Path where the backup will be written.  Must not already exist;
        call ``validate_backup_destination()`` first if unsure.

    Returns
    -------
    dict with keys:
      source     — resolved absolute source path (str)
      dest       — resolved absolute destination path (str)
      size_bytes — final size of the backup file (int)
      size_human — human-readable size string
      created_at — ISO-8601 UTC timestamp of when the backup completed

    Raises RuntimeError on any failure.
    """
    source = Path(source_db_path).resolve()
    dest   = Path(dest_path).resolve()

    if not source.exists():
        raise RuntimeError(f"Source database does not exist: {source}")

    try:
        src_conn = sqlite3.connect(str(source))
        try:
            dst_conn = sqlite3.connect(str(dest))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"SQLite backup failed: {exc}") from exc

    size = dest.stat().st_size
    return {
        "source":     str(source),
        "dest":       str(dest),
        "size_bytes": size,
        "size_human": human_size(size),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# DB file metadata
# ---------------------------------------------------------------------------

def get_db_file_info(db_path: str | Path) -> dict:
    """
    Return metadata about the database file and its WAL companion.

    The displayed path is the *filename only* (no parent directory) to avoid
    leaking sensitive filesystem layout details in the UI.

    Returns
    -------
    dict with keys:
      display_name   — filename only (safe for UI display)
      exists         — bool
      size_bytes     — int | None
      size_human     — str
      modified_at    — ISO-8601 UTC str | None
      wal_present    — bool
      wal_size_bytes — int | None
      wal_size_human — str
    """
    p   = Path(db_path)
    wal = Path(f"{db_path}-wal")

    result: dict = {
        "display_name":   p.name,
        "exists":         p.exists(),
        "size_bytes":     None,
        "size_human":     "—",
        "modified_at":    None,
        "wal_present":    False,
        "wal_size_bytes": None,
        "wal_size_human": "—",
    }

    if p.exists():
        try:
            stat = p.stat()
            result["size_bytes"]  = stat.st_size
            result["size_human"]  = human_size(stat.st_size)
            result["modified_at"] = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            pass  # stat failed — leave defaults

    if wal.exists():
        result["wal_present"] = True
        try:
            wal_stat = wal.stat()
            result["wal_size_bytes"] = wal_stat.st_size
            result["wal_size_human"] = human_size(wal_stat.st_size)
        except OSError:
            pass

    return result
