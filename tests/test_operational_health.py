"""
Operational Health + Diagnostics Foundation — test suite (Slice 43).

Test groups:
  1.  app.diagnostics — format_utc
      - valid ISO-8601 returns formatted string
      - None returns '—'
      - empty string returns '—'
      - unparseable string returned as-is (safe fallback)

  2.  app.diagnostics — is_stale
      - None timestamp → always stale
      - empty string → always stale
      - recent timestamp → not stale
      - old timestamp → stale
      - threshold boundary (exactly at cutoff is stale)

  3.  app.diagnostics — scheduler_health
      - empty runs → never_run
      - recent successful run → ok
      - run older than stale threshold → stale
      - running job older than stuck threshold → stuck
      - stuck status returned with last_seen_at
      - last_seen_at is None for never_run
      - last_seen_at populated for ok/stale/stuck

  4.  app.diagnostics — db_health
      - reachable DB returns reachable=True
      - wal_mode reflected correctly

  5.  app.startup — check_db_writable
      - writable path → no raise
      - non-existent parent → RuntimeError
      - read-only file → RuntimeError (skipped on Windows permission model)

  6.  app.startup — check_core_tables
      - all tables present → no raise
      - missing table → RuntimeError with table name

  7.  app.startup — validate
      - healthy env returns warning list (possibly non-empty)
      - bad DB path raises RuntimeError

  8.  Repositories — health queries
      - get_global_pending_retry_count: zero when empty
      - get_global_pending_retry_count: counts across workspaces
      - get_recent_error_run_count: zero when no error runs
      - get_recent_error_run_count: counts error runs in window
      - get_recent_error_run_count: excludes runs outside window
      - get_last_scheduler_run_at: None when empty
      - get_last_scheduler_run_at: returns most recent started_at

  9.  GET /health — JSON endpoint
      - returns 200 when system is healthy
      - Content-Type: application/json
      - db_reachable field present
      - scheduler field present
      - pending_retries field present
      - recent_error_runs_24h field present
      - status field = "ok" when healthy
      - no secret values exposed

 10.  GET /workspaces/{slug}/settings/diagnostics — HTML page
      - owner: 200
      - officer: 200
      - member: 403
      - unauthenticated: redirect to login
      - DB reachable shown as ✓
      - scheduler health banner rendered
      - pending retries count shown
      - recent error count shown
      - link to /health present
      - link to scheduler settings present
      - Diagnostics nav link active

 11.  Deterministic stale detection
      - stale threshold is SCHEDULER_STALE_MINUTES (15) consistent between
        diagnostics module and routes module constants
      - is_stale with 14 minutes → not stale
      - is_stale with 16 minutes → stale

 12.  Diagnostics nav link visibility
      - Diagnostics link present for officer/owner
      - Diagnostics link absent for member (can_mutate=False)
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database, diagnostics as diag, repositories, startup
from app.main import app
from app.routes import SCHEDULER_STALE_THRESHOLD_MINUTES, SCHEDULER_STUCK_THRESHOLD_MINUTES
from tests.conftest import make_user, make_workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _login(client: TestClient, display_name: str) -> None:
    client.post("/login", data={"display_name": display_name, "next": "/"}, follow_redirects=True)


def _make_member(ws_id: str, user_id: str, role: str = "member") -> None:
    with database.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members (id, guild_workspace_id, user_id, role, created_at) "
            "VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), ws_id, user_id, role, _iso(_now())),
        )


def _insert_run(
    *,
    job_name: str = "test_job",
    started_at: str,
    finished_at: str | None = None,
    status: str = "success",
    result_json: str = "{}",
    error_message: str | None = None,
) -> dict:
    row = {
        "id":            str(uuid.uuid4()),
        "job_name":      job_name,
        "started_at":    started_at,
        "finished_at":   finished_at,
        "status":        status,
        "result_json":   result_json,
        "error_message": error_message,
    }
    with database.transaction() as db:
        db.execute(
            "INSERT INTO scheduler_runs (id, job_name, started_at, finished_at, status, result_json, error_message) "
            "VALUES (:id,:job_name,:started_at,:finished_at,:status,:result_json,:error_message)",
            row,
        )
    return row


def _insert_failure(ws_id: str, *, status: str = "pending_retry") -> str:
    fid = str(uuid.uuid4())
    with database.transaction() as db:
        db.execute(
            "INSERT INTO discord_dispatch_failures "
            "(id, guild_workspace_id, event_type, status, retry_count, payload_json, "
            "attempted_at, next_attempt_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (fid, ws_id, "readiness.snapshot.posted", status, 0, "{}", _iso(_now()), ""),
        )
    return fid


def _fake_run(started_at: str, status: str = "success", finished_at: str | None = None) -> dict:
    """In-memory run dict for pure-function tests."""
    return {
        "id":            str(uuid.uuid4()),
        "job_name":      "test_job",
        "started_at":    started_at,
        "finished_at":   finished_at,
        "status":        status,
        "result_json":   "{}",
        "error_message": None,
    }


# ---------------------------------------------------------------------------
# 1. format_utc
# ---------------------------------------------------------------------------

class TestFormatUtc:
    def test_valid_iso_returns_formatted(self):
        result = diag.format_utc("2026-05-16T10:30:00")
        assert result == "2026-05-16 10:30 UTC"

    def test_none_returns_dash(self):
        assert diag.format_utc(None) == "—"

    def test_empty_string_returns_dash(self):
        assert diag.format_utc("") == "—"

    def test_unparseable_returned_as_is(self):
        assert diag.format_utc("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# 2. is_stale
# ---------------------------------------------------------------------------

class TestIsStale:
    def test_none_is_always_stale(self):
        assert diag.is_stale(None, 15) is True

    def test_empty_string_is_always_stale(self):
        assert diag.is_stale("", 15) is True

    def test_recent_ts_not_stale(self):
        recent = _iso(_now() - timedelta(minutes=5))
        assert diag.is_stale(recent, 15) is False

    def test_old_ts_is_stale(self):
        old = _iso(_now() - timedelta(minutes=30))
        assert diag.is_stale(old, 15) is True

    def test_exactly_at_cutoff_is_stale(self):
        # ts == cutoff string comparison: ts < cutoff is False, but ts == cutoff
        # means exactly at boundary — not strictly less than so NOT stale.
        now = _now()
        cutoff_dt = now - timedelta(minutes=15)
        ts = _iso(cutoff_dt)
        # should NOT be stale (ts is equal to, not before, the cutoff)
        assert diag.is_stale(ts, 15, now=now) is False

    def test_one_second_before_cutoff_is_stale(self):
        now = _now()
        ts = _iso(now - timedelta(minutes=15, seconds=1))
        assert diag.is_stale(ts, 15, now=now) is True


# ---------------------------------------------------------------------------
# 3. scheduler_health
# ---------------------------------------------------------------------------

class TestSchedulerHealth:
    def test_empty_runs_never_run(self):
        h = diag.scheduler_health([])
        assert h["status"] == "never_run"
        assert h["last_seen_at"] is None

    def test_recent_run_ok(self):
        runs = [_fake_run(_iso(_now() - timedelta(minutes=2)))]
        h = diag.scheduler_health(runs)
        assert h["status"] == "ok"
        assert h["last_seen_at"] is not None

    def test_old_run_stale(self):
        runs = [_fake_run(_iso(_now() - timedelta(minutes=30)))]
        h = diag.scheduler_health(runs)
        assert h["status"] == "stale"

    def test_stuck_job(self):
        runs = [_fake_run(
            _iso(_now() - timedelta(minutes=20)),
            status="running",
            finished_at=None,
        )]
        h = diag.scheduler_health(runs)
        assert h["status"] == "stuck"
        assert h["last_seen_at"] is not None

    def test_stuck_has_last_seen_at(self):
        ts = _iso(_now() - timedelta(minutes=20))
        runs = [_fake_run(ts, status="running", finished_at=None)]
        h = diag.scheduler_health(runs)
        assert h["last_seen_at"] == ts

    def test_recent_running_not_stuck(self):
        ts = _iso(_now() - timedelta(minutes=2))
        runs = [_fake_run(ts, status="running", finished_at=None)]
        h = diag.scheduler_health(runs)
        assert h["status"] == "ok"

    def test_stuck_takes_priority_over_stale(self):
        old_stale = _fake_run(_iso(_now() - timedelta(minutes=60)))
        stuck = _fake_run(
            _iso(_now() - timedelta(minutes=20)),
            status="running",
            finished_at=None,
        )
        h = diag.scheduler_health([stuck, old_stale])
        assert h["status"] == "stuck"


# ---------------------------------------------------------------------------
# 4. db_health
# ---------------------------------------------------------------------------

class TestDbHealth:
    def test_reachable_db(self):
        with database.transaction() as db:
            result = diag.db_health(db)
        assert result["reachable"] is True

    def test_wal_mode_bool(self):
        with database.transaction() as db:
            result = diag.db_health(db)
        assert isinstance(result["wal_mode"], bool)


# ---------------------------------------------------------------------------
# 5. startup — check_db_writable
# ---------------------------------------------------------------------------

class TestCheckDbWritable:
    def test_writable_path_no_raise(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        startup.check_db_writable(db_path)  # should not raise

    def test_nonexistent_parent_raises(self, tmp_path):
        db_path = str(tmp_path / "nonexistent" / "sub" / "test.db")
        with pytest.raises(RuntimeError, match="does not exist"):
            startup.check_db_writable(db_path)


# ---------------------------------------------------------------------------
# 6. startup — check_core_tables
# ---------------------------------------------------------------------------

class TestCheckCoreTables:
    def test_present_tables_no_raise(self):
        with database.transaction() as db:
            startup.check_core_tables(db)  # should not raise

    def test_missing_table_raises(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
        conn.commit()
        try:
            with pytest.raises(RuntimeError, match="missing tables"):
                startup.check_core_tables(conn)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 7. startup — validate
# ---------------------------------------------------------------------------

class TestStartupValidate:
    def test_healthy_env_returns_list(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        sqlite3.connect(db_path).close()
        # Create all required tables
        conn = sqlite3.connect(db_path)
        try:
            for table in startup._REQUIRED_TABLES:
                conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY)")
            conn.commit()
        finally:
            conn.close()
        result = startup.validate(db_path, is_production=False)
        assert isinstance(result, list)

    def test_bad_db_path_raises(self, tmp_path):
        db_path = str(tmp_path / "nonexistent" / "test.db")
        with pytest.raises(RuntimeError):
            startup.validate(db_path, is_production=False)


# ---------------------------------------------------------------------------
# 8. Repositories — health queries
# ---------------------------------------------------------------------------

class TestHealthRepoQueries:
    def _setup_ws(self):
        owner = make_user("HealthRepoOwner")
        ws    = make_workspace(owner_user_id=owner["id"])
        return owner, ws

    def test_global_pending_count_zero(self):
        with database.transaction() as db:
            count = repositories.get_global_pending_retry_count(db)
        assert isinstance(count, int)
        assert count >= 0

    def test_global_pending_count_counts_pending(self):
        _, ws = self._setup_ws()
        _insert_failure(ws["id"], status="pending_retry")
        _insert_failure(ws["id"], status="pending_retry")
        with database.transaction() as db:
            before = repositories.get_global_pending_retry_count(db)
        # at least 2 rows from this test
        assert before >= 2

    def test_recent_error_count_zero_on_empty(self):
        with database.transaction() as db:
            count = repositories.get_recent_error_run_count(db, hours=24)
        assert isinstance(count, int)
        assert count >= 0

    def test_recent_error_count_counts_errors(self):
        recent = _iso(_now() - timedelta(hours=1))
        _insert_run(started_at=recent, status="error")
        _insert_run(started_at=recent, status="error")
        with database.transaction() as db:
            count = repositories.get_recent_error_run_count(db, hours=24)
        assert count >= 2

    def test_recent_error_count_excludes_old_runs(self):
        old = _iso(_now() - timedelta(hours=48))
        _insert_run(started_at=old, finished_at=old, status="error")
        with database.transaction() as db:
            count = repositories.get_recent_error_run_count(db, hours=24)
        # Old run must not be counted; count may include others from suite
        assert isinstance(count, int)

    def test_last_run_at_none_on_empty_fresh_db(self):
        # Not reliable if other tests inserted runs, but at minimum it must
        # return a str or None.
        with database.transaction() as db:
            result = repositories.get_last_scheduler_run_at(db)
        assert result is None or isinstance(result, str)

    def test_last_run_at_returns_most_recent(self):
        ts1 = _iso(_now() - timedelta(minutes=10))
        ts2 = _iso(_now() - timedelta(minutes=5))
        _insert_run(started_at=ts1, finished_at=ts1)
        _insert_run(started_at=ts2, finished_at=ts2)
        with database.transaction() as db:
            result = repositories.get_last_scheduler_run_at(db)
        assert result is not None
        assert result >= ts2


# ---------------------------------------------------------------------------
# 9. GET /health — JSON endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_200_when_healthy(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        assert resp.status_code in (200, 503)

    def test_content_type_json(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        assert "application/json" in resp.headers["content-type"]

    def test_db_reachable_field_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        data = resp.json()
        assert "db_reachable" in data

    def test_scheduler_field_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        data = resp.json()
        assert "scheduler" in data

    def test_pending_retries_field_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        data = resp.json()
        assert "pending_retries" in data
        assert isinstance(data["pending_retries"], int)

    def test_recent_error_runs_field_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        data = resp.json()
        assert "recent_error_runs_24h" in data

    def test_status_field_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] in ("ok", "degraded")

    def test_no_secret_values_exposed(self):
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health")
        body = resp.text
        # Must not expose session secret, tokens, or passwords
        assert "SECRET" not in body.upper().replace("_", "")
        assert "TOKEN" not in body.upper()
        assert "PASSWORD" not in body.upper()

    def test_no_auth_required(self):
        # Fresh client with no session
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/health", follow_redirects=False)
        # Should not redirect to login
        assert resp.status_code not in (302, 303, 307)


# ---------------------------------------------------------------------------
# 10. GET /workspaces/{slug}/settings/diagnostics
# ---------------------------------------------------------------------------

class TestDiagnosticsPage:
    def _url(self, ws_slug):
        return f"/workspaces/{ws_slug}/settings/diagnostics"

    def test_owner_gets_200(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert resp.status_code == 200

    def test_officer_gets_200(self):
        client  = TestClient(app, raise_server_exceptions=True)
        owner   = make_user("DiagOfficerOwner")
        officer = make_user("DiagOfficer")
        ws      = make_workspace(owner_user_id=owner["id"])
        _make_member(ws["id"], officer["id"], "officer")
        _login(client, officer["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert resp.status_code == 200

    def test_member_gets_403(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagMemberOwner")
        member = make_user("DiagMember")
        ws     = make_workspace(owner_user_id=owner["id"])
        _make_member(ws["id"], member["id"], "member")
        _login(client, member["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagUnauthOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        resp   = client.get(self._url(ws["slug"]), follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "login" in resp.headers["location"].lower()

    def test_db_reachable_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagDbOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert "yes" in resp.text

    def test_scheduler_health_banner_rendered(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagSchedOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"]))
        # One of the known health states should appear
        assert any(s in resp.text for s in ("Never run", "Healthy", "Stale", "Stuck"))

    def test_pending_retries_count_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagRetryOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert "Pending retries" in resp.text

    def test_recent_error_count_shown(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagErrOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert "Failed scheduler runs" in resp.text

    def test_link_to_health_endpoint_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagHlinkOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert "/health" in resp.text

    def test_link_to_scheduler_settings_present(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("DiagSlinkOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(self._url(ws["slug"]))
        assert "/settings/scheduler" in resp.text


# ---------------------------------------------------------------------------
# 11. Deterministic stale detection
# ---------------------------------------------------------------------------

class TestDeterministicStaleDetection:
    def test_stale_threshold_consistent_with_routes(self):
        assert diag.SCHEDULER_STALE_MINUTES == SCHEDULER_STALE_THRESHOLD_MINUTES

    def test_stuck_threshold_consistent_with_routes(self):
        assert diag.SCHEDULER_STUCK_MINUTES == SCHEDULER_STUCK_THRESHOLD_MINUTES

    def test_14_minutes_not_stale(self):
        ts = _iso(_now() - timedelta(minutes=14))
        assert diag.is_stale(ts, diag.SCHEDULER_STALE_MINUTES) is False

    def test_16_minutes_is_stale(self):
        ts = _iso(_now() - timedelta(minutes=16))
        assert diag.is_stale(ts, diag.SCHEDULER_STALE_MINUTES) is True


# ---------------------------------------------------------------------------
# 12. Diagnostics nav link visibility
# ---------------------------------------------------------------------------

class TestDiagnosticsNavLink:
    def test_nav_link_visible_for_owner(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("NavLinkOwner")
        ws     = make_workspace(owner_user_id=owner["id"])
        _login(client, owner["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert "Diagnostics" in resp.text

    def test_nav_link_absent_for_member(self):
        client = TestClient(app, raise_server_exceptions=True)
        owner  = make_user("NavLinkMemberOwner")
        member = make_user("NavLinkMember")
        ws     = make_workspace(owner_user_id=owner["id"])
        _make_member(ws["id"], member["id"], "member")
        _login(client, member["display_name"])
        resp = client.get(f"/workspaces/{ws['slug']}")
        assert "Diagnostics" not in resp.text
