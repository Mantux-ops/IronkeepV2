#!/usr/bin/env python3
"""
scripts/backup_db.py — Create a WAL-aware SQLite backup of the IronkeepV2 database.

Usage
-----
  python scripts/backup_db.py [options]

Options
-------
  --dest PATH         Explicit destination path for the backup file.
                      If omitted, a timestamped file is created inside --backup-dir.
  --backup-dir DIR    Directory for auto-named backups (default: same directory as
                      the source database).
  --prefix STR        Filename prefix for auto-named backups (default: ironkeep_backup).
  --verify            Run integrity_check on the completed backup (recommended).

Examples
--------
  # Auto-named backup next to the live DB
  python scripts/backup_db.py

  # Auto-named backup in a dedicated directory
  python scripts/backup_db.py --backup-dir /var/lib/ironkeep/backups/

  # Explicit destination
  python scripts/backup_db.py --dest /mnt/nas/ironkeep_prod_20260516.db

  # Auto-name + integrity verify
  python scripts/backup_db.py --backup-dir /var/lib/ironkeep/backups/ --verify

Environment
-----------
  IRONKEEP_DB_PATH    Source database path (defaults to "ironkeep_v2.db").

Exit codes
----------
  0  — backup created (and verified, if --verify was passed)
  1  — error (printed to stderr)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Allow running from the project root without installing the package.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app import backup, startup  # noqa: E402 (after sys.path insertion)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create a WAL-aware SQLite backup of the IronkeepV2 database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--dest",
        metavar="PATH",
        default=None,
        help="Explicit destination path for the backup file.",
    )
    p.add_argument(
        "--backup-dir",
        metavar="DIR",
        default=None,
        help="Directory for auto-named backups (default: same directory as source DB).",
    )
    p.add_argument(
        "--prefix",
        default="ironkeep_backup",
        help="Filename prefix for auto-named backups (default: ironkeep_backup).",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        default=False,
        help="Run integrity_check on the completed backup.",
    )
    return p


def resolve_destination(args: argparse.Namespace, db_path: str) -> str:
    """
    Determine the backup destination path from parsed CLI arguments.

    Priority:
      1. --dest (explicit path)
      2. --backup-dir / auto-generated filename
      3. DB directory / auto-generated filename (default)
    """
    if args.dest:
        return args.dest

    filename = backup.backup_filename(prefix=args.prefix)

    if args.backup_dir:
        return str(Path(args.backup_dir) / filename)

    # Default: same directory as the source DB
    return str(Path(db_path).parent / filename)


def main(argv: list[str] | None = None) -> int:
    """
    Entry point for the backup script.

    Parameters
    ----------
    argv:
        Argument list (defaults to sys.argv[1:] when None).

    Returns
    -------
    Exit code: 0 for success, 1 for any error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    db_path = os.environ.get("IRONKEEP_DB_PATH", "ironkeep_v2.db")

    dest = resolve_destination(args, db_path)

    try:
        backup.validate_backup_destination(dest)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Source : {db_path}")
    print(f"Dest   : {dest}")
    print("Creating backup ...", end=" ", flush=True)

    try:
        result = backup.create_backup(db_path, dest)
    except RuntimeError as exc:
        print("FAILED", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done ({result['size_human']})")

    if args.verify:
        print("Verifying backup integrity ...", end=" ", flush=True)
        try:
            conn = sqlite3.connect(dest)
            try:
                startup.check_core_tables(conn)
                startup.check_integrity(conn)
            finally:
                conn.close()
        except RuntimeError as exc:
            print("FAILED", file=sys.stderr)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("ok")

    print(f"Backup complete: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
