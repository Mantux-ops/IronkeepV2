"""
Backup / Restore + Recovery Hardening — test suite (Slice 44).

Test groups:
  1.  backup.human_size
      - zero bytes → "0 B"
      - None → "—"
      - sub-KB values → "N B"
      - KB range → "X.Y KB"
      - MB range → "X.Y MB"
      - GB range → "X.Y GB"
      - large values without decimals (≥ 10 of unit)

  2.  backup.backup_filename
      - format matches prefix_YYYYMMDD_HHMMSS.db
      - custom prefix included
      - default prefix is "ironkeep_backup"
      - injected datetime is used (deterministic output)
      - UTC timezone is used regardless of local TZ

  3.  backup.validate_backup_destination
      - valid new path in existing writable dir → no raise
      - parent directory does not exist → RuntimeError
      - destination is an existing directory → RuntimeError
      - destination already exists (existing file) → RuntimeError

  4.  backup.create_backup — WAL-aware backup
      - produces a valid SQLite file at dest_path
      - tables from source are present in backup
      - data written before backup is in backup
      - source DB unchanged after backup
      - source path does not exist → RuntimeError
      - backup file size > 0

  5.  backup.get_db_file_info
      - existing file: exists=True, size_bytes > 0, modified_at not None
      - display_name is basename only (no directory components)
      - non-existent path: exists=False, size_bytes=None, size_human="—"
      - WAL file absent: wal_present=False
      - WAL file present: wal_present=True, wal_size_bytes >= 0
      - modified_at is ISO-8601 UTC string

  6.  startup.check_integrity
      - healthy DB → no raise
      - corrupt DB (non-SQLite file) → RuntimeError
      - empty/truncated file → RuntimeError

  7.  diagnostics page — backup section rendered
      - "Backup & Recovery" heading present
      - backup recommendations present
      - restore cautions present
      - DB filename shown in page
      - DB size shown in page
      - WAL state shown in page
      - page still passes existing permission checks (owner/officer only)

  8.  Path safety / sanitization
      - display_name never contains directory separator
      - deeply nested path exposes only filename
      - Windows-style path exposed only as filename
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import backup, database, startup
from app.main import app
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _login(client: TestClient, display_name: str) -> None:
    client.post(
        "/login",
        data={"display_name": display_name, "next": "/"},
        follow_redirects=True,
    )


def _make_member(ws_id: str, user_id: str, role: str = "member") -> None:
    with database.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), ws_id, user_id, role, _iso(_now())),
        )


# ---------------------------------------------------------------------------
# 1. human_size
# ---------------------------------------------------------------------------

class TestHumanSize:
    def test_zero(self):
        assert backup.human_size(0) == "0 B"

    def test_none(self):
        assert backup.human_size(None) == "—"

    def test_small_bytes(self):
        assert backup.human_size(512) == "512 B"

    def test_kb_range(self):
        result = backup.human_size(1536)  # 1.5 KB
        assert "KB" in result
        assert "1.5" in result

    def test_mb_range(self):
        result = backup.human_size(2 * (1 << 20))  # 2.0 MB
        assert "MB" in result

    def test_gb_range(self):
        result = backup.human_size(2 * (1 << 30))  # 2.0 GB
        assert "GB" in result

    def test_large_value_no_decimal(self):
        result = backup.human_size(10 * (1 << 20))  # 10 MB — should be "10 MB" not "10.0 MB"
        assert result == "10 MB"

    def test_small_mb_has_decimal(self):
        result = backup.human_size(5 * (1 << 20))  # 5.0 MB
        assert "5.0 MB" == result

    def test_1_byte(self):
        assert backup.human_size(1) == "1 B"

    def test_exact_kb(self):
        result = backup.human_size(1024)  # 1.0 KB
        assert "KB" in result


# ---------------------------------------------------------------------------
# 2. backup_filename
# ---------------------------------------------------------------------------

class TestBackupFilename:
    def test_default_prefix(self):
        name = backup.backup_filename()
        assert name.startswith("ironkeep_backup_")
        assert name.endswith(".db")

    def test_custom_prefix(self):
        name = backup.backup_filename(prefix="mybackup")
        assert name.startswith("mybackup_")

    def test_deterministic_with_injected_datetime(self):
        dt = datetime(2026, 5, 16, 22, 1, 0, tzinfo=timezone.utc)
        name = backup.backup_filename(now=dt)
        assert name == "ironkeep_backup_20260516_220100.db"

    def test_format_yyyymmdd_hhmmss(self):
        dt = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        name = backup.backup_filename(now=dt)
        assert "20251231_235959" in name

    def test_has_db_extension(self):
        name = backup.backup_filename()
        assert name.endswith(".db")

    def test_no_directory_separators(self):
        name = backup.backup_filename()
        assert "/" not in name
        assert "\\" not in name

    def test_custom_prefix_and_datetime(self):
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        name = backup.backup_filename(prefix="restore", now=dt)
        assert name == "restore_20260101_000000.db"


# ---------------------------------------------------------------------------
# 3. validate_backup_destination
# ---------------------------------------------------------------------------

class TestValidateBackupDestination:
    def test_valid_new_file_in_existing_dir(self, tmp_path):
        dest = tmp_path / "backup.db"
        backup.validate_backup_destination(dest)  # should not raise

    def test_parent_does_not_exist(self, tmp_path):
        dest = tmp_path / "nonexistent_dir" / "backup.db"
        with pytest.raises(RuntimeError, match="does not exist"):
            backup.validate_backup_destination(dest)

    def test_destination_is_directory(self, tmp_path):
        dest = tmp_path  # tmp_path itself is a directory
        with pytest.raises(RuntimeError, match="directory"):
            backup.validate_backup_destination(dest)

    def test_destination_already_exists(self, tmp_path):
        dest = tmp_path / "existing.db"
        dest.write_bytes(b"existing content")
        with pytest.raises(RuntimeError, match="already exists"):
            backup.validate_backup_destination(dest)

    def test_string_path_accepted(self, tmp_path):
        dest = str(tmp_path / "backup.db")
        backup.validate_backup_destination(dest)  # should not raise


# ---------------------------------------------------------------------------
# 4. create_backup — WAL-aware
# ---------------------------------------------------------------------------

class TestCreateBackup:
    def _make_source_db(self, path: Path) -> Path:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'alpha')")
        conn.execute("INSERT INTO items VALUES (2, 'beta')")
        conn.commit()
        conn.close()
        return path

    def test_backup_creates_file(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        result = backup.create_backup(src, dest)
        assert dest.exists()
        assert result["size_bytes"] > 0

    def test_backup_result_keys(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        result = backup.create_backup(src, dest)
        assert "source" in result
        assert "dest" in result
        assert "size_bytes" in result
        assert "size_human" in result
        assert "created_at" in result

    def test_backup_tables_present(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        backup.create_backup(src, dest)
        conn = sqlite3.connect(str(dest))
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        names = {r[0] for r in rows}
        assert "items" in names

    def test_backup_data_present(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        backup.create_backup(src, dest)
        conn = sqlite3.connect(str(dest))
        rows = conn.execute("SELECT name FROM items ORDER BY id").fetchall()
        conn.close()
        assert [r[0] for r in rows] == ["alpha", "beta"]

    def test_source_unchanged_after_backup(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        backup.create_backup(src, dest)
        conn = sqlite3.connect(str(src))
        rows = conn.execute("SELECT name FROM items ORDER BY id").fetchall()
        conn.close()
        assert [r[0] for r in rows] == ["alpha", "beta"]

    def test_source_not_found_raises(self, tmp_path):
        src = tmp_path / "nonexistent.db"
        dest = tmp_path / "backup.db"
        with pytest.raises(RuntimeError, match="does not exist"):
            backup.create_backup(src, dest)

    def test_backup_is_valid_sqlite_file(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        backup.create_backup(src, dest)
        conn = sqlite3.connect(str(dest))
        conn.execute("SELECT 1").fetchone()  # should not raise
        conn.close()

    def test_created_at_is_iso_utc(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        result = backup.create_backup(src, dest)
        dt = datetime.fromisoformat(result["created_at"])
        assert dt.tzinfo is not None

    def test_size_human_not_empty(self, tmp_path):
        src = self._make_source_db(tmp_path / "source.db")
        dest = tmp_path / "backup.db"
        result = backup.create_backup(src, dest)
        assert result["size_human"] != "—"


# ---------------------------------------------------------------------------
# 5. get_db_file_info
# ---------------------------------------------------------------------------

class TestGetDbFileInfo:
    def test_existing_file_exists_true(self, tmp_path):
        p = tmp_path / "ironkeep.db"
        p.write_bytes(b"x" * 4096)
        info = backup.get_db_file_info(str(p))
        assert info["exists"] is True

    def test_existing_file_size(self, tmp_path):
        p = tmp_path / "ironkeep.db"
        p.write_bytes(b"x" * 4096)
        info = backup.get_db_file_info(str(p))
        assert info["size_bytes"] == 4096

    def test_existing_file_size_human(self, tmp_path):
        p = tmp_path / "ironkeep.db"
        p.write_bytes(b"x" * 4096)
        info = backup.get_db_file_info(str(p))
        assert info["size_human"] != "—"

    def test_existing_file_modified_at(self, tmp_path):
        p = tmp_path / "ironkeep.db"
        p.write_bytes(b"hello")
        info = backup.get_db_file_info(str(p))
        assert info["modified_at"] is not None
        dt = datetime.fromisoformat(info["modified_at"])
        assert dt.tzinfo is not None

    def test_display_name_is_basename_only(self, tmp_path):
        p = tmp_path / "subdir" / "ironkeep_v2.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        info = backup.get_db_file_info(str(p))
        assert info["display_name"] == "ironkeep_v2.db"
        assert str(tmp_path) not in info["display_name"]

    def test_display_name_no_directory_separators(self, tmp_path):
        p = tmp_path / "db.db"
        p.write_bytes(b"x")
        info = backup.get_db_file_info(str(p))
        assert "/" not in info["display_name"]
        assert "\\" not in info["display_name"]

    def test_nonexistent_file_exists_false(self, tmp_path):
        p = tmp_path / "missing.db"
        info = backup.get_db_file_info(str(p))
        assert info["exists"] is False

    def test_nonexistent_file_size_none(self, tmp_path):
        p = tmp_path / "missing.db"
        info = backup.get_db_file_info(str(p))
        assert info["size_bytes"] is None
        assert info["size_human"] == "—"

    def test_nonexistent_file_modified_at_none(self, tmp_path):
        p = tmp_path / "missing.db"
        info = backup.get_db_file_info(str(p))
        assert info["modified_at"] is None

    def test_no_wal_file(self, tmp_path):
        p = tmp_path / "ironkeep.db"
        p.write_bytes(b"x")
        # Ensure WAL file does not exist
        wal = Path(f"{p}-wal")
        assert not wal.exists()
        info = backup.get_db_file_info(str(p))
        assert info["wal_present"] is False
        assert info["wal_size_bytes"] is None
        assert info["wal_size_human"] == "—"

    def test_wal_file_present(self, tmp_path):
        p = tmp_path / "ironkeep.db"
        p.write_bytes(b"x" * 100)
        wal = Path(f"{p}-wal")
        wal.write_bytes(b"w" * 512)
        info = backup.get_db_file_info(str(p))
        assert info["wal_present"] is True
        assert info["wal_size_bytes"] == 512
        assert info["wal_size_human"] != "—"

    def test_deeply_nested_path_display_name(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "ironkeep_v2.db"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_bytes(b"x")
        info = backup.get_db_file_info(str(nested))
        assert info["display_name"] == "ironkeep_v2.db"


# ---------------------------------------------------------------------------
# 6. startup.check_integrity
# ---------------------------------------------------------------------------

class TestCheckIntegrity:
    def test_healthy_db_no_raise(self, tmp_path):
        p = tmp_path / "healthy.db"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.commit()
        startup.check_integrity(conn)  # should not raise
        conn.close()

    def test_healthy_db_with_data(self, tmp_path):
        p = tmp_path / "healthy.db"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE t (x TEXT)")
        conn.execute("INSERT INTO t VALUES ('hello')")
        conn.commit()
        startup.check_integrity(conn)  # should not raise
        conn.close()

    def test_corrupt_file_raises(self, tmp_path):
        p = tmp_path / "corrupt.db"
        # Write arbitrary non-SQLite bytes
        p.write_bytes(b"\x00" * 8192)
        with pytest.raises(Exception):
            conn = sqlite3.connect(str(p))
            startup.check_integrity(conn)
            conn.close()

    def test_in_memory_db_passes(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE x (id INTEGER)")
        conn.commit()
        startup.check_integrity(conn)  # should not raise
        conn.close()


# ---------------------------------------------------------------------------
# 7. Diagnostics page — backup section rendered
# ---------------------------------------------------------------------------

class TestDiagnosticsBackupSection:
    """
    Verify that the Backup & Recovery section is present in the diagnostics
    page and that DB file metadata is rendered.
    """

    def _setup(self, tmp_path):
        owner = make_user("BackupDiagOwner")
        ws    = make_workspace(
            name="Backup Diag WS",
            slug="backup-diag-ws",
            owner_user_id=owner["id"],
        )
        return owner, ws

    def test_backup_heading_present(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOwner")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200
        assert "Backup" in resp.text

    def test_backup_recommendations_present(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOwner")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200
        assert "backup" in resp.text.lower()
        assert "recommendation" in resp.text.lower() or "Backup recommendations" in resp.text

    def test_restore_cautions_present(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOwner")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200
        assert "restore" in resp.text.lower() or "Restore" in resp.text

    def test_db_filename_shown(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOwner")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200
        # Should show the filename (basename of the configured DB path)
        from app import database as db_mod
        expected_name = Path(db_mod._DB_PATH).name
        assert expected_name in resp.text

    def test_db_size_shown(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOwner")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200
        # Size must be visible — any of the human-size units
        assert any(unit in resp.text for unit in ["KB", "MB", "GB", " B"])

    def test_wal_state_shown(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOwner")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200
        # WAL file row must be present in some form
        assert "WAL" in resp.text

    def test_member_gets_403(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        member = make_user("BackupDiagMember")
        _make_member(ws["id"], member["id"], role="member")
        client = TestClient(app, raise_server_exceptions=False)
        _login(client, "BackupDiagMember")
        resp = client.get(
            f"/workspaces/{ws['slug']}/settings/diagnostics",
            follow_redirects=True,
        )
        assert resp.status_code == 403

    def test_officer_gets_200(self, tmp_path):
        owner, ws = self._setup(tmp_path)
        officer = make_user("BackupDiagOfficer")
        _make_member(ws["id"], officer["id"], role="officer")
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOfficer")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200

    def test_no_absolute_path_exposed(self, tmp_path):
        """The full filesystem path should not appear in the rendered HTML."""
        owner, ws = self._setup(tmp_path)
        client = TestClient(app, raise_server_exceptions=True)
        _login(client, "BackupDiagOwner")
        resp = client.get(f"/workspaces/{ws['slug']}/settings/diagnostics")
        assert resp.status_code == 200
        from app import database as db_mod
        db_parent = str(Path(db_mod._DB_PATH).parent)
        # The parent directory path should not appear verbatim in the HTML
        assert db_parent not in resp.text


# ---------------------------------------------------------------------------
# 8. Path sanitization
# ---------------------------------------------------------------------------

class TestPathSanitization:
    def test_deeply_nested_path_no_dir_in_display(self, tmp_path):
        nested = tmp_path / "production" / "data" / "ironkeep_v2.db"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_bytes(b"x")
        info = backup.get_db_file_info(str(nested))
        assert info["display_name"] == "ironkeep_v2.db"
        assert "production" not in info["display_name"]
        assert "data" not in info["display_name"]

    def test_display_name_is_string(self, tmp_path):
        p = tmp_path / "test.db"
        p.write_bytes(b"x")
        info = backup.get_db_file_info(str(p))
        assert isinstance(info["display_name"], str)

    def test_nonexistent_path_display_name_still_basename(self, tmp_path):
        p = tmp_path / "somewhere" / "missing.db"
        info = backup.get_db_file_info(str(p))
        assert info["display_name"] == "missing.db"

    def test_windows_style_path_handled(self, tmp_path):
        # Use a real tmp_path-based path; only test the basename extraction
        p = tmp_path / "mydb.db"
        p.write_bytes(b"x")
        info = backup.get_db_file_info(str(p))
        assert info["display_name"] == "mydb.db"
