"""
Scheduler Status page tests.

Tests cover:
- Access control (owner, officer, member, unauthenticated)
- Health banners: never_run, stale, stuck, ok
- Stuck detection: recent running jobs are NOT marked stuck
- Run table: success badge, error badge, stuck badge, running badge
- Error message rendering
- result_json summary and <details> disclosure
- Invalid result_json handled safely
- Pending dispatch failures count shown
- No pending failures message shown
- No POST route registered (405)
- Stable ordering (DESC by started_at, id)
- Route helper unit tests: _format_utc, _parse_result_summary,
  _compute_duration, _run_badge_status, _enrich_scheduler_run,
  _scheduler_health

The scheduler loop is never started.  Rows are inserted directly into
scheduler_runs for test setup.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, repositories
from app.application import use_cases
from app.main import app
from app.routes import (
    SCHEDULER_STALE_THRESHOLD_MINUTES,
    SCHEDULER_STUCK_THRESHOLD_MINUTES,
    _compute_duration,
    _enrich_scheduler_run,
    _format_utc,
    _parse_result_summary,
    _run_badge_status,
    _scheduler_health,
)
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


def _status_url(slug: str) -> str:
    return f"/workspaces/{slug}/settings/scheduler"


def _insert_run(
    job_name: str = "retry_dispatch_failures",
    started_at: str | None = None,
    finished_at: str | None = None,
    status: str = "success",
    result_json: str = "{}",
    error_message: str | None = None,
) -> dict:
    """Insert a scheduler_runs row directly for test setup."""
    run_id = str(uuid.uuid4())
    started = started_at or _iso(_now())
    record = {
        "id":            run_id,
        "job_name":      job_name,
        "started_at":    started,
        "finished_at":   finished_at or (started if status != "running" else None),
        "status":        status,
        "result_json":   result_json,
        "error_message": error_message,
    }
    with database.transaction() as db:
        repositories.insert_scheduler_run(db, record)
    return record


def _insert_failure(ws_id: str, status: str = "pending_retry") -> dict:
    """Insert a discord_dispatch_failures row for the pending-count tests."""
    record = {
        "id":                 str(uuid.uuid4()),
        "guild_workspace_id": ws_id,
        "guild_operation_id": None,
        "event_type":         "readiness_snapshot.created",
        "entity_id":          None,
        "error_code":         None,
        "error_message":      "test failure",
        "attempted_at":       _iso(_now()),
        "retry_count":        0,
        "status":             status,
        "payload_json":       "{}",
        "next_attempt_at":    "",
    }
    with database.transaction() as db:
        repositories.insert_discord_dispatch_failure(db, record)
    return record


def _stale_cutoff() -> str:
    return _iso(_now() - timedelta(minutes=SCHEDULER_STALE_THRESHOLD_MINUTES))


def _stuck_cutoff() -> str:
    return _iso(_now() - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES))


# ---------------------------------------------------------------------------
# 1. Access control
# ---------------------------------------------------------------------------

class TestAccessControl:
    def test_owner_can_view(self):
        owner = make_user("SchedOwner")
        ws = make_workspace(slug="sched-owner-ws", owner_user_id=owner["id"])

        client = TestClient(app)
        _login(client, "SchedOwner")
        resp = client.get(_status_url("sched-owner-ws"))
        assert resp.status_code == 200

    def test_officer_can_view(self):
        owner = make_user("SchedOfficerOwner")
        ws = make_workspace(slug="sched-officer-ws", owner_user_id=owner["id"])
        use_cases.add_workspace_member(ws["id"], owner["id"], "SchedOfficer", role="officer")

        client = TestClient(app)
        _login(client, "SchedOfficer")
        resp = client.get(_status_url("sched-officer-ws"))
        assert resp.status_code == 200

    def test_member_blocked(self):
        owner = make_user("SchedMemberOwner")
        ws = make_workspace(slug="sched-member-ws", owner_user_id=owner["id"])
        use_cases.add_workspace_member(ws["id"], owner["id"], "SchedMember", role="member")

        client = TestClient(app)
        _login(client, "SchedMember")
        resp = client.get(_status_url("sched-member-ws"))
        assert resp.status_code == 403

    def test_unauthenticated_redirected_to_login(self):
        make_workspace(slug="sched-anon-ws")
        client = TestClient(app, follow_redirects=False)
        resp = client.get(_status_url("sched-anon-ws"))
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# 2. Health banners
# ---------------------------------------------------------------------------

class TestHealthBanners:
    def _get_page(self, slug: str) -> str:
        client = TestClient(app)
        _login(client, f"Owner-{slug}")
        return client.get(_status_url(slug)).text

    def _make_ws(self, slug: str) -> dict:
        owner = make_user(f"Owner-{slug}")
        return make_workspace(slug=slug, owner_user_id=owner["id"])

    def test_never_run_banner_when_no_rows(self):
        self._make_ws("never-run-ws")
        body = self._get_page("never-run-ws")
        assert "Never run" in body or "never run" in body.lower()
        assert "SCHEDULER_ENABLED" in body

    def test_stale_banner_when_last_run_is_old(self):
        self._make_ws("stale-ws")
        old_start = _iso(_now() - timedelta(minutes=SCHEDULER_STALE_THRESHOLD_MINUTES + 5))
        _insert_run(started_at=old_start, finished_at=old_start, status="success")
        body = self._get_page("stale-ws")
        assert "stale" in body.lower() or "stopped" in body.lower()

    def test_stuck_banner_when_unfinished_old_job(self):
        self._make_ws("stuck-ws")
        old_start = _iso(_now() - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES + 5))
        _insert_run(
            started_at=old_start,
            finished_at=None,
            status="running",
        )
        body = self._get_page("stuck-ws")
        assert "stuck" in body.lower() or "crashed" in body.lower()

    def test_recent_running_job_is_not_marked_stuck(self):
        """A job started 1 minute ago (within the stuck window) must show as 'running'."""
        self._make_ws("recent-run-ws")
        recent_start = _iso(_now() - timedelta(minutes=1))
        _insert_run(
            started_at=recent_start,
            finished_at=None,
            status="running",
        )
        body = self._get_page("recent-run-ws")
        # "stuck" should NOT appear in the health banner
        assert "Stuck job detected" not in body
        # The running badge should appear in the table
        assert "running" in body.lower()

    def test_ok_banner_when_scheduler_is_active(self):
        self._make_ws("ok-ws")
        _insert_run(status="success")
        body = self._get_page("ok-ws")
        assert "Active" in body or "active" in body.lower()


# ---------------------------------------------------------------------------
# 3. Run table content
# ---------------------------------------------------------------------------

class TestRunTable:
    def _setup(self, slug: str) -> tuple[str, TestClient]:
        owner = make_user(f"TableOwner-{slug}")
        make_workspace(slug=slug, owner_user_id=owner["id"])
        client = TestClient(app)
        _login(client, f"TableOwner-{slug}")
        return slug, client

    def test_success_badge_shown(self):
        slug, client = self._setup("tbl-success-ws")
        _insert_run(status="success")
        body = client.get(_status_url(slug)).text
        assert "success" in body

    def test_error_badge_and_message_shown(self):
        slug, client = self._setup("tbl-error-ws")
        _insert_run(status="error", error_message="something exploded")
        body = client.get(_status_url(slug)).text
        assert "error" in body
        assert "something exploded" in body

    def test_stuck_row_shows_no_duration(self):
        """A stuck run (finished_at=NULL) must render '—' for duration, not crash."""
        slug, client = self._setup("tbl-stuck-ws")
        old_start = _iso(_now() - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES + 5))
        _insert_run(started_at=old_start, finished_at=None, status="running")
        resp = client.get(_status_url(slug))
        assert resp.status_code == 200
        body = resp.text
        # Duration column for a stuck row must show "—", not a computed value
        assert "—" in body

    def test_result_json_summary_rendered(self):
        slug, client = self._setup("tbl-summary-ws")
        _insert_run(result_json='{"checked": 3, "resolved": 2}')
        body = client.get(_status_url(slug)).text
        assert "checked: 3" in body
        assert "resolved: 2" in body

    def test_invalid_json_handled_safely(self):
        """Malformed result_json must not raise — renders a safe fallback."""
        slug, client = self._setup("tbl-badjson-ws")
        _insert_run(result_json="not-valid-json")
        resp = client.get(_status_url(slug))
        assert resp.status_code == 200
        assert "invalid result_json" in resp.text

    def test_details_element_renders_raw_json(self):
        """A <details> disclosure with the raw result_json must appear."""
        slug, client = self._setup("tbl-details-ws")
        payload = '{"checked": 5, "resolved": 4}'
        _insert_run(result_json=payload)
        body = client.get(_status_url(slug)).text
        assert "<details" in body
        assert "checked" in body

    def test_job_name_shown_in_table(self):
        slug, client = self._setup("tbl-jobname-ws")
        _insert_run(job_name="refresh_stale_metadata")
        body = client.get(_status_url(slug)).text
        assert "refresh_stale_metadata" in body

    def test_stable_ordering_newest_first(self):
        """Runs are returned newest-first; the page preserves this order."""
        slug, client = self._setup("tbl-order-ws")
        older = _iso(_now() - timedelta(hours=1))
        newer = _iso(_now())
        _insert_run(job_name="job_old", started_at=older, finished_at=older, status="success")
        _insert_run(job_name="job_new", started_at=newer, finished_at=newer, status="success")
        body = client.get(_status_url(slug)).text
        idx_new = body.index("job_new")
        idx_old = body.index("job_old")
        assert idx_new < idx_old, "Newer run should appear before older run"


# ---------------------------------------------------------------------------
# 4. Pending dispatch failures
# ---------------------------------------------------------------------------

class TestPendingFailures:
    def _setup(self, slug: str) -> tuple[dict, TestClient]:
        owner = make_user(f"PFOwner-{slug}")
        ws = make_workspace(slug=slug, owner_user_id=owner["id"])
        client = TestClient(app)
        _login(client, f"PFOwner-{slug}")
        return ws, client

    def test_pending_count_shown_when_failures_exist(self):
        ws, client = self._setup("pf-count-ws")
        _insert_failure(ws["id"])
        _insert_failure(ws["id"])
        body = client.get(_status_url("pf-count-ws")).text
        assert "2" in body
        assert "Pending Discord retries" in body or "pending" in body.lower()

    def test_no_pending_message_when_zero_failures(self):
        ws, client = self._setup("pf-zero-ws")
        body = client.get(_status_url("pf-zero-ws")).text
        assert "No pending Discord dispatch failures" in body

    def test_resolved_failures_not_counted(self):
        """Only pending_retry rows are counted — resolved and exhausted are excluded."""
        ws, client = self._setup("pf-resolved-ws")
        _insert_failure(ws["id"], status="resolved")
        _insert_failure(ws["id"], status="exhausted")
        body = client.get(_status_url("pf-resolved-ws")).text
        assert "No pending Discord dispatch failures" in body

    def test_pending_count_is_workspace_scoped(self):
        """Failures from other workspaces must not appear in the count."""
        owner_a = make_user("PFOwnerA")
        ws_a = make_workspace(slug="pf-ws-a", owner_user_id=owner_a["id"])
        owner_b = make_user("PFOwnerB")
        ws_b = make_workspace(slug="pf-ws-b", owner_user_id=owner_b["id"])

        # Insert failures only for ws_b
        _insert_failure(ws_b["id"])
        _insert_failure(ws_b["id"])

        client = TestClient(app)
        _login(client, "PFOwnerA")
        body = client.get(_status_url("pf-ws-a")).text
        assert "No pending Discord dispatch failures" in body


# ---------------------------------------------------------------------------
# 5. No POST route
# ---------------------------------------------------------------------------

class TestNoPostRoute:
    def test_post_returns_405(self):
        """There is no POST handler — any POST must return 405 Method Not Allowed."""
        owner = make_user("PostOwner")
        ws = make_workspace(slug="post-405-ws", owner_user_id=owner["id"])
        client = TestClient(app)
        _login(client, "PostOwner")
        resp = client.post(_status_url("post-405-ws"))
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# 6. Route helper unit tests (pure functions, no HTTP)
# ---------------------------------------------------------------------------

class TestFormatUtc:
    def test_none_returns_dash(self):
        assert _format_utc(None) == "—"

    def test_empty_string_returns_dash(self):
        assert _format_utc("") == "—"

    def test_valid_iso_formats_correctly(self):
        result = _format_utc("2026-05-16T09:30:45.123456+00:00")
        assert "2026-05-16" in result
        assert "09:30" in result
        assert "UTC" in result

    def test_invalid_ts_returns_as_is(self):
        result = _format_utc("not-a-timestamp")
        assert "not-a-timestamp" in result


class TestParseResultSummary:
    def test_empty_returns_empty(self):
        assert _parse_result_summary(None) == ""
        assert _parse_result_summary("") == ""

    def test_valid_dict_produces_summary(self):
        result = _parse_result_summary('{"checked": 3, "resolved": 2}')
        assert "checked: 3" in result
        assert "resolved: 2" in result

    def test_separator_is_middot(self):
        result = _parse_result_summary('{"a": 1, "b": 2}')
        assert "·" in result

    def test_non_primitive_values_excluded(self):
        result = _parse_result_summary('{"count": 5, "nested": {"x": 1}}')
        assert "count: 5" in result
        assert "nested" not in result

    def test_invalid_json_returns_fallback(self):
        assert _parse_result_summary("not json") == "(invalid result_json)"

    def test_non_dict_json_returns_fallback(self):
        assert _parse_result_summary("[1, 2, 3]") == "(invalid result_json)"

    def test_empty_dict_returns_empty(self):
        assert _parse_result_summary("{}") == ""


class TestComputeDuration:
    def test_returns_dash_for_missing_finished_at(self):
        assert _compute_duration("2026-05-16T09:00:00+00:00", None) == "—"

    def test_returns_dash_for_missing_started_at(self):
        assert _compute_duration(None, "2026-05-16T09:00:00+00:00") == "—"

    def test_returns_dash_for_both_none(self):
        assert _compute_duration(None, None) == "—"

    def test_sub_minute_shown_in_seconds(self):
        start = "2026-05-16T09:00:00+00:00"
        end   = "2026-05-16T09:00:03+00:00"
        result = _compute_duration(start, end)
        assert "s" in result
        assert "3.0" in result

    def test_over_minute_shown_in_minutes(self):
        start = "2026-05-16T09:00:00+00:00"
        end   = "2026-05-16T09:02:00+00:00"
        result = _compute_duration(start, end)
        assert "m" in result


class TestRunBadgeStatus:
    def test_success_returns_success(self):
        run = {"status": "success", "finished_at": "x", "started_at": "y"}
        assert _run_badge_status(run, "z") == "success"

    def test_error_returns_error(self):
        run = {"status": "error", "finished_at": "x", "started_at": "y"}
        assert _run_badge_status(run, "z") == "error"

    def test_recent_running_returns_running(self):
        """A running job started 1 minute ago (within stuck window) stays 'running'."""
        recent = _iso(_now() - timedelta(minutes=1))
        stuck_cutoff = _iso(_now() - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES))
        run = {"status": "running", "finished_at": None, "started_at": recent}
        assert _run_badge_status(run, stuck_cutoff) == "running"

    def test_old_running_returns_stuck(self):
        """A running job started well before the stuck cutoff is 'stuck'."""
        old = _iso(_now() - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES + 30))
        stuck_cutoff = _iso(_now() - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES))
        run = {"status": "running", "finished_at": None, "started_at": old}
        assert _run_badge_status(run, stuck_cutoff) == "stuck"


class TestSchedulerHealth:
    def test_empty_runs_returns_never_run(self):
        health = _scheduler_health([], _stale_cutoff(), _stuck_cutoff())
        assert health["status"] == "never_run"

    def test_recent_success_returns_ok(self):
        runs = [{"status": "success", "finished_at": "x", "started_at": _iso(_now()),
                 "job_name": "j"}]
        health = _scheduler_health(runs, _stale_cutoff(), _stuck_cutoff())
        assert health["status"] == "ok"

    def test_old_run_returns_stale(self):
        old = _iso(_now() - timedelta(minutes=SCHEDULER_STALE_THRESHOLD_MINUTES + 10))
        runs = [{"status": "success", "finished_at": old, "started_at": old, "job_name": "j"}]
        health = _scheduler_health(runs, _stale_cutoff(), _stuck_cutoff())
        assert health["status"] == "stale"

    def test_old_running_job_returns_stuck(self):
        old = _iso(_now() - timedelta(minutes=SCHEDULER_STUCK_THRESHOLD_MINUTES + 10))
        runs = [{"status": "running", "finished_at": None, "started_at": old, "job_name": "j"}]
        health = _scheduler_health(runs, _stale_cutoff(), _stuck_cutoff())
        assert health["status"] == "stuck"

    def test_recent_running_job_returns_ok_not_stuck(self):
        recent = _iso(_now() - timedelta(minutes=1))
        runs = [{"status": "running", "finished_at": None, "started_at": recent,
                 "job_name": "j"}]
        # Stale cutoff is 15 min ago; recent is within that window → ok
        health = _scheduler_health(runs, _stale_cutoff(), _stuck_cutoff())
        assert health["status"] in ("ok", "running")
        assert health["status"] != "stuck"

    def test_stuck_takes_priority_over_stale(self):
        """If there is a stuck job, status is 'stuck' even if the latest run is also old."""
        old = _iso(_now() - timedelta(minutes=60))
        runs = [{"status": "running", "finished_at": None, "started_at": old, "job_name": "j"}]
        health = _scheduler_health(runs, _stale_cutoff(), _stuck_cutoff())
        assert health["status"] == "stuck"
